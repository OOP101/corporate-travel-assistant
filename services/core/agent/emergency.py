"""
应急协助模块 —— 行智 · Journey Hub

提供标准化应急指引，包括：
  - 当地应急电话（警察/急救/使馆/投诉）
  - 证件丢失应对指引（按国家/城市）
  - 就近医院/药店导航
  - 旅行保险报案指引
  - 紧急联系人通知指引

对应需求文档 F2.5 应急协助（P1）。
"""
import re
from typing import Dict, Any, Optional


import json
import os
from typing import Dict, Any, Optional

# ---------------------------------------------------------------------------
# 应急数据（外置 JSON，便于运营维护更新，无需改代码）
# ---------------------------------------------------------------------------
_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emergency_data.json")
with open(_DATA_PATH, "r", encoding="utf-8") as _f:
    _EMERGENCY_DATA = json.load(_f)

DOMESTIC_EMERGENCY: Dict[str, Any] = _EMERGENCY_DATA["domestic_emergency"]
INTERNATIONAL_EMERGENCY: Dict[str, Any] = _EMERGENCY_DATA["international_emergency"]
DOCUMENT_LOST_GUIDE: Dict[str, Any] = _EMERGENCY_DATA["document_lost_guide"]
EMERGENCY_CATEGORIES: Dict[str, Dict[str, list]] = _EMERGENCY_DATA["emergency_categories"]


class EmergencyAssistant:
    """
    应急协助处理器

    根据用户输入匹配应急类别，返回结构化指引。
    LLM 可用时辅助生成个性化指引文案，不可用时走规则模板。
    """

    def __init__(self, llm_manager=None):
        self.llm = llm_manager

    def handle(self, query: str, session_id: str = "default") -> str:
        """
        处理应急协助请求。

        Args:
            query: 用户输入
            session_id: 会话 ID

        Returns:
            应急指引文本
        """
        category = self._classify_query(query)
        destination = self._detect_destination(query)

        if category == "phone":
            return self._emergency_phones(destination)
        if category == "document":
            return self._document_lost_guide(destination)
        if category == "medical":
            return self._medical_guide()
        if category == "insurance":
            return self._insurance_guide()
        if category == "contact":
            return self._emergency_contact_guide()

        # 兜底：综合应急指引
        return self._comprehensive_guide(query, destination)

    # ------------------------------------------------------------------
    # 分类
    # ------------------------------------------------------------------
    @staticmethod
    def _classify_query(query: str) -> Optional[str]:
        """将用户输入匹配到应急类别"""
        for category, keywords in EMERGENCY_CATEGORIES.items():
            for kw in keywords:
                if kw in query:
                    return category
        return None

    @staticmethod
    def _detect_destination(query: str) -> str:
        """从输入中提取目的地"""
        all_dests = list(INTERNATIONAL_EMERGENCY.keys())
        for dest in all_dests:
            if dest in query:
                return dest
        # 检查是否境外
        overseas_hints = ["出国", "境外", "海外", "国外", "旅游"]
        if any(h in query for h in overseas_hints):
            return "international_generic"
        return "domestic"

    # ------------------------------------------------------------------
    # 各类指引生成
    # ------------------------------------------------------------------
    def _emergency_phones(self, destination: str) -> str:
        """生成应急电话指引"""
        lines = ["🚨 应急电话一览"]

        if destination in INTERNATIONAL_EMERGENCY:
            info = INTERNATIONAL_EMERGENCY[destination]
            lines.append(f"\n📍 {destination}：")
            for key, value in info.items():
                label = key.replace("_", " ").title()
                lines.append(f"  · {label}: {value}")
        elif destination == "international_generic":
            lines.append("\n⚠️ 请告诉我您的具体目的地国家，我可以提供当地的应急电话和使馆联系方式。")
            lines.append(f"\n🌐 外交部全球领事保护热线：+86-10-12308")
        else:
            info = DOMESTIC_EMERGENCY["通用"]
            lines.append("\n📍 中国大陆通用应急电话：")
            label_map = {
                "police": "报警", "ambulance": "急救", "fire": "火警",
                "traffic_accident": "交通事故", "consumer_complaint": "消费者投诉",
                "tourism_complaint": "旅游投诉", "weather_hotline": "天气查询",
            }
            for key, value in info.items():
                lines.append(f"  · {label_map.get(key, key)}: {value}")

        lines.append("\n💡 外交部全球领事保护热线：+86-10-12308（境外遇险24小时）")
        return "\n".join(lines)

    def _document_lost_guide(self, destination: str) -> str:
        """证件丢失指引"""
        lines = ["📋 证件丢失应对指引"]

        if destination in INTERNATIONAL_EMERGENCY or destination == "international_generic":
            lines.append(f"\n{DOCUMENT_LOST_GUIDE['international']}")
            if destination in INTERNATIONAL_EMERGENCY:
                embassy_info = INTERNATIONAL_EMERGENCY[destination]
                lines.append(
                    f"\n📍 {destination}使馆联系方式：{embassy_info.get('embassy_cn', '请查询')} "
                    f"({embassy_info.get('embassy_cn_note', '')})"
                )
        else:
            lines.append(f"\n{DOCUMENT_LOST_GUIDE['domestic']['id_card']}")
            lines.append(f"\n{DOCUMENT_LOST_GUIDE['domestic']['passport_domestic']}")

        return "\n".join(lines)

    def _medical_guide(self) -> str:
        """就医指引"""
        return f"🏥 {MEDICAL_GUIDE}"

    def _insurance_guide(self) -> str:
        """保险报案指引"""
        return f"🛡️ {INSURANCE_CLAIM_GUIDE}"

    def _emergency_contact_guide(self) -> str:
        """紧急联系人通知指引"""
        return (
            "📞 紧急联系人通知：\n"
            "1. 请提前在旅行前设置好紧急联系人信息；\n"
            "2. 遇到紧急情况，第一时间通知家人/朋友您的位置和状况；\n"
            "3. 如无法自行联系，可请酒店前台或当地使领馆协助联系；\n"
            "4. 境外遇险可拨打外交部领事保护热线 +86-10-12308 请求协助。"
        )

    def _comprehensive_guide(self, query: str, destination: str) -> str:
        """综合应急指引（兜底）"""
        lines = [
            "🆘 应急协助",
            "",
            "我可以为您提供以下应急协助：",
            "",
            "1. 📞 应急电话 — 查看目的地的报警/急救/使馆电话",
            "2. 📋 证件丢失 — 护照/身份证丢失的补办指引",
            "3. 🏥 就医导航 — 附近医院/药店指引",
            "4. 🛡️ 保险报案 — 旅行保险理赔流程指引",
            "5. 📞 紧急联系 — 通知家人和领事保护",
            "",
            "请告诉我您遇到了什么情况，或直接说「应急电话」查看目的地的应急号码。",
        ]

        # 如果提到具体目的地，附带电话
        if destination in INTERNATIONAL_EMERGENCY:
            lines.append("")
            lines.append(self._emergency_phones(destination))

        return "\n".join(lines)
