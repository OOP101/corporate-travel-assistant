"""
意图路由 —— plan / chat / manage 三级分类

职责：解析用户输入，判断意图类型并路由到对应处理节点。

分类规则（按优先级）：
  1. MANAGE → 查看行程、修改、取消、删除、归档、总结等管理动作
  2. PLAN   → 规划、行程、安排、攻略、旅游、出差等规划意图
  3. CHAT   → 通用旅行问答（默认兜底）
"""
import re
from enum import Enum


class Intent(Enum):
    """意图枚举"""
    PLAN = "plan"           # 行程规划
    CHAT = "chat"           # 智能问答
    MANAGE = "manage"       # 行程管理
    EMERGENCY = "emergency" # 应急协助


class IntentRouter:
    """
    规则 + 关键词意图分类器

    生产环境可替换为 LLM 分类（用轻量模型做 few-shot）。
    """

    def __init__(self):
        # 应急关键词（最高优先级）
        self._emergency_keywords = [
            "应急", "急救", "报警", "丢失", "丢了", "生病",
            "受伤", "医院", "药店", "使馆", "领事馆",
            "保险报案", "理赔", "紧急联系",
        ]

        # 三级关键词表（按优先级从高到低）
        self._manage_keywords = [
            "查看行程", "修改", "取消", "删除", "我的行程",
            "行程列表", "归档", "总结", "改名", "重命名",
        ]

        self._plan_keywords = [
            "规划", "行程", "安排", "攻略", "去", "玩",
            "几日游", "自由行",
            # 注意："出差/旅游/旅行" 单词太宽（"出差报销""旅游保险"是问答），
            # 由 _plan_patterns 的 (出差|旅游|旅行).*(安排|规划) 精确兜住
        ]

        self._manage_patterns = [
            re.compile(r"(查看|列出|显示|看看|看下|查下).{0,6}(行程|计划|订单|记录)"),
            re.compile(r"(修改|更新|调整).*(行程|计划|时间|地点)"),
            re.compile(r"(取消|删除|移除).*(行程|计划|活动)"),
            re.compile(r"(归档|总结).*(行程|旅行)"),
            re.compile(r"(把|将).*(改名为?|改成|重命名).*"),
        ]

        self._plan_patterns = [
            re.compile(r"(规划|安排|制定).*(行程|路线|计划|攻略)"),
            re.compile(r"去.{0,10}玩"),
            re.compile(r"(几日游|自由行|跟团游)"),
            re.compile(r"(出差|旅游|旅行).*(安排|规划)"),
            # "出差/旅行"但排除问答场景（报销/补贴/保险等是问答不是规划）
            re.compile(r"(出差|旅行|旅游)(?!.*(报销|补贴|保险|材料|标准|制度|流程|发票|机票|需要|哪些|怎么办|怎么选))"),
            # 裸"城市→城市"说法（可带日期前缀与"出差/旅行"等后缀）：
            # 如"广州飞北京"、"9月15号广州飞北京出差"、"广州到北京"。
            # 到达地为中文限 2~4 字且句尾，避免误伤"广州飞北京的机票多少钱"
            re.compile(r"^[\u4e00-\u9fa5a-z0-9]{2,12}\s*(?:直飞|飞往|飞|到|至|—|—|→)\s*(?:[\u4e00-\u9fa5]{2,4}|[a-z]{2,12})(?:出差|旅行|旅游|游玩)?[\u4e00-\u9fa5]{0,3}$"),
            # "飞北京"/"飞往北京" 这类省略出发地的短句（整句仅目的地），按规划意图处理
            re.compile(r"^飞往?(?:[\u4e00-\u9fa5]{2,4}|[a-z]{2,12})$"),
        ]

        self._emergency_patterns = [
            re.compile(r"(护照|身份证|证件).*(丢|遗失|不见)"),
            re.compile(r"(应急|急救|急救电话|报警电话|医院|药店).{0,6}(电话|在哪|附近|怎么)"),
            re.compile(r"(保险).*(报案|理赔)"),
            re.compile(r"(紧急).*(联系|通知|求助)"),
        ]

        # “去”作为规划关键词时的排除短语（多为旅行问答而非规划意图）
        self._go_excludes = [
            "必去", "值得去", "推荐去", "可以去", "应该去", "适合去",
            "怎么去", "如何去", "怎样去", "去哪", "去哪儿", "哪里去",
            "好去处", "想去吗", "要不要去",
        ]
        # “玩”作为规划关键词时的排除短语
        self._play_excludes = [
            "好玩", "怎么玩", "玩什么", "玩啥", "去哪玩", "哪儿玩", "哪里玩",
        ]

    def classify(self, user_input: str) -> Intent:
        """
        分类用户输入的意图

        Args:
            user_input: 用户输入文本

        Returns:
            Intent 枚举值
        """
        text = user_input.strip().lower()

        if not text:
            return Intent.CHAT

        # 0. 应急意图（最高优先级，安全相关）
        for pattern in self._emergency_patterns:
            if pattern.search(text):
                return Intent.EMERGENCY
        for kw in self._emergency_keywords:
            if kw in text:
                return Intent.EMERGENCY

        # 1. 正则模式匹配（最精确）
        for pattern in self._manage_patterns:
            if pattern.search(text):
                return Intent.MANAGE

        for pattern in self._plan_patterns:
            if pattern.search(text):
                return Intent.PLAN

        # 2. 管理关键词（优先级高于规划）
        for kw in self._manage_keywords:
            if kw in text:
                return Intent.MANAGE

        # 3. 规划关键词
        for kw in self._plan_keywords:
            if kw not in text:
                continue
            # “去”/“玩”过于常见（必去的景点、哪儿好玩），仅在非问答语境下视为规划
            if kw == "去" and any(ex in text for ex in self._go_excludes):
                continue
            if kw == "玩" and any(ex in text for ex in self._play_excludes):
                continue
            return Intent.PLAN

        # 4. 兜底 → 智能问答
        return Intent.CHAT
