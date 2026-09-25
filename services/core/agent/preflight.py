"""
前置校验 —— 规划意图的关键信息完整性检查

在调用规划引擎前，检查用户输入是否包含生成行程所需的关键信息：
  - 目的地（必须）
  - 出行时间或天数（必须）

信息不全时生成追问提示，引导用户补充，避免生成低质量行程。
"""
import re
from typing import List, Optional

from shared.llm import LLMManager

# 常见城市名（用于判断是否提及目的地）
_DESTINATION_CITIES = [
    "北京", "上海", "杭州", "成都", "西安", "厦门", "丽江", "苏州",
    "南京", "重庆", "广州", "深圳", "三亚", "青岛", "昆明", "大理",
    "桂林", "张家界", "黄山", "哈尔滨", "大连", "武汉", "长沙",
    "西藏", "拉萨", "新疆", "青海", "甘肃", "海南", "香港", "澳门",
    "台北", "东京", "大阪", "京都", "首尔", "曼谷", "清迈", "巴黎",
    "伦敦", "纽约", "洛杉矶", "新加坡", "吉隆坡", "巴厘岛", "迪拜",
]

# 日期/时间关键词
_DATE_PATTERNS = [
    r"\d{1,2}月\d{1,2}[日号]",
    r"\d{4}[-/年]\d{1,2}[-/月]\d{0,2}日?",
    r"[下本]周[末一二三四五六日天]",
    r"[下本]个月",
    r"周[末一二三四五六日天]",
    r"今[天后明]",
    r"国庆|五一|春节|元旦|中秋|端午|清明",
]

# 天数关键词
_DURATION_PATTERNS = [
    r"\d+\s*[天日]",
    r"两\s*[天日]",
    r"半\s*月|一个[星周]?",
    r"[一两周]周",
]


class PreflightChecker:
    """
    前置校验器

    检查用户输入是否包含生成行程所需的关键信息，
    不全时返回追问提示。
    """

    def __init__(self, llm_manager: LLMManager = None):
        self.llm = llm_manager

    def check(self, user_input: str, session_id: str = "") -> Optional[str]:
        """
        检查关键信息完整性。

        Returns:
            None 表示信息齐全，可直接规划；
            str 表示缺失信息，返回值为追问提示。
        """
        missing = self._detect_missing(user_input)

        if not missing:
            return None

        # 用 LLM 生成自然追问（不可用时走规则模板）
        if self.llm and self.llm.is_available():
            followup = self._llm_followup(user_input, missing)
            if followup:
                return followup

        return self._rule_followup(user_input, missing)

    # ------------------------------------------------------------------
    # 缺失检测
    # ------------------------------------------------------------------
    def _detect_missing(self, text: str) -> List[str]:
        """检测用户输入中缺失的关键信息"""
        missing = []

        # 检测目的地
        if not self._has_destination(text):
            missing.append("destination")

        # 检测日期/天数
        if not self._has_date_or_duration(text):
            missing.append("date")

        return missing

    @staticmethod
    def _has_destination(text: str) -> bool:
        for city in _DESTINATION_CITIES:
            if city in text:
                return True
        # 泛化匹配：X去Y玩 / X到Y
        if re.search(r"[去到]\s*[\u4e00-\u9fff]{2,4}\s*[玩旅游]", text):
            return True
        return False

    @staticmethod
    def _has_date_or_duration(text: str) -> bool:
        for pattern in _DATE_PATTERNS:
            if re.search(pattern, text):
                return True
        for pattern in _DURATION_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    # ------------------------------------------------------------------
    # 追问生成
    # ------------------------------------------------------------------
    def _llm_followup(self, user_input: str, missing: List[str]) -> Optional[str]:
        """用 LLM 生成自然的追问提示"""
        missing_desc = "、".join(
            "目的地" if m == "destination" else "出行时间或天数" for m in missing
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是「行智」AI出行管家。用户想规划行程但缺少关键信息，"
                    "请用友好简洁的中文追问，一次只问最关键的1-2个问题。"
                    "只输出追问内容，不要多余解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户输入：{user_input}\n"
                    f"缺失信息：{missing_desc}\n"
                    "请生成追问。"
                ),
            },
        ]
        try:
            return self.llm.chat(messages, temperature=0.5, max_tokens=256)
        except Exception:
            return None

    @staticmethod
    def _rule_followup(user_input: str, missing: List[str]) -> str:
        """规则模板追问"""
        questions = []
        if "destination" in missing:
            questions.append("请问您想去哪里呢？")
        if "date" in missing:
            questions.append("您计划什么时候出发？大概玩几天？")

        prefix = "很高兴帮您规划行程！还需要确认几个信息：\n"
        return prefix + "\n".join(f"· {q}" for q in questions)
