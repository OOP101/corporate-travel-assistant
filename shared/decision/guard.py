"""决策守卫 —— 把类型化判定安全地嵌进业务代码。

`DecisionClient` 是「会抛异常的库」；业务里真正需要的形态是
**「问一句，能答就答，不能答就走我原来的逻辑」**。本模块提供这个形态：

  * 客户端不可用 / 调用异常 / 输出不合结构 → 一律返回 `default`，**绝不抛出**；
  * 置信度落在「不确定带」内（如 noul 的 0.25~0.75）→ 也返回 `default`，
    而不是硬猜一个值；
  * 同一（模型, 问题, 状态）的判定结果带 LRU 缓存 —— 重复文本（例如用户
    连点同一个按钮）第二次起零成本，不会因为引入语义判定而放大延迟。

因此在绝大多数调用点，接入一个决策判定是「纯增益」：最坏情况就是退回到
调用方原本的规则逻辑。
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from typing import Any, Dict, List, Mapping, Optional

from .client import DecisionClient
from .types import Choice, DecisionError, DecisionResponse, Noul, NoulCriteria, Score

logger = logging.getLogger("shared.decision")

_CACHE_MAX = 256
# 缓存的是「原语级判定值」而非最终布尔：noul 存概率、choice 存标签、score 存档位。
# 这样同一缓存项在不同 threshold / default 下都能复用。
_CACHE: "OrderedDict[str, Any]" = OrderedDict()


def clear_cache() -> None:
    """清空判定缓存（测试与配置变更后调用）。"""
    _CACHE.clear()


def _cache_key(kind: str, model: str, instructions: str, detail: Any, state: str) -> str:
    return json.dumps(
        [kind, model, instructions, detail, state], ensure_ascii=False, sort_keys=True, default=str
    )


def _cache_get(key: str) -> Optional[Any]:
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def _cache_put(key: str, value: Any) -> None:
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


def _run(
    client: Optional[DecisionClient],
    question_name: str,
    question: Any,
    state: str,
    timeout: Optional[int],
    model: Optional[str],
) -> Optional[DecisionResponse]:
    """执行一次判定；任何失败都吞掉并返回 None（调用方据此走 default）。"""
    if client is None:
        return None
    try:
        if not client.is_available():
            return None
        return client.system_one(
            state=state, questions={question_name: question}, model=model, timeout=timeout
        )
    except DecisionError as e:
        logger.info("决策不可用，回退调用方默认逻辑: %s", e)
        return None
    except Exception as e:  # noqa: BLE001 — 决策层故障绝不允许打断主流程
        logger.warning("决策调用异常，回退调用方默认逻辑: %s", e)
        return None


# ---------------------------------------------------------------------------
# 三种原语的守卫式读法
# ---------------------------------------------------------------------------
def ask_noul(
    client: Optional[DecisionClient],
    state: str,
    instructions: str,
    *,
    criteria: Optional[NoulCriteria] = None,
    default: Optional[bool] = None,
    threshold: float = 0.75,
    question_name: str = "q",
    timeout: Optional[int] = None,
    model: Optional[str] = None,
) -> Optional[bool]:
    """类型化是/否判定。

    Returns:
        True   —— 模型以不低于 `threshold` 的把握判「是」
        False  —— 以不低于 `threshold` 的把握判「否」
        default（默认 None）—— 客户端不可用 / 调用失败 / 落在不确定带内
                                 （`[1-threshold, threshold]`，默认 0.25~0.75）
    """
    detail = criteria.model_dump() if isinstance(criteria, NoulCriteria) else criteria
    key = _cache_key("noul", str(model or ""), instructions, detail, str(state))

    probability = _cache_get(key)
    if probability is None:
        resp = _run(client, question_name, Noul(instructions=instructions, criteria=criteria),
                    str(state), timeout, model)
        if resp is None:
            return default
        answer = resp.noul(question_name)
        if answer is None:
            return default
        probability = answer.noul
        _cache_put(key, probability)

    if probability >= threshold:
        return True
    if probability <= 1.0 - threshold:
        return False
    return default


def ask_choice(
    client: Optional[DecisionClient],
    state: str,
    instructions: str,
    options: Mapping[str, Optional[str]],
    *,
    default: Optional[str] = None,
    min_confidence: float = 0.6,
    question_name: str = "q",
    timeout: Optional[int] = None,
    model: Optional[str] = None,
) -> Optional[str]:
    """类型化多选判定；返回选中的标签，置信度不足或失败时返回 `default`。"""
    if not options:
        return default
    key = _cache_key("choice", str(model or ""), instructions, list(options.keys()), str(state))

    cached = _cache_get(key)
    if cached is None:
        resp = _run(client, question_name, Choice(instructions=instructions, criteria=dict(options)),
                    str(state), timeout, model)
        if resp is None:
            return default
        answer = resp.choice(question_name)
        if answer is None:
            return default
        if answer.confidence < min_confidence:
            return default
        _cache_put(key, answer.choice)
        return answer.choice
    return str(cached)


def ask_score(
    client: Optional[DecisionClient],
    state: str,
    instructions: str,
    rubric: List[str],
    *,
    default: Optional[int] = None,
    min_confidence: float = 0.0,
    question_name: str = "q",
    timeout: Optional[int] = None,
    model: Optional[str] = None,
) -> Optional[int]:
    """类型化评分判定；返回档位整数（0 起），失败或置信度不足时返回 `default`。"""
    if not rubric:
        return default
    key = _cache_key("score", str(model or ""), instructions, rubric, str(state))

    cached = _cache_get(key)
    if cached is None:
        resp = _run(client, question_name, Score(instructions=instructions, criteria=list(rubric)),
                    str(state), timeout, model)
        if resp is None:
            return default
        answer = resp.score(question_name)
        if answer is None:
            return default
        if answer.confidence < min_confidence:
            return default
        cached = float(answer.score or 0)
        _cache_put(key, cached)
    if cached < 0 or cached >= len(rubric):
        return default
    return int(cached)


def cache_info() -> Dict[str, Any]:
    """缓存概况（调试 / 观测用）。"""
    return {"size": len(_CACHE), "max": _CACHE_MAX}
