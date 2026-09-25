"""
应变重排引擎 —— 策程 · Planner Core

当行程中的某项活动发生变更（景点闭园、航班延误、用户主动调整）时，
重新排列当日及后续受影响的活动时间线，保持行程整体连贯。

重排策略：
  1. 移除/取消活动 → 后续活动前移填补空档，可选 LLM 推荐替代方案
  2. 延迟活动 → 后续活动顺延，超出 22:00 的活动标记为"需调整"
  3. 时间缩短/延长 → 重新计算后续活动起始时间
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from shared.llm import LLMManager

logger = logging.getLogger("core.generation.reroute")


def _to_minutes(time_str: str) -> int:
    """HH:MM → 当日分钟数"""
    if not time_str or ":" not in time_str:
        return 0
    try:
        h, m = time_str.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, IndexError):
        return 0


def _to_time_str(minutes: int) -> str:
    """分钟数 → HH:MM"""
    minutes = max(0, min(23 * 60 + 59, minutes))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _activity_duration(act: dict) -> int:
    """活动持续时长（分钟）"""
    start = _to_minutes(act.get("time_start", ""))
    end = _to_minutes(act.get("time_end", ""))
    return max(0, end - start)


class RerouteEngine:
    """
    应变重排引擎

    用法:
        engine = RerouteEngine(llm)
        updated_trip = engine.reroute(trip_dict, changed_activity, reason)
    """

    # 当日活动时间窗口
    DAY_START = 9 * 60   # 09:00
    DAY_END = 22 * 60    # 22:00
    # 活动间最小间隔（分钟）
    MIN_GAP = 10

    def __init__(self, llm_manager: LLMManager = None):
        self.llm = llm_manager

    def reroute(
        self,
        trip: dict,
        changed_activity: dict,
        reason: str = "",
    ) -> dict:
        """
        重排行程。

        Args:
            trip: 完整行程字典
            changed_activity: 变更的活动（含 title 用于匹配）
            reason: 变更原因（closed/delayed/removed/shortened/extended）

        Returns:
            更新后的行程字典，含 reroute_summary 字段
        """
        changed_title = changed_activity.get("title", "")
        change_type = self._detect_change_type(reason, changed_activity)

        summary_parts = []
        replacement = None

        for day in trip.get("days", []):
            activities = day.get("activities", [])

            # 找到变更活动的位置
            target_idx = self._find_activity(activities, changed_title)

            if target_idx is None:
                continue

            target = activities[target_idx]
            old_duration = _activity_duration(target)

            if change_type in ("closed", "removed"):
                # 景点闭园/移除：标记并尝试替代
                target["status"] = "skipped"
                target["tips"] = f"[已移除] {reason}. {target.get('tips', '')}"

                # LLM 推荐替代方案
                replacement = self._suggest_replacement(trip, day, target)

                if replacement:
                    # 在目标位置插入替代活动，时长取原活动时长
                    replacement["time_start"] = target.get("time_start", "")
                    replacement["time_end"] = target.get("time_end", "")
                    replacement["status"] = "scheduled"
                    activities[target_idx] = replacement
                    summary_parts.append(
                        f"「{changed_title}」已移除，推荐替代：{replacement.get('title', '未知')}"
                    )
                else:
                    # 无替代，后续活动前移
                    activities.pop(target_idx)
                    self._shift_forward(activities, target_idx, old_duration)
                    summary_parts.append(f"「{changed_title}」已移除，后续活动前移{old_duration}分钟")

            elif change_type == "delayed":
                # 延迟：获取新时长，后续顺延
                new_duration = _activity_duration(changed_activity)
                delay = max(0, new_duration - old_duration)
                target["time_end"] = changed_activity.get("time_end", target.get("time_end", ""))
                target["status"] = "changed"
                target["tips"] = f"[已调整] {reason}. {target.get('tips', '')}"
                self._shift_backward(activities, target_idx + 1, delay)
                summary_parts.append(f"「{changed_title}」延迟{delay}分钟，后续活动顺延")

            elif change_type in ("shortened", "extended"):
                # 时长变更：重新计算后续时间
                new_end = changed_activity.get("time_end", target.get("time_end", ""))
                target["time_end"] = new_end
                target["status"] = "changed"
                target["tips"] = f"[已调整] {reason}. {target.get('tips', '')}"
                # 以新结束时间为基准重排后续
                self._realign(activities, target_idx)
                summary_parts.append(f"「{changed_title}」时长已调整，后续活动时间已重排")

            else:
                # 通用变更
                target["status"] = "changed"
                target["tips"] = f"[已调整] {reason}. {target.get('tips', '')}"
                self._realign(activities, target_idx)
                summary_parts.append(f"「{changed_title}」已调整，当日时间线已重排")

            day["activities"] = activities
            break  # 只处理匹配到的第一天

        trip["reroute_summary"] = "；".join(summary_parts) or "未找到匹配活动"
        return trip

    # ------------------------------------------------------------------
    # 变更类型识别
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_change_type(reason: str, activity: dict) -> str:
        """从原因文本推断变更类型"""
        reason_lower = (reason or "").lower()
        if any(kw in reason_lower for kw in ("闭园", "关闭", "closed", "cancel", "取消", "移除", "removed")):
            return "closed"
        if any(kw in reason_lower for kw in ("延误", "延迟", "delay", "晚点")):
            return "delayed"
        if any(kw in reason_lower for kw in ("缩短", "shortened", "提前结束")):
            return "shortened"
        if any(kw in reason_lower for kw in ("延长", "extended", "加时")):
            return "extended"
        if any(kw in reason_lower for kw in ("删除", "去掉", "不去")):
            return "removed"
        return "changed"

    @staticmethod
    def _find_activity(activities: List[dict], title: str) -> Optional[int]:
        """在当日活动中查找匹配的活动索引"""
        if not title:
            return None
        for i, act in enumerate(activities):
            if act.get("title") == title:
                return i
        # 模糊匹配
        for i, act in enumerate(activities):
            if title in act.get("title", ""):
                return i
        return None

    # ------------------------------------------------------------------
    # 时间重排算法
    # ------------------------------------------------------------------
    def _shift_forward(self, activities: List[dict], start_idx: int, freed_minutes: int):
        """后续活动前移，填补空出的时间"""
        if start_idx >= len(activities) or freed_minutes <= 0:
            return
        for i in range(start_idx, len(activities)):
            act = activities[i]
            start = _to_minutes(act.get("time_start", ""))
            end = _to_minutes(act.get("time_end", ""))
            duration = end - start
            new_start = max(self.DAY_START, start - freed_minutes)
            act["time_start"] = _to_time_str(new_start)
            act["time_end"] = _to_time_str(new_start + duration)

    def _shift_backward(self, activities: List[dict], start_idx: int, delay_minutes: int):
        """后续活动顺延"""
        if start_idx >= len(activities) or delay_minutes <= 0:
            return
        for i in range(start_idx, len(activities)):
            act = activities[i]
            start = _to_minutes(act.get("time_start", ""))
            end = _to_minutes(act.get("time_end", ""))
            duration = end - start
            new_start = start + delay_minutes
            if new_start + duration > self.DAY_END:
                act["status"] = "changed"
                act["tips"] = f"[超出当日时间窗] 原计划{act.get('time_start','')}，建议调整到次日或取消。{act.get('tips','')}"
            act["time_start"] = _to_time_str(new_start)
            act["time_end"] = _to_time_str(new_start + duration)

    def _realign(self, activities: List[dict], from_idx: int):
        """从指定位置开始重新对齐后续活动时间，保持活动间最小间隔"""
        if from_idx >= len(activities):
            return
        # 前一项的结束时间
        prev_end = _to_minutes(activities[from_idx].get("time_end", ""))
        for i in range(from_idx + 1, len(activities)):
            act = activities[i]
            start = _to_minutes(act.get("time_start", ""))
            end = _to_minutes(act.get("time_end", ""))
            duration = max(15, end - start)
            new_start = max(prev_end + self.MIN_GAP, start)
            if new_start + duration > self.DAY_END:
                act["status"] = "changed"
                act["tips"] = f"[超出当日时间窗] 建议调整到次日。{act.get('tips','')}"
            act["time_start"] = _to_time_str(new_start)
            act["time_end"] = _to_time_str(new_start + duration)
            prev_end = new_start + duration

    # ------------------------------------------------------------------
    # LLM 替代景点推荐
    # ------------------------------------------------------------------
    def _suggest_replacement(
        self,
        trip: dict,
        day: dict,
        removed_act: dict,
    ) -> Optional[dict]:
        """用 LLM 推荐同区域替代景点；LLM 不可用走规则兜底"""
        if not self.llm or not self.llm.is_available():
            return self._rule_replacement(removed_act, day)

        try:
            destination = trip.get("destination", "")
            day_theme = day.get("theme", "")
            removed_type = removed_act.get("type", "attraction")
            loc = removed_act.get("location", {})
            loc_name = loc.get("name", "") if isinstance(loc, dict) else ""

            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是行程应变助手。用户行程中某项活动无法进行，"
                        "请推荐一个同区域的替代活动。只输出 JSON，不要解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"""请推荐替代活动，输出 JSON:
{{
  "type": "attraction|dining|rest|shopping|other",
  "title": "替代活动名称",
  "location": {{"name": "地点名", "lat": 0.0, "lng": 0.0, "address": "地址"}},
  "ticket_price": 0,
  "booking_required": false,
  "tips": "推荐理由",
  "estimated_cost": 0
}}

