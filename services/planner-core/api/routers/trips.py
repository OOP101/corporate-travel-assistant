"""行程管理 Router —— 生成 (SSE) / CRUD / 应变重排 / 清单 / 总结 / 费用"""
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from shared.metrics import trip_generation_duration
from shared.sse import SSE_DONE, sse_frame, sse_stream_response

from generators import ItineraryGenerator
from archive import SummaryGenerator
from .. import deps

logger = logging.getLogger("planner-core.trips")

router = APIRouter()


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class GenerateTripRequest(BaseModel):
    query: str = Field(..., description="自然语言需求")
    session_id: str = Field(default="default")
    preferences: dict = Field(default_factory=dict)
    model: Optional[str] = Field(default=None, description="LLM 模型名（可选，缺省用 .env 配置）")
    params: dict = Field(default_factory=dict, description="用户已确认的结构化参数（scene/日期等，优先级高于抽取）")
    carry: dict = Field(default_factory=dict, description="澄清轮次已抽取的参数（低优先级续用）")


class ConfirmTripRequest(BaseModel):
    trip: dict = Field(..., description="确认的行程草案（/trips/generate 的 draft 帧 trip 字段）")
    session_id: str = Field(default="default")


class UpdateTripRequest(BaseModel):
    data: dict = Field(..., description="要更新的字段", min_length=1)


class RerouteRequest(BaseModel):
    changed_activity: dict = Field(..., description="变更的活动")
    reason: str = Field(default="")


# 允许更新的行程字段白名单
_TRIP_UPDATE_FIELDS = {
    "title", "destination", "origin", "start_date", "end_date",
    "budget_total", "status", "preferences", "checklist", "days",
}


def _deny_if_not_owner(trip: dict, session_id: str = ""):
    """行程属主校验（防 IDOR）。

    调用方显式声明了身份（session_id）且与行程归属 user_id 不符时，
    按 404 拒绝（不暴露行程存在性）。未声明身份的调用保持兼容放行，
    P2 接入企业身份（SSO）后应改为强制校验。
    """
    owner = trip.get("user_id") or ""
    if session_id and owner and session_id != owner:
        raise HTTPException(404, f"行程不存在: {trip.get('trip_id')}")


# 免做企业差旅政策检查的场景（个人出游为 C 端场景，与差旅政策无关）
_POLICY_EXEMPT_SCENES = {"personal"}


def _policy_exempt_reason(trip_dict: dict, user_id: str) -> str:
    """判断本次行程是否免做政策检查与审批；返回免检原因，空串表示需要检查。

    两类豁免（见 docs_企业级旅行服务助手/07-改C端-完全验证与简历影响.md §2.5/§2.6）：

    1. **个人出游场景** —— 与「企业差旅政策」无关，不该出现职级限额与审批门禁。
    2. **无员工档案的用户** —— 没有职级可匹配，套用通用政策没有意义。

    为什么必须显式短路：`_match_policy()` 对非员工取 `level=""`，而
    `PolicyStore.get_by_level()` 会把 `level==""` 的**通用政策**纳入任意职级候选
    （种子里的 pol_139be3c19e59 正是 level=""）。于是政策预检照样会跑：
      - 通用政策限额为 0 时，用户会看到一句「政策预检通过」——企业术语漏进个人行程；
      - 通用政策若填了真实额度，个人出游会被误判「住宿 ¥X 超过标准 ¥Y」。
    审批侧则因 `employee` 为空而不发起，可政策又写着 `requires_approval=True`，
    形成「说必须审批、实际无人审批、行程照样生效」的哑雷。
    """
    scene = str((trip_dict or {}).get("scene") or "").strip().lower()
    if scene in _POLICY_EXEMPT_SCENES:
        return f"场景「{scene}」为个人出游，不适用企业差旅政策"
    if deps.employee_store is not None and not deps.employee_store.get(user_id):
        return f"用户 {user_id} 无员工档案，无可匹配的职级政策"
    return ""


