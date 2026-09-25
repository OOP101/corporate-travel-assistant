"""行程生成管线 —— 「自然语言 → 草案」的进程内流水线（v3）

从 v2 planner-core 的 /trips/generate SSE 端点抽出：HTTP 端点与 Agent 工具
（plan_trip_stream）共用同一条管线，消除「编排层经 HTTP 回调自身」的绕路。

产出帧统一用 {"kind": ...}：
  progress  生成过程提示（不进正文）
  chunk     原始生成文本片段（HTTP SSE 透传；Agent 侧折算进度）
  clarify   S2 澄清反问（缺参清单 + 已抽参数）
  policy    政策预检结果（经工具总线调政策外接服务，只预警不审批）
  draft     S3 草案（未落库未审批，交确认）
  error     错误（生成中途失败已降级演示行程时）
  timing    各阶段耗时埋点
"""
import logging
import time

from shared.metrics import trip_generation_duration

from core import deps
from core.generation import ItineraryGenerator

logger = logging.getLogger("core.pipeline")


def generate_draft_stream(
    query: str,
    session_id: str = "default",
    user_id: str = "default",
    model: str = None,
    preferences: dict = None,
    params: dict = None,
    carry: dict = None,
):
    """生成行程草案（流式帧生成器）。草案未落库未审批；确认走 approval engine。"""
    if deps.llm_manager is None or deps.trip_store is None:
        yield {"kind": "error", "content": "服务未就绪"}
        return

    # 攻略语料来自攻略外接服务（个人出游场景召回；服务未接入则无料可引）
    guide_store = deps.guide_service.guide_store if deps.guide_service else None

    # 每次请求独立生成器实例：并发请求的 model 选择与解析结果互不干扰
    gen = ItineraryGenerator(deps.llm_manager, guide_store=guide_store)
    gen.model = model

    yield {"kind": "progress", "content": "正在分析您的出行需求..."}
    api_started_at = time.monotonic()

    with trip_generation_duration.labels(status="generate").time():
        for chunk in gen.generate_stream(query, preferences or {}, params or {}, carry or {}):
            yield {"kind": "chunk", "content": chunk}

    # 生成中途出错（已降级演示行程）：独立 error 帧，不混入行程 JSON
    if getattr(gen, "last_error", None):
        yield {"kind": "error", "content": gen.last_error}

    # S2 澄清：必填参数缺失（scene/目的地/日期天数）→ 发 clarify 帧，不生成不落库
    missing = getattr(gen, "last_missing", None) or []
    if missing:
        p = getattr(gen, "last_params", {}) or {}
        yield {
            "kind": "clarify",
            "missing": missing,
            "params": p,
            "content": ItineraryGenerator.build_clarify_question(missing, p),
        }
        yield _timing_frame(gen, model, api_started_at, policy_ms=0, policy_event={})
        return

    # S3 草案：只生成，不落库、不审批（审批在确认后由 approval engine 触发）
    trip_dict = getattr(gen, "_last_trip", None)
    policy_event = {}
    policy_ms = 0
    if trip_dict:
        # 政策预检：经政策外接服务（工具总线语义），只预警不审批
        policy_svc = deps.policy_service
        if policy_svc is not None:
            t_policy = time.monotonic()
            policy_event = policy_svc.preview_trip(trip_dict, deps.employee_of(user_id))
            policy_ms = int((time.monotonic() - t_policy) * 1000)
        if policy_event:
            yield {"kind": "policy", **{k: v for k, v in policy_event.items() if k != "event"}}
        yield {
            "kind": "draft",
            "trip": trip_dict,
            "defaulted": getattr(gen, "last_defaulted", []) or [],
            "params": getattr(gen, "last_params", {}) or {},
        }
    else:
        yield {"kind": "error", "content": "行程草案生成失败，请稍后重试"}

    yield _timing_frame(gen, model, api_started_at, policy_ms, policy_event)


def _timing_frame(gen, model, api_started_at: float, policy_ms: int, policy_event: dict) -> dict:
    """聚合各阶段耗时 + LLM 统计 → timing 帧，供外部基准脚本消费。"""
    phase_timings = getattr(gen, "_phase_timings", {}) or {}
    phase_timings["save"] = {"duration_ms": 0}
    phase_timings["policy"] = {
        "duration_ms": policy_ms,
        "has_violations": bool(policy_event.get("has_violations")),
    }
    phase_timings["api_total"] = {"duration_ms": int((time.monotonic() - api_started_at) * 1000)}
    return {"kind": "timing", "model": model or "default", "phases": phase_timings}
