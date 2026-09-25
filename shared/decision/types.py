"""System One 类型化决策原语 —— 本地最小实现（无外部依赖，不调 TypeSafe）。

镜像 `typesafe_sdk` 的问题 / 答案模型，结构上可直接对应官方 wire 格式，
用 pydantic 做校验，因此既能拿官方 SDK 的语义来读，也能独立跑。

三种问题原语（与官方沙箱一致，docs.typesafe.ai/primitives/*）：

    Noul   是/否问题。答案 `noul ∈ [0,1]` 是「是」的概率：
           趋近 1 判为是，趋近 0 判为否，0.5 附近表示不确定。
    Choice 从命名选项中选一个。答案是命中项 + 置信度 + 各选项概率分布。
    Score  按**有序**评分表打分（档位从 0 开始）。答案是各档位概率 + 图例。

与 LLM 的本质区别：这里的问题与答案都是**类型化的**，判定结果可被程序直接
消费（布尔/枚举/整数档位 + 置信度），不需要再解析自然语言，也不给模型留
「自由发挥」的空间 —— 这正是 System One 用来替代代码里 if/else 与
LLM-as-judge 的用法。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field


class DecisionError(RuntimeError):
    """类型化决策调用失败（底层 LLM 不可用 / HTTP 异常 / 输出无法满足结构）。"""


# ---------------------------------------------------------------------------
# 问题（Question）
# ---------------------------------------------------------------------------
class _Strict(BaseModel):
    """拒绝未声明字段，避免上游多吐字段时静默通过。"""

    model_config = ConfigDict(extra="forbid")


class NoulCriteria(_Strict):
    """可选：分别描述「是」与「否」两种结果各自的含义，用于消歧。"""

    true: Optional[str] = None
    false: Optional[str] = None


class Noul(_Strict):
    """是/否问题。"""

    type: Literal["noul"] = "noul"
    instructions: Optional[str] = None
    criteria: Optional[NoulCriteria] = None


class Choice(_Strict):
    """从命名选项中选一个；`criteria` = 选项标签 → 该选项的含义（可为 None）。"""

    type: Literal["choice"] = "choice"
    instructions: Optional[str] = None
    criteria: Dict[str, Optional[str]] = Field(default_factory=dict)


class Score(_Strict):
    """按有序评分表打分；`criteria` 从 0 档开始逐个描述。"""

    type: Literal["score"] = "score"
    instructions: Optional[str] = None
    criteria: List[str] = Field(default_factory=list)


Question = Union[Noul, Choice, Score]
Questions = Mapping[str, Question]
"""问题名 → 问题对象。名字用于回读答案，如 response.noul("authorized")。"""


# ---------------------------------------------------------------------------
# 答案（Answer）
# ---------------------------------------------------------------------------
class _AnswerBase(BaseModel):
    # 上游可能新增字段：忽略而不报错（前向兼容），与官方 SDK 的处理一致。
    model_config = ConfigDict(extra="ignore")


class NoulAnswer(_AnswerBase):
    """是/否答案。`noul` 即「是」的概率，官方模型没有单独的 confidence 字段。"""

    type: Literal["noul"] = "noul"
    noul: float

    @property
    def answer(self) -> bool:
        """按 0.5 阈值判是/否（与官方口径一致）。"""
        return self.noul >= 0.5

    @property
    def confidence(self) -> float:
        """距 0.5 的归一化距离：0 = 完全不确定，1 = 完全确定。"""
        return abs(self.noul - 0.5) * 2

    def __bool__(self) -> bool:  # 让 `if answer:` 直接可用
        return self.answer


class ChoiceAnswer(_AnswerBase):
    """选项答案：命中项 + 置信度 + 全量概率分布。"""

    type: Literal["choice"] = "choice"
    choice: str
    confidence: float = 1.0
    probabilities: Dict[str, float] = Field(default_factory=dict)

    def __str__(self) -> str:
        return self.choice


class ScoreAnswer(_AnswerBase):
    """评分答案：图例（档位 → 描述）+ 各档位概率。取概率最高档位为结论。"""

    type: Literal["score"] = "score"
    legend: Dict[int, str] = Field(default_factory=dict)
    probabilities: Dict[int, float] = Field(default_factory=dict)

    @property
    def score(self) -> Optional[int]:
        if not self.probabilities:
            return None
        return max(self.probabilities, key=lambda k: self.probabilities[k])

    @property
    def confidence(self) -> float:
        s = self.score
        if s is None:
            return 0.0
        return float(self.probabilities.get(s, 0.0))

    def __int__(self) -> int:
        return self.score or 0


Answer = Union[NoulAnswer, ChoiceAnswer, ScoreAnswer]
"""单个问题的答案，按 `type` 字段判别。"""


class Usage(BaseModel):
    """用量与耗时（由底层 LLM 统计回填）。"""

    model_config = ConfigDict(extra="ignore")

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    n_retries: int = 0
    """畸形结构的纠正重试次数（不含首次尝试）。"""


class DecisionResponse(BaseModel):
    """一次 `system_one` 调用的完整结果。"""

    model_config = ConfigDict(extra="ignore")

    model: str = ""
    answers: Dict[str, Answer] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)
    debug: Dict[str, Any] = Field(default_factory=dict)

    # -- 按类型回读 --
    @property
    def nouls(self) -> Dict[str, NoulAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, NoulAnswer)}

    @property
    def choices(self) -> Dict[str, ChoiceAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, ChoiceAnswer)}

    @property
    def scores(self) -> Dict[str, ScoreAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, ScoreAnswer)}

    def noul(self, name: str) -> Optional[NoulAnswer]:
        a = self.answers.get(name)
        return a if isinstance(a, NoulAnswer) else None

    def choice(self, name: str) -> Optional[ChoiceAnswer]:
        a = self.answers.get(name)
        return a if isinstance(a, ChoiceAnswer) else None

    def score(self, name: str) -> Optional[ScoreAnswer]:
        a = self.answers.get(name)
        return a if isinstance(a, ScoreAnswer) else None

    def boolean(self, name: str, default: bool = False, threshold: float = 0.5) -> bool:
        """便捷读法：是/否问题直接取布尔值，缺失或类型不符时给 default。"""
        a = self.noul(name)
        if a is None:
            return default
        return a.noul >= threshold