def _match_policy(trip_dict: dict, user_id: str):
    """按 user_id（员工 ID）职级匹配差旅政策；解析不到员工按通用政策。"""
    if deps.policy_store is None:
        return None
    employee = deps.employee_store.get(user_id) if deps.employee_store else None
    level = (employee or {}).get("level", "")
    return deps.policy_store.get_best_match(level)


def _policy_preview(trip_dict: dict, user_id: str) -> dict:
    """政策预检（S4 确认页预警用）——只检查不审批（PRD v2：审批绝不先于用户确认）。"""
    exempt = _policy_exempt_reason(trip_dict, user_id)
    if exempt:
        logger.info(f"跳过政策预检：{exempt}")
        return {}
    policy = _match_policy(trip_dict, user_id)
    if not policy:
        return {}
    try:
        violations = deps.policy_store.check_violations(trip_dict, policy)
        return {
            "event": "policy",
            "policy_id": policy.get("policy_id", ""),
            "policy_name": policy.get("name", ""),
            "violations": violations,
            "has_violations": len(violations) > 0,
            "content": (
                f"政策预检：{len(violations)} 项超标" if violations else "政策预检通过"
            ),
        }
    except Exception as e:
        logger.warning(f"政策预检失败: {e}")
        return {}


def _confirm_policy_flow(trip_dict: dict, trip_id: str, user_id: str) -> list:
    """用户确认后的 P1 链路（S5）：政策检查 → 超标提示 → 审批发起。

    员工解析：user_id 恰为员工 ID 时按其职级匹配政策；解析不到员工时仍做
    政策匹配与提示（按通用政策），但审批因缺少审批人不自动发起。

    Returns:
        事件列表：{"event": "policy", ...} / {"event": "approval", ...}
    """
    events = []
    exempt = _policy_exempt_reason(trip_dict, user_id)
    if exempt:
        logger.info(f"跳过确认后政策/审批链路：{exempt}")
        return events
    if deps.policy_store is None:
        return events
    try:
        employee = deps.employee_store.get(user_id) if deps.employee_store else None
        policy = _match_policy(trip_dict, user_id)
        if not policy:
            return events

        violations = deps.policy_store.check_violations(trip_dict, policy)
        events.append({
            "event": "policy",
            "policy_id": policy.get("policy_id", ""),
            "policy_name": policy.get("name", ""),
            "violations": violations,
            "has_violations": len(violations) > 0,
            "content": (
                f"政策检查完成：{len(violations)} 项超标"
                if violations else "政策检查通过"
            ),
        })

        # 审批发起：政策要求审批或预算达到阈值（仅在用户确认后由 confirm 调用）
        budget = float(trip_dict.get("budget_total", 0) or 0)
        threshold = float(policy.get("approval_threshold", 0) or 0)
        needs_approval = policy.get("requires_approval", False) or (threshold > 0 and budget >= threshold)
        approver_id = (employee or {}).get("manager_id", "")
        remark_scene = trip_dict.get("scene") or ""
        remark_purpose = trip_dict.get("purpose") or ""
        remark = "用户确认后发起"
        if remark_scene:
            remark += f" · 场景：{remark_scene}"
        if remark_purpose:
            remark += f" · 事由：{remark_purpose}"
        if needs_approval and employee and approver_id and deps.approval_store:
            if not deps.employee_store.get(approver_id):
                logger.warning(f"审批人不存在，跳过自动审批: {approver_id}")
            else:
                approval = {
                    "trip_id": trip_id,
                    "employee_id": user_id,
                    "approver_id": approver_id,
                    "total_amount": budget,
                    "policy_id": policy.get("policy_id", ""),
                    "violations": violations,
                    "remark": remark,
                    "status": "pending",
                }
                approval_id = deps.approval_store.save(approval)
                events.append({
                    "event": "approval",
                    "approval_id": approval_id,
                    "approver_id": approver_id,
                    "has_violations": len(violations) > 0,
                    "content": f"已发起审批（审批人：{(deps.employee_store.get(approver_id) or {}).get('name', approver_id)}）",
                })
    except Exception as e:
        # 政策/审批是增强链路，失败不阻断行程确认
        logger.warning(f"确认后政策/审批链路失败: {e}")
    return events


