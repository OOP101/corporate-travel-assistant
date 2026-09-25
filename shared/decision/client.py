"""DecisionClient —— 用任意 OpenAI 兼容 LLM 兜底实现 System One 的类型化决策。

对应官方 `typesafe-ai/system-one-adapter-python` 的定位：**把「类型化问题 →
类型化答案」的判定层，接到一个通用 LLM 上**，从而在拿不到 TypeSafe key 的
环境里也能跑同一套范式（官方那个包是为了拿 LLM 和 TypeSafe 做对比；我们这里
是为了把决策层落到已有基础设施上）。

与官方适配器的差异（有意为之，够用即止）：
  * 底座是我们的 `shared.llm.LLMManager`（腾讯 TokenHub / 任何 OpenAI 兼容网关），
    不引入 `typesafe-sdk`、不依赖 `TYPESAFE_API_KEY`；
  * 官方 `structured_outputs=True`（走 provider 原生 JSON Schema）在本实现中
    固定为**提示词 JSON 模式 + 客户端结构校验**（等价于官方 `structured_outputs=False`
    的路径）—— TokenHub 只保证 `response_format=json_object`；
  * 只实现同步链路（上游还提供 Async 客户端与 providers 抽象层）。

用法：
    from shared.decision import DecisionClient, Noul, Choice

    client = DecisionClient(llm_manager)
    resp = client.system_one(
        state="用户说：你看着办吧，别问了",
        questions={"authorized": Noul(
            instructions="用户是否授权由助手自行决定、无需再澄清？",
            criteria=NoulCriteria(true="明确表示不必再问", false="只是随口一说或另有所指"),
        )},
    )
    resp.noul("authorized").answer   # -> True / False
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Mapping, Optional, Union

from pydantic import TypeAdapter

from .types import (
    Answer,
    Choice,
    ChoiceAnswer,
    DecisionError,
    DecisionResponse,
    Noul,
    NoulAnswer,
    Question,
    Score,
    ScoreAnswer,
    Usage,
)

logger = logging.getLogger("shared.decision")

_QUESTION_ADAPTER: TypeAdapter = TypeAdapter(Question)

_SYSTEM_PROMPT = """你是「类型化决策引擎」，只回答下面明确列出的问题。

