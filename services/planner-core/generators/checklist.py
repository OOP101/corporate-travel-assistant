"""
出行清单生成器 —— 策程 · Planner Core

根据目的地气候、行程类型、同行人组成生成个性化出行清单。
LLM 不可用时降级到默认清单模板。
"""
import json
import logging
from typing import List

from shared.llm import LLMManager

logger = logging.getLogger("planner-core.generators.checklist")


class ChecklistGenerator:
    """
    出行清单生成器

    用法:
        gen = ChecklistGenerator(llm)
        items = gen.generate(trip_dict)
    """

    def __init__(self, llm_manager: LLMManager):
        self.llm = llm_manager

    def generate(self, trip: dict) -> List[str]:
        """
        根据行程生成出行清单。

        Args:
            trip: Trip.to_dict() 行程字典

        Returns:
            清单项列表 (按类别组织)
        """
        if not self.llm.is_available():
            logger.info("LLM 不可用，使用默认清单模板")
            return self._default_checklist(trip)

        try:
            messages = self._build_prompt(trip)
            data = self.llm.chat_json(messages, temperature=0.3, max_tokens=1024)
            items = data.get("checklist", [])
            if not items:
                return self._default_checklist(trip)
            logger.info(f"清单生成完成: {len(items)} 项")
            return items
        except Exception as e:
            logger.error(f"清单生成失败，降级到默认模板: {e}")
            return self._default_checklist(trip)

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------
    def _build_prompt(self, trip: dict) -> list:
        """构建清单生成 prompt。"""
        destination = trip.get("destination", "未指定")
        start_date = trip.get("start_date", "")
        end_date = trip.get("end_date", "")
        party = trip.get("travel_party", [])
        party_desc = "、".join(
            f"{m.get('name', '')}({m.get('role', 'adult')}, {m.get('age', 0)}岁)"
            for m in party
        ) or "成人1人"
        days = trip.get("days", [])
        themes = "；".join(d.get("theme", "") for d in days if d.get("theme"))

        system = (
            "你是出行清单规划助手。根据目的地气候、行程主题、同行人组成，"
            "生成分类清晰、实用的出行清单。只输出 JSON，不要解释。"
        )
        user = f"""请生成出行清单，输出 JSON:
{{"checklist": ["证件类: ...", "衣物类: ...", ...]}}

目的地: {destination}
日期: {start_date} ~ {end_date}
同行人: {party_desc}
行程主题: {themes}

要求:
1. 按类别组织 (证件类、衣物类、电子设备、洗漱用品、药品类、其他)。
2. 结合目的地当季气候推荐衣物。
3. 同行人含儿童/老人时增加专用物品。
4. 含境外目的地时增加护照/签证/转换插头等。
"""
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ------------------------------------------------------------------
    # 默认清单模板 (降级)
    # ------------------------------------------------------------------
    def _default_checklist(self, trip: dict) -> List[str]:
        """基础清单模板，根据同行人微调。"""
        party = trip.get("travel_party", [])
        has_child = any(m.get("role") == "child" for m in party)
        has_elder = any(m.get("role") == "elder" for m in party)
        destination = trip.get("destination", "")

        items = [
            "证件类: 身份证、户口本(儿童)",
            "衣物类: 换洗衣物(按天数+1套)、舒适步行鞋、外套(防温差)",
            "电子设备: 手机充电器、充电宝、数据线、耳机",
            "洗漱用品: 牙刷牙膏、毛巾、洗面奶、防晒霜",
            "药品类: 感冒药、肠胃药、创可贴、晕车药",
            "其他: 雨伞、水杯、少量现金、垃圾袋",
        ]

        if has_child:
            items.append("儿童专用: 儿童水壶、零食、湿巾、备用衣物")
        if has_elder:
            items.append("老人专用: 常用降压/降糖药、保温杯、折叠拐杖")

        # 简易气候判断
        dest_lower = destination
        summer_dests = ["三亚", "厦门", "广州", "深圳", "丽江"]
        winter_dests = ["哈尔滨", "长白山", "漠河"]
        if any(d in dest_lower for d in summer_dests):
            items.append("防晒类: 防晒衣、墨镜、晒后修复")
        if any(d in dest_lower for d in winter_dests):
            items.append("保暖类: 羽绒服、保暖内衣、手套、围巾")

        return items