# ---------------------------------------------------------------------------
# 行程生成 (SSE 流式) —— v2：澄清 / 草案两态，确认后才落库审批（POST /trips/confirm）
# ---------------------------------------------------------------------------
@router.post("/trips/generate", tags=["行程生成"])
async def generate_trip(req: GenerateTripRequest, request: Request):
    """
    流式生成行程方案草案 (SSE) —— v2 语义

    事件帧:
      event: status   → 正在分析...
      event: clarify  → 必填参数缺失（scene/目的地/日期天数），附缺参清单，本次不生成
      event: chunk    → 行程 JSON 文本片段
      event: policy   → 政策预检结果（仅预警，不触发审批）
      event: draft    → 草案生成完成（未落库），附 trip / defaulted（代填项）/ params
      event: error    → 错误

    草案经用户确认后调 POST /trips/confirm 落库并触发审批。
    """
    if deps.llm_manager is None or deps.trip_store is None:
        raise HTTPException(503, "服务未就绪")

    user_id = req.session_id or getattr(request.state, "workspace_id", "default")

    # 每次请求独立生成器实例：并发请求的 model 选择与解析结果互不干扰
    gen = ItineraryGenerator(deps.llm_manager, guide_store=deps.guide_store)
    gen.model = req.model  # 前端选择的模型（可选）

    def generate():
        try:
            yield sse_frame({"event": "status", "content": "正在分析您的出行需求..."})
            api_started_at = time.monotonic()

            with trip_generation_duration.labels(status="generate").time():
                for chunk in gen.generate_stream(req.query, req.preferences, req.params, req.carry):
                    yield sse_frame({"event": "chunk", "content": chunk})

            # 生成中途出错（已降级演示行程）：发独立 error 帧，不混入行程 JSON
            if getattr(gen, "last_error", None):
                yield sse_frame({"event": "error", "content": gen.last_error})

            # S2 澄清：必填参数缺失（scene/目的地/日期天数）→ 发 clarify 帧，不生成不落库
            missing = getattr(gen, "last_missing", None) or []
            if missing:
                params = getattr(gen, "last_params", {}) or {}
                yield sse_frame({
                    "event": "clarify",
                    "missing": missing,
                    "params": params,
                    "content": ItineraryGenerator.build_clarify_question(missing, params),
                })
                yield sse_frame({"event": "timing", "model": req.model or "default",
                                 "phases": getattr(gen, "_phase_timings", {}) or {}})
                yield SSE_DONE
                return

            # S3 草案：只生成，不落库、不审批（审批在 /trips/confirm 用户确认后触发）
            trip_dict = getattr(gen, "_last_trip", None)
            save_ms = 0
            policy_ms = 0
            policy_event = {}
            if trip_dict:
                # 埋点：政策预检耗时
                t_policy = time.monotonic()
                policy_event = _policy_preview(trip_dict, user_id)
                policy_ms = int((time.monotonic() - t_policy) * 1000)
                if policy_event:
                    yield sse_frame(policy_event)
                yield sse_frame({
                    "event": "draft",
                    "trip": trip_dict,
                    "defaulted": getattr(gen, "last_defaulted", []) or [],
                    "params": getattr(gen, "last_params", {}) or {},
                })
            else:
                yield sse_frame({"event": "error", "content": "行程草案生成失败，请稍后重试"})

            # 埋点：聚合各阶段耗时 + LLM 统计 → timing 帧，供外部基准脚本消费
            phase_timings = getattr(gen, "_phase_timings", {}) or {}
            phase_timings["save"] = {"duration_ms": save_ms}
            phase_timings["policy"] = {
                "duration_ms": policy_ms,
                "has_violations": bool(policy_event.get("has_violations")),
            }
            phase_timings["api_total"] = {"duration_ms": int((time.monotonic() - api_started_at) * 1000)}
            yield sse_frame({"event": "timing", "model": req.model or "default",
                             "phases": phase_timings})

            yield SSE_DONE

        except Exception as e:
            logger.error(f"行程草案生成失败: {e}", exc_info=True)
            yield sse_frame({"event": "error", "content": str(e)})

    return sse_stream_response(generate())