目的地: {destination}
当日主题: {day_theme}
被替换活动: {removed_act.get('title','')} ({removed_type})
位置: {loc_name}

要求: 替代活动应与原活动类型相近，在同区域，适合当日主题。""",
                },
            ]
            data = self.llm.chat_json(messages, temperature=0.5, max_tokens=512)
            if data.get("title"):
                logger.info(f"LLM 推荐替代: {data['title']}")
                return data
        except Exception as e:
            logger.warning(f"LLM 替代推荐失败: {e}")

        return self._rule_replacement(removed_act, day)

    @staticmethod
    def _rule_replacement(removed_act: dict, day: dict) -> Optional[dict]:
        """规则兜底替代方案"""
        act_type = removed_act.get("type", "attraction")
        # 根据类型给出通用替代
        fallbacks = {
            "attraction": {
                "type": "rest",
                "title": "周边休闲漫步",
                "location": {"name": "附近街区", "lat": 0, "lng": 0, "address": ""},
                "ticket_price": 0,
                "booking_required": False,
                "tips": "原景点不可用，改为周边休闲漫步，灵活度更高。",
                "estimated_cost": 0,
            },
            "dining": {
                "type": "dining",
                "title": "附近餐厅",
                "location": {"name": "就近选择", "lat": 0, "lng": 0, "address": ""},
                "ticket_price": 0,
                "booking_required": False,
                "tips": "原餐厅不可用，就近选择其他餐厅。",
                "estimated_cost": 100,
            },
        }
        return fallbacks.get(act_type, fallbacks["attraction"])