硬性规则：
1. 只依据「状态」作答。信息不足时给出接近 0.5 的概率表示不确定，严禁臆造事实。
2. 只输出一个 JSON 对象，形如 {"answers": {"<问题名>": <答案对象>}}，问题名必须与给出的一致。
3. 不要输出任何解释、前后缀文字，也不要用 markdown 代码块包裹。
4. 概率与置信度都是 0~1 的小数；Choice 的 probabilities 各值之和应约等于 1。"""


class _Malformed(Exception):
    """模型输出不满足问题结构（触发纠正重试，重试用尽后升级为 DecisionError）。"""


# ---------------------------------------------------------------------------
# 提示词构造
# ---------------------------------------------------------------------------
def _label_description(label: str, desc: Optional[str]) -> str:
    return f"{label}：{desc}" if desc else label


def _question_block(name: str, q: Union[Noul, Choice, Score]) -> str:
    lines = [f"### {name}（{q.type}）"]
    if q.instructions:
        lines.append(f"问题：{q.instructions}")
    if isinstance(q, Noul) and q.criteria:
        if q.criteria.true:
            lines.append(f"判为「是」的情形：{q.criteria.true}")
        if q.criteria.false:
            lines.append(f"判为「否」的情形：{q.criteria.false}")
    elif isinstance(q, Choice):
        lines.append("可选项（choice 只能取其中之一）：")
        for label, desc in q.criteria.items():
            lines.append(f"  - {_label_description(label, desc)}")
        if not q.criteria:
            lines.append("  （未给出选项，无法作答）")
    elif isinstance(q, Score):
        lines.append("评分档位（从 0 档开始，probabilities 的键为档位整数）：")
        for level, desc in enumerate(q.criteria):
            lines.append(f"  - {level}：{desc}")
    else:
        lines.append(f"问题类型：{q.type}")
    return "\n".join(lines)


def _answer_template(name: str, q: Union[Noul, Choice, Score], mode: str) -> Dict[str, Any]:
    """给出该问题的答案骨架，让模型「照抄结构、替换数值」。"""
    if isinstance(q, Noul):
        return {"type": "noul", "noul": 1.0 if mode == "discrete" else 0.0}
    if isinstance(q, Choice):
        labels = list(q.criteria.keys()) or ["<选项>"]
        body: Dict[str, Any] = {"type": "choice", "choice": labels[0]}
        if mode != "discrete":
            body["confidence"] = 0.0
            body["probabilities"] = {label: round(1.0 / len(labels), 4) for label in labels}
        return body
    levels = [str(i) for i in range(max(len(q.criteria), 1))]
    return {
        "type": "score",
        "legend": {i: (q.criteria[i] if i < len(q.criteria) else "") for i in range(len(levels))},
        "probabilities": {i: round(1.0 / len(levels), 4) for i in range(len(levels))},
    }


def build_messages(
    state: str,
    questions: Mapping[str, Union[Noul, Choice, Score]],
    mode: str = "probabilities",
) -> List[Dict[str, str]]:
    """把「状态 + 类型化问题」渲染成对话消息（官方即 state + questions 两段式输入）。"""
    blocks = "\n\n".join(_question_block(name, q) for name, q in questions.items())
    template = {"answers": {name: _answer_template(name, q, mode) for name, q in questions.items()}}
    user = (
        f"## 状态\n{state}\n\n"
        f"## 问题\n{blocks}\n\n"
        f"## 输出 JSON 模板（照抄结构，替换数值 / 选项 / 概率）\n"
        f"{json.dumps(template, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# 输出解析与校验
# ---------------------------------------------------------------------------
def _first_number(raw: Any, keys: tuple) -> Optional[float]:
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, dict):
        for key in keys:
            if key in raw and isinstance(raw[key], (int, float)) and not isinstance(raw[key], bool):
                return float(raw[key])
        for value in raw.values():  # 单一取值的兜底
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            return None
    return None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_probs(probs: Dict[Any, float]) -> Dict[Any, float]:
    """把分布修成合法概率：负值归零；总量不为 1 时按比例缩放（而非先截断）。

    注意顺序：**先归一、后截断**。若先 `_clamp01` 再归一，模型给出
    `{business: 2.0, personal: 1.0}` 这类「权重式」输出会被截成 1:1，
    把 2:1 的偏好关系抹掉。
    """
    cleaned = {k: max(0.0, float(v)) for k, v in probs.items()}
    total = sum(cleaned.values())
    if total <= 0:
        return cleaned
    if abs(total - 1.0) > 0.02:
        cleaned = {k: v / total for k, v in cleaned.items()}
    return {k: _clamp01(v) for k, v in cleaned.items()}


def _coerce_noul(name: str, q: Noul, raw: Any, mode: str) -> NoulAnswer:
    value = _first_number(raw, ("noul", "answer", "value", "probability", "confidence"))
    if value is None or not math.isfinite(value):
        raise _Malformed(f"问题 {name!r}：未能取到 0~1 的 noul 概率（得到 {raw!r}）")
    value = _clamp01(value)
    if mode == "discrete":
        # 离散模式：模型只给一个值，按 0.5 阈值归类为确定的 0 / 1
        value = 1.0 if value >= 0.5 else 0.0
    return NoulAnswer(noul=value)


def _coerce_choice(
    name: str, q: Choice, raw: Any, mode: str, normalize: bool
) -> ChoiceAnswer:
    if not isinstance(raw, dict):
        raise _Malformed(f"问题 {name!r}：choice 答案必须是对象（得到 {raw!r}）")
    labels = list(q.criteria.keys())
    choice = raw.get("choice", raw.get("label", raw.get("value")))
    if not isinstance(choice, str) or not choice:
        raise _Malformed(f"问题 {name!r}：缺少 choice 字段（得到 {raw!r}）")
    if labels and choice not in labels:
        # 允许模型回一个描述串：命中唯一包含它的选项时接受，否则判畸形
        matched = [lb for lb in labels if lb == choice or (isinstance(choice, str) and choice in lb)]
        if len(matched) != 1:
            raise _Malformed(f"问题 {name!r}：choice={choice!r} 不在可选项 {labels} 内")
        choice = matched[0]

    raw_probs = raw.get("probabilities") or raw.get("scores") or {}
    probs: Dict[str, float] = {}
    if isinstance(raw_probs, dict):
        for label in (labels or list(raw_probs.keys())):
            value = raw_probs.get(label)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                probs[label] = max(0.0, float(value))
        for label in labels:  # 补齐缺失选项为 0
            probs.setdefault(label, 0.0)
    if normalize and sum(probs.values()) > 0:
        probs = _normalize_probs(probs)
    else:
        probs = {label: _clamp01(v) for label, v in probs.items()}
    if not probs or sum(probs.values()) <= 0:
        probs = {choice: 1.0}  # 模型没给分布（等价离散模式）→ 退化为 one-hot

    confidence = _first_number(raw.get("confidence"), ("confidence",)) if isinstance(raw, dict) else None
    if confidence is None:
        confidence = probs.get(choice, 0.0)
    return ChoiceAnswer(choice=choice, confidence=_clamp01(confidence), probabilities=probs)


def _coerce_score(name: str, q: Score, raw: Any, normalize: bool) -> ScoreAnswer:
    if not isinstance(raw, dict):
        raise _Malformed(f"问题 {name!r}：score 答案必须是对象（得到 {raw!r}）")
    raw_probs = raw.get("probabilities") or raw.get("scores") or {}
    if not isinstance(raw_probs, dict) or not raw_probs:
        raise _Malformed(f"问题 {name!r}：score 缺少 probabilities（得到 {raw!r}）")

    probs: Dict[int, float] = {}
    for key, value in raw_probs.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        try:
            probs[int(key)] = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    if not probs:
        raise _Malformed(f"问题 {name!r}：probabilities 键值无法解析为档位: {raw_probs!r}")
    probs = _normalize_probs(probs) if normalize else {k: _clamp01(v) for k, v in probs.items()}

    legend: Dict[int, str] = {}
    raw_legend = raw.get("legend")
    if isinstance(raw_legend, dict):
        for key, value in raw_legend.items():
            try:
                legend[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
    for level, desc in enumerate(q.criteria):  # 问题里给的图例优先补齐
        legend.setdefault(level, desc)
    return ScoreAnswer(legend=legend, probabilities=probs)


def coerce_answers(
    questions: Mapping[str, Union[Noul, Choice, Score]],
    payload: Any,
    mode: str = "probabilities",
    normalize: bool = True,
) -> Dict[str, Answer]:
    """把模型的 JSON 输出校验成类型化答案；任何结构问题抛 `_Malformed`。"""
    if not isinstance(payload, dict):
        raise _Malformed(f"顶层输出不是 JSON 对象（得到 {payload!r}）")
    answers_raw = payload.get("answers", payload)
    if not isinstance(answers_raw, dict):
        raise _Malformed(f"answers 不是对象（得到 {answers_raw!r}）")

    answers: Dict[str, Answer] = {}
    for name, q in questions.items():
        raw = answers_raw.get(name)
        if raw is None:
            raise _Malformed(f"缺少问题 {name!r} 的答案（实际返回 {list(answers_raw)}）")
        if isinstance(q, Noul):
            answers[name] = _coerce_noul(name, q, raw, mode)
        elif isinstance(q, Choice):
            answers[name] = _coerce_choice(name, q, raw, mode, normalize)
        elif isinstance(q, Score):
            answers[name] = _coerce_score(name, q, raw, normalize)
        else:  # 理论上不可达：Questions 类型已约束
            raise _Malformed(f"问题 {name!r} 类型不支持: {type(q).__name__}")
    return answers


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
class DecisionClient:
    """把类型化问题交给一个 OpenAI 兼容 LLM 作答（System One 范式的最小落地）。"""

    def __init__(
        self,
        llm_manager: Any,
        *,
        model: Optional[str] = None,
        llm_answer_mode: str = "probabilities",
        normalize_probabilities: bool = True,
        n_retry_malformed_structure: int = 1,
        max_tokens: int = 1024,
        timeout: int = 30,
        temperature: float = 0.0,
    ):
        """
        Args:
            llm_manager: `shared.llm.LLMManager` 实例（任何提供 `is_available()` /
                `chat_json()` 的对象均可，便于测试注入桩）。
            model: 默认模型 id；`system_one(..., model=...)` 可按次覆盖。
            llm_answer_mode: `"probabilities"`（要概率分布，默认）或
                `"discrete"`（只要一个取值，客户端据此给出确定值）。
            normalize_probabilities: 概率和不等于 1 时是否等比缩放修正。
            n_retry_malformed_structure: 结构不合规时的纠正重试次数（不含首次）。
            max_tokens / timeout / temperature: 透传给底层 LLM 的调用参数。
                temperature 默认 0 —— 判定类任务不需要发散。
        """
        if llm_answer_mode not in ("probabilities", "discrete"):
            raise ValueError(f"llm_answer_mode 只能是 probabilities / discrete，得到 {llm_answer_mode!r}")
        self.llm = llm_manager
        self.model = model
        self.llm_answer_mode = llm_answer_mode
        self.normalize_probabilities = normalize_probabilities
        self.n_retry_malformed_structure = max(0, int(n_retry_malformed_structure))
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.temperature = temperature

    # -- 可用性 --
    def is_available(self) -> bool:
        """底层 LLM 是否有可用 key（没有则不该发起任何调用）。"""
        checker = getattr(self.llm, "is_available", None)
        if not callable(checker):
            return self.llm is not None
        try:
            return bool(checker())
        except Exception:  # noqa: BLE001 — 可用性探测绝不允许把调用方拖崩
            return False

    # -- 主入口 --
    def system_one(
        self,
        state: str,
        questions: Mapping[str, Union[Noul, Choice, Score, Dict[str, Any]]],
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> DecisionResponse:
        """对 `state` 求解一组类型化问题。

        Raises:
            DecisionError: LLM 不可用、调用失败，或重试后输出仍不满足结构。
        """
        if not questions:
            raise DecisionError("questions 不能为空")
        if not self.is_available():
            raise DecisionError("底层 LLM 不可用（未注册 provider 或 api_key 为空）")

        parsed: Dict[str, Union[Noul, Choice, Score]] = {}
        for name, q in questions.items():
            try:
                parsed[name] = q if isinstance(q, (Noul, Choice, Score)) else _QUESTION_ADAPTER.validate_python(q)
            except Exception as e:  # noqa: BLE001 — 统一收敛为 DecisionError
                raise DecisionError(f"问题 {name!r} 定义非法: {e}") from e

        messages = build_messages(state, parsed, self.llm_answer_mode)
        use_model = model or self.model
        attempts = 1 + self.n_retry_malformed_structure
        last_reason = ""
        payload: Any = None
        used_attempts = 0

        for attempt in range(attempts):
            used_attempts = attempt + 1
            try:
                payload = self.llm.chat_json(
                    messages,
                    model=use_model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=timeout or self.timeout,
                )
            except Exception as e:  # noqa: BLE001 — 网络/解析异常一律升级为 DecisionError
                logger.warning("decision chat_json 失败（第 %s 次）: %s", used_attempts, e)
                raise DecisionError(f"LLM 调用失败: {e}") from e

            try:
                answers = coerce_answers(
                    parsed, payload, self.llm_answer_mode, self.normalize_probabilities
                )
            except _Malformed as e:
                last_reason = str(e)
                logger.warning("decision 输出不合规（第 %s 次）: %s", used_attempts, last_reason)
                if attempt + 1 >= attempts:
                    break
                # 纠正重试：把失败原因回灌，让模型自己修结构
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                    {"role": "user", "content": f"上一次输出不合规：{last_reason}。请重新只输出符合模板的 JSON。"},
                ]
                continue

            return DecisionResponse(
                model=use_model or "",
                answers=answers,
                usage=self._collect_usage(used_attempts - 1),
                debug={"attempts": used_attempts, "llm_answer_mode": self.llm_answer_mode},
            )

        raise DecisionError(f"输出结构不合法（已重试 {used_attempts - 1} 次）: {last_reason}")

    # -- 内部 --
    def _collect_usage(self, n_retries: int) -> Usage:
        stats: Dict[str, Any] = {}
        getter = getattr(self.llm, "get_last_stats", None)
        if callable(getter):
            try:
                stats = getter() or {}
            except Exception:  # noqa: BLE001 — 统计缺失不影响决策结果
                stats = {}
        return Usage(
            input_tokens=stats.get("prompt_tokens"),
            output_tokens=stats.get("completion_tokens"),
            latency_ms=stats.get("duration_ms"),
            n_retries=max(0, n_retries),
        )


# 与官方 `system_one_adapter.SystemOneAdapterClient` 同名别名，方便对照阅读。
SystemOneAdapterClient = DecisionClient