# ---------------------------------------------------------------------------
# 方案确认 (S4 → S5) —— 用户确认草案后才落库 + 政策检查 + 审批
# ---------------------------------------------------------------------------
@router.post("/trips/confirm", tags=["行程生成"])
async def confirm_trip(req: ConfirmTripRequest, request: Request):
    """
    确认行程草案：落库 + 政策检查 + 审批发起（PRD v2 S5）。

    审批只允许在用户确认后发生；确认前政策违例仅作预警（见 /trips/generate 的 policy 帧）。
    """
    if deps.trip_store is None:
        raise HTTPException(503, "服务未就绪")

    trip_dict = req.trip or {}
    if not isinstance(trip_dict, dict) or not (trip_dict.get("destination") or trip_dict.get("title")):
        raise HTTPException(400, "无效的行程草案（缺少目的地/标题）")

    user_id = req.session_id or getattr(request.state, "workspace_id", "default")
    trip_dict["user_id"] = user_id
    if trip_dict.get("status") == "pending_approval":
        # 草案不应携带旧状态
        trip_dict["status"] = "draft"

    trip_id = deps.trip_store.save(trip_dict)

    # S5 链路：政策检查 + 审批发起（仅此路径允许触发审批）
    events = _confirm_policy_flow(trip_dict, trip_id, user_id)
    if any(e.get("event") == "approval" for e in events):
        # PRD 3.5 审批门禁：需审批的行程置为待审批，主管通过后才生效
        deps.trip_store.update(trip_id, {"status": "pending_approval"})

    saved = deps.trip_store.get(trip_id) or trip_dict
    return {
        "status": "ok",
        "trip_id": trip_id,
        "trip": saved,
        "events": events,
        "message": (
            f"行程已确认保存（编号 {trip_id}）"
            + ("；已发起审批" if any(e.get("event") == "approval" for e in events) else "")
        ),
    }


# ---------------------------------------------------------------------------
# 行程 CRUD
# ---------------------------------------------------------------------------
@router.get("/trips", tags=["行程管理"])
async def list_trips(
    request: Request,
    session_id: str = Query(default="", description="会话/用户 ID (兼容)"),
):
    """行程列表"""
    user_id = session_id or getattr(request.state, "workspace_id", "default")
    trips = deps.trip_store.list_by_user(user_id)
    return {"trips": trips, "count": len(trips)}


@router.get("/trips/{trip_id}", tags=["行程管理"])
async def get_trip(trip_id: str, session_id: str = Query(default="", description="调用方身份（声明后做属主校验）")):
    """行程详情"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, session_id)
    return trip


@router.put("/trips/{trip_id}", tags=["行程管理"])
async def update_trip(
    trip_id: str,
    req: UpdateTripRequest,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """编辑行程（仅允许更新白名单字段）"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, session_id)
    # 字段白名单校验
    unknown_fields = set(req.data.keys()) - _TRIP_UPDATE_FIELDS
    if unknown_fields:
        raise HTTPException(400, f"不允许更新的字段: {', '.join(sorted(unknown_fields))}")
    updated = deps.trip_store.update(trip_id, req.data)
    if not updated:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    return updated


