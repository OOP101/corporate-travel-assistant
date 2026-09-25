"""shared.decision —— System One 类型化决策层（本地最小实现）。

把「非结构化状态 + 类型化问题 → 类型化答案 + 置信度」的判定能力，接到
已有的 OpenAI 兼容 LLM（腾讯 TokenHub）上，用于替代散落在业务代码里的
关键词正则与 LLM-as-judge。

    from shared.decision import DecisionClient, Noul, NoulCriteria, ask_noul

    client = DecisionClient(llm_manager)
    ok = ask_noul(
        client,
        state=user_text,
        instructions="用户是否授权由助手自行决定、不必再澄清？",
        criteria=NoulCriteria(true="明确表示不必再问", false="只是随口一说"),
        default=False,
    )

设计取向：**纯增益、可降级**。判定层任何异常都不上抛，调用方拿到 `default`
后继续走原有规则分支，因此接入风险仅在于「多一次判定」而不在于「改坏原逻辑」。
"""
from .client import DecisionClient, SystemOneAdapterClient, build_messages, coerce_answers
from .guard import ask_choice, ask_noul, ask_score, cache_info, clear_cache
from .types import (
    Answer,
    Choice,
    ChoiceAnswer,
    DecisionError,
    DecisionResponse,
    Noul,
    NoulAnswer,
    NoulCriteria,
    Question,
    Questions,
    Score,
    ScoreAnswer,
    Usage,
)

__all__ = [
    # 类型化原语
    "Noul",
    "NoulCriteria",
    "Choice",
    "Score",
    "Question",
    "Questions",
    "Answer",
    "NoulAnswer",
    "ChoiceAnswer",
    "ScoreAnswer",
    "Usage",
    "DecisionResponse",
    "DecisionError",
    # 客户端
    "DecisionClient",
    "SystemOneAdapterClient",
    "build_messages",
    "coerce_answers",
    # 守卫
    "ask_noul",
    "ask_choice",
    "ask_score",
    "clear_cache",
    "cache_info",
]
