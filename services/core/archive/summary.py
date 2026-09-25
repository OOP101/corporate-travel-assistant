"""
行后归档 —— 策程 · Planner Core

生成行程总结: 概览、每日回顾、偏差分析、花费统计。
LLM 不可用时降级到规则模板。
"""
import json
import logging
from typing import List

from shared.llm import LLMManager

logger = logging.getLogger("core.archive.summary")


class SummaryGenerator:
    """
    行后总结生成器

    用法:
        gen = SummaryGenerator(llm)
        summary = gen.generate(trip_dict)
    """

    def __init__(self, llm_manager: LLMManager):
        self.llm = llm_manager

    def generate(self, trip: dict) -> dict:
        """
        生成行程总结。

        Args:
            trip: Trip.to_dict() 行程字典

        Returns:
            {overview, daily_recap, deviation_analysis, expense_summary}
        """
        if not self.llm.is_available():
            logger.info("LLM 不可用，使用规则模板生成总结")
            return self._rule_summary(trip)

        try:
            messages = self._build_prompt(trip)
            data = self.llm.chat_json(messages, temperature=0.3, max_tokens=2048)
            # 补全结构字段
            data.setdefault("overview", "")
            data.setdefault("daily_recap", [])
            data.setdefault("deviation_analysis", "")
            data.setdefault("expense_summary", {})
            # 合并规则计算的花费统计 (保证数值准确)
            data["expense_summary"] = self._calc_expenses(trip, data.get("expense_summary"))
            logger.info("行程总结生成完成")
            return data
        except Exception as e:
            logger.error(f"总结生成失败，降级到规则模板: {e}")
            return self._rule_summary(trip)

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------
    def _build_prompt(self, trip: dict) -> list:
        """构建总结生成 prompt。"""
        title = trip.get("title", "")
        destination = trip.get("destination", "")
        days = trip.get("days", [])
        party = trip.get("travel_party", [])

        system = (
            "你是行程归档分析助手。基于行程数据生成行后总结，"
            "包括概览、每日回顾、偏差分析(计划 vs 实际)和花费统计。"
            "只输出 JSON，不要解释。"
        )
        user = f"""请生成行程总结，输出 JSON:
{{
  "overview": "整体概览 (目的地、天数、同行人、总花费)",
  "daily_recap": [
    {{"date": "YYYY-MM-DD", "theme": "主题", "highlights": "当日亮点", "completed": 3, "skipped": 0}}
  ],
  "deviation_analysis": "计划执行偏差分析 (哪些活动未完成/调整及原因)",
  "expense_summary": {{"total": 0, "by_category": {{"attraction": 0, "dining": 0, "transport": 0, "shopping": 0, "other": 0}}}}
}}

行程数据:
{json.dumps(trip, ensure_ascii=False, indent=2)}

注意:
1. overview 须涵盖 {destination} {len(days)} 天行程的核心信息。
2. daily_recap 数量与 days 一致。
3. 根据各活动的 status (scheduled/completed/skipped/changed) 做偏差分析。
4. expense_summary 的 by_category 按 activity type 归类预估花费。
"""
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ------------------------------------------------------------------
    # 规则模板 (降级)
    # ------------------------------------------------------------------
    def _rule_summary(self, trip: dict) -> dict:
        """无 LLM 时基于规则的总结模板。"""
        destination = trip.get("destination", "未指定")
        days: List[dict] = trip.get("days", [])
        party = trip.get("travel_party", [])
        party_desc = "、".join(
            f"{m.get('name', '')}({m.get('role', 'adult')})" for m in party
        ) or "1人"

        # 概览
        overview = (
            f"本次行程前往{destination}，共{len(days)}天，"
            f"同行{party_desc}，预算¥{trip.get('budget_total', 0)}。"
        )

        # 每日回顾
        daily_recap = []
        for day in days:
            acts = day.get("activities", [])
            completed = sum(1 for a in acts if a.get("status") == "completed")
            skipped = sum(1 for a in acts if a.get("status") == "skipped")
            changed = sum(1 for a in acts if a.get("status") == "changed")
            highlights = "、".join(a.get("title", "") for a in acts[:3] if a.get("title"))
            daily_recap.append({
                "date": day.get("date", ""),
                "theme": day.get("theme", ""),
                "highlights": highlights or "—",
                "completed": completed,
                "skipped": skipped,
                "changed": changed,
            })

        # 偏差分析
        total_acts = sum(len(d.get("activities", [])) for d in days)
        total_skipped = sum(
            1 for d in days for a in d.get("activities", []) if a.get("status") == "skipped"
        )
        total_changed = sum(
            1 for d in days for a in d.get("activities", []) if a.get("status") == "changed"
        )
        deviation = f"共安排 {total_acts} 项活动"
        if total_skipped or total_changed:
            deviation += f"，其中 {total_skipped} 项跳过、{total_changed} 项调整"
            deviation += "。建议后续关注天气与交通预警，提前预留缓冲时间。"
        else:
            deviation += "，全部按计划执行 (演示数据中均为 scheduled 状态)。"

        # 花费统计
        expense_summary = self._calc_expenses(trip, {})

        return {
            "overview": overview,
            "daily_recap": daily_recap,
            "deviation_analysis": deviation,
            "expense_summary": expense_summary,
        }

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_expenses(trip: dict, llm_summary: dict) -> dict:
        """基于活动数据计算花费统计 (优先于 LLM 估算，保证数值准确)。"""
        by_category = {
            "attraction": 0.0, "dining": 0.0, "transport": 0.0,
            "shopping": 0.0, "accommodation": 0.0, "other": 0.0,
        }
        party_size = max(1, len(trip.get("travel_party", [])) or 1)

        for day in trip.get("days", []):
            for act in day.get("activities", []):
                act_type = act.get("type", "other")
                cost = float(act.get("estimated_cost", 0) or 0)
                ticket = float(act.get("ticket_price", 0) or 0)
                # 门票按人数计，其他花费按单人估算
                line = cost * party_size + ticket * party_size if act_type == "attraction" else cost * party_size
                cat = act_type if act_type in by_category else "other"
                by_category[cat] += line

        # 取整
        by_category = {k: round(v, 2) for k, v in by_category.items()}
        total = round(sum(by_category.values()), 2)

        return {
            "total": total,
            "by_category": by_category,
            "budget_total": float(trip.get("budget_total", 0) or 0),
            "budget_diff": round(total - float(trip.get("budget_total", 0) or 0), 2),
        }