@router.delete("/trips/{trip_id}", tags=["行程管理"])
async def delete_trip(
    trip_id: str,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """删除行程"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, session_id)
    deps.trip_store.delete(trip_id)
    return {"status": "ok", "trip_id": trip_id}


# ---------------------------------------------------------------------------
# 应变重排
# ---------------------------------------------------------------------------
@router.post("/trips/{trip_id}/reroute", tags=["行程管理"])
async def reroute_trip(
    trip_id: str,
    req: RerouteRequest,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """
    应变重排：指定活动变更后，重新排列受影响的后续行程。

    重排策略：
      - 景点闭馆/移除 → LLM 推荐替代方案或后续活动前移
      - 航班延误 → 后续活动顺延，超窗活动标记需调整
      - 时长变更 → 重新对齐后续活动时间线
    """
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, session_id)
    # PRD 3.5 审批门禁：待审批行程不允许调整
    if trip.get("status") == "pending_approval":
        raise HTTPException(409, "行程待主管审批，审批通过后才能调整")

    if deps.reroute_engine is None:
        raise HTTPException(503, "重排引擎未就绪")

    changed = req.changed_activity
    reason = req.reason or "用户主动调整"

    updated_trip = deps.reroute_engine.reroute(trip, changed, reason)
    deps.trip_store.update(trip_id, updated_trip)

    return {
        "status": "ok",
        "trip_id": trip_id,
        "message": updated_trip.get("reroute_summary", "行程已重排"),
        "reroute_summary": updated_trip.get("reroute_summary", ""),
    }


# ---------------------------------------------------------------------------
# 出行清单
# ---------------------------------------------------------------------------
@router.get("/trips/{trip_id}/checklist", tags=["行程管理"])
async def get_checklist(trip_id: str, session_id: str = Query(default="")):
    """获取出行清单"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, session_id)

    # 如果行程已有 checklist，直接返回
    if trip.get("checklist"):
        return {"trip_id": trip_id, "checklist": trip["checklist"], "source": "trip"}

    # 否则生成
    items = deps.checklist_gen.generate(trip)
    trip["checklist"] = items
    deps.trip_store.update(trip_id, {"checklist": items})
    return {"trip_id": trip_id, "checklist": items, "source": "generated"}


# ---------------------------------------------------------------------------
# 行程总结
# ---------------------------------------------------------------------------
@router.post("/trips/{trip_id}/summary", tags=["行程管理"])
async def generate_summary(trip_id: str, session_id: str = Query(default="")):
    """生成行程总结"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, session_id)

    summary = deps.summary_gen.generate(trip)
    return {"trip_id": trip_id, "summary": summary}


# ---------------------------------------------------------------------------
# 消费统计 (PRD F4.1) —— 复用 SummaryGenerator._calc_expenses 逻辑
# ---------------------------------------------------------------------------
@router.get("/trips/{trip_id}/expenses", tags=["行程管理"])
async def get_expenses(trip_id: str, session_id: str = Query(default="")):
    """
    消费统计独立接口。

    基于行程各活动的 estimated_cost / ticket_price 按类别汇总，
    复用 SummaryGenerator._calc_expenses 的规则计算逻辑 (优先于 LLM 估算，保证数值准确)。
    """
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, session_id)

    # 复用已有的花费计算逻辑 (静态方法，无需 LLM)
    expense_summary = SummaryGenerator._calc_expenses(trip, {})
    return {"trip_id": trip_id, "expense_summary": expense_summary}


# ---------------------------------------------------------------------------
# 行程单导出 (P2) —— 打印 / 另存为 PDF 友好的 HTML，零外部依赖
# ---------------------------------------------------------------------------
_TYPE_LABELS = {
    "transport": "交通", "meeting": "会议", "attraction": "景点",
    "dining": "餐饮", "accommodation": "住宿", "shopping": "购物",
    "rest": "休息", "other": "其他",
}


def _esc(value):
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _fmt_money(value):
    try:
        return f"¥{float(value):,.0f}"
    except (TypeError, ValueError):
        return ""


def _humanize_party(party):
    """出行人字段可能是 str / list[dict] / dict，统一为人名串。"""
    if not party:
        return ""
    if isinstance(party, str):
        return party
    if isinstance(party, list):
        names = []
        for p in party:
            if isinstance(p, dict):
                names.append(p.get("name") or p.get("role") or "")
            elif isinstance(p, str):
                names.append(p)
        return "、".join(n for n in names if n)
    if isinstance(party, dict):
        return party.get("name") or ""
    return str(party)


def _render_itinerary_html(trip: dict) -> str:
    """把行程结构渲染成打印友好的 HTML 行程单（含清单与费用预估）。"""
    title = _esc(trip.get("title") or "未命名行程")
    destination = _esc(trip.get("destination") or "")
    origin = _esc(trip.get("origin") or "")
    start = _esc(trip.get("start_date") or "")
    end = _esc(trip.get("end_date") or "")
    status = _esc(trip.get("status") or "")
    travel_party = _esc(_humanize_party(trip.get("travel_party")))
    budget = _fmt_money(trip.get("budget_total"))

    meta_items = []
    if origin and destination:
        meta_items.append(f"出发地：{origin}")
    if destination:
        meta_items.append(f"目的地：{destination}")
    if start or end:
        meta_items.append(f"行程日期：{start} ~ {end}")
    if travel_party:
        meta_items.append(f"出行人：{travel_party}")
    if budget:
        meta_items.append(f"总预算：{budget}")
    if status:
        meta_items.append(f"状态：{status}")

    days_html = ""
    for i, day in enumerate(trip.get("days") or []):
        theme = _esc(day.get("theme") or "")
        date = _esc(day.get("date") or "")
        rows = ""
        for act in day.get("activities") or []:
            atype = act.get("type") or "other"
            label = _TYPE_LABELS.get(atype, _TYPE_LABELS["other"])
            time_range = " ~ ".join(
                t for t in [act.get("time_start"), act.get("time_end")] if t
            )
            atitle = _esc(act.get("title") or "")
            loc = act.get("location")
            loc_name = _esc(loc.get("name") if isinstance(loc, dict) else loc)
            cost = _fmt_money(act.get("estimated_cost") or act.get("ticket_price"))
            tips = _esc(act.get("tips") or "")
            booking = ""
            if act.get("booking_required"):
                url = _esc(act.get("booking_url") or "")
                booking = '<span class="book">需预订' + (f" · {url}" if url else "") + '</span>'
            loc_block = f'<div class="t-loc">📍 {loc_name}</div>' if loc_name else ""
            tips_block = f'<div class="t-tips">{tips}</div>' if tips else ""
            rows += f"""
              <tr>
                <td class="t-time">{_esc(time_range)}</td>
                <td class="t-type">{label}</td>
                <td class="t-title">{atitle}{loc_block}{tips_block}{booking}</td>
                <td class="t-cost">{cost}</td>
              </tr>"""
        days_html += f"""
          <div class="day">
            <h2>Day {i + 1}{(' · ' + theme) if theme else ''}{('　' + date) if date else ''}</h2>
            <table><tbody>{rows}</tbody></table>
          </div>"""

    checklist_html = ""
    checklist = trip.get("checklist") or []
    if checklist:
        items = "".join(f"<li>{_esc(it)}</li>" for it in checklist)
        checklist_html = f"""
          <div class="section">
            <h2>出行清单</h2>
            <ul class="checklist">{items}</ul>
          </div>"""

    expense_html = ""
    try:
        exp = SummaryGenerator._calc_expenses(trip, {})
        total = exp.get("total")
        if isinstance(total, (int, float)):
            cats = exp.get("by_category") or {}
            cat_rows = "".join(
                f'<div class="exp-row"><span>{_TYPE_LABELS.get(c, c)}</span>'
                f'<span>{_fmt_money(v)}</span></div>'
                for c, v in cats.items()
            )
            expense_html = f"""
              <div class="section">
                <h2>费用预估</h2>
                <div class="exp-total">合计：{_fmt_money(total)}</div>
                {cat_rows}
              </div>"""
    except Exception:
        pass

    generated_at = _esc(time.strftime("%Y-%m-%d %H:%M"))

    css = """
    <style>
      * { box-sizing: border-box; }
      body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
             color: #1f2937; margin: 0; background: #f3f4f6; }
      .sheet { max-width: 820px; margin: 24px auto; background: #fff; padding: 40px 48px;
               box-shadow: 0 1px 4px rgba(0,0,0,.1); }
      h1.doc-title { font-size: 24px; margin: 0 0 4px; }
      .subtitle { color: #6b7280; font-size: 13px; margin-bottom: 20px; }
      .meta { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px;
              color: #374151; border-bottom: 1px solid #e5e7eb; padding-bottom: 14px; margin-bottom: 22px; }
      .day { margin-bottom: 22px; }
      .day h2 { font-size: 16px; margin: 0 0 8px; padding-left: 10px; border-left: 4px solid #4f46e5; }
      table { width: 100%; border-collapse: collapse; font-size: 13px; }
      td { padding: 7px 8px; border-bottom: 1px solid #f1f1f4; vertical-align: top; }
      .t-time { color: #6b7280; white-space: nowrap; width: 90px; }
      .t-type { color: #4f46e5; white-space: nowrap; width: 56px; font-weight: 600; }
      .t-title { width: auto; }
      .t-cost { text-align: right; color: #b45309; font-weight: 600; white-space: nowrap; width: 90px; }
      .t-loc { color: #6b7280; font-size: 12px; margin-top: 2px; }
      .t-tips { color: #9ca3af; font-size: 12px; margin-top: 2px; }
      .book { color: #dc2626; font-size: 12px; }
      .section { margin-top: 24px; }
      .section h2 { font-size: 16px; border-left: 4px solid #4f46e5; padding-left: 10px; }
      .checklist { margin: 0; padding-left: 20px; font-size: 13px; color: #374151; }
      .checklist li { margin: 4px 0; }
      .exp-total { font-size: 14px; font-weight: 700; color: #b45309; margin-bottom: 8px; }
      .exp-row { display: flex; justify-content: space-between; font-size: 13px;
                 padding: 4px 0; border-bottom: 1px dashed #eee; }
      .footer { margin-top: 30px; padding-top: 12px; border-top: 1px solid #e5e7eb;
                font-size: 12px; color: #9ca3af; text-align: center; }
      @media print {
        body { background: #fff; }
        .sheet { box-shadow: none; margin: 0; max-width: none; padding: 12mm; }
      }
    </style>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title} · 行程单</title>
{css}
</head>
<body>
  <div class="sheet">
    <h1 class="doc-title">{title}</h1>
    <div class="subtitle">企业智行 · 行程单（Corporate Journey Hub）</div>
    <div class="meta">{''.join(f'<span>{m}</span>' for m in meta_items)}</div>
    {days_html}
    {checklist_html}
    {expense_html}
    <div class="footer">本行程单由企业智行自动生成 · 生成时间 {generated_at}</div>
  </div>
</body>
</html>"""
    return html


@router.get("/trips/{trip_id}/export", tags=["行程管理"])
async def export_trip(trip_id: str, session_id: str = Query(default="")):
    """
    导出行程单：返回打印 / 另存为 PDF 友好的 HTML（零外部依赖）。

    前端拿到 HTML 后在新建窗口中渲染并触发浏览器打印（可「另存为 PDF」），
    无需 python-docx 等额外依赖，亦为后续 docx/pdf 生成保留统一渲染入口。
    """
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, session_id)
    html = _render_itinerary_html(trip)
    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")
