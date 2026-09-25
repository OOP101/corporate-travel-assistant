"""行程 API —— HTTP 薄壳（v3）

生成/确认逻辑已下沉：
  生成 → core.agent.pipeline（与 Agent 工具共用同一条管线）
  确认 → core.approval.engine（审批闭环，唯一业务主线）
本文件只剩 HTTP 契约：SSE 帧映射、请求模型、CRUD 与属主校验。
"""
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from shared.sse import SSE_DONE, sse_frame, sse_stream_response

from core import deps
from core.archive import SummaryGenerator
from core.agent.pipeline import generate_draft_stream

logger = logging.getLogger("core.api.trips")

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


def _deny_if_not_owner(trip: dict, request: Request, session_id: str = ""):
    """行程属主校验（防 IDOR）。

    只在调用方**声明了身份**时拒绝：身份取自登录态（Bearer token → username），
    其次显式 session_id。与行程归属 user_id 不符时按 404 拒绝，不暴露行程存在性。
    未声明身份（既无 Bearer 也无 session_id）的调用放行——直接调 API 与演示走这条。
    """
    owner = trip.get("user_id") or ""
    declared = deps.declared_user_id(request, session_id)
    if declared and owner and declared != owner:
        raise HTTPException(404, f"行程不存在: {trip.get('trip_id')}")


def _pending_guard(trip: dict):
    """审批门禁：待审批行程不允许调整（PRD 3.5）。"""
    if trip.get("status") == "pending_approval":
        raise HTTPException(409, "行程待主管审批，审批通过后才能调整")


# ---------------------------------------------------------------------------
# 行程生成 (SSE 流式) —— 薄壳：kind 帧 → SSE event 帧
# ---------------------------------------------------------------------------
@router.post("/trips/generate", tags=["行程生成"])
async def generate_trip(req: GenerateTripRequest, request: Request):
    """
    流式生成行程方案草案 (SSE)

    事件帧:
      event: status   → 正在分析...
      event: chunk    → 行程 JSON 文本片段
      event: clarify  → 必填参数缺失（scene/目的地/日期天数），附缺参清单，本次不生成
      event: policy   → 政策预检结果（经政策外接服务，仅预警不审批）
      event: draft    → 草案生成完成（未落库），附 trip / defaulted（代填项）/ params
      event: error    → 错误
      event: timing   → 各阶段耗时埋点

    草案经用户确认后调 POST /trips/confirm 落库并触发审批。
    """
    if deps.llm_manager is None or deps.trip_store is None:
        raise HTTPException(503, "服务未就绪")

    user_id = deps.resolve_user_id(request, req.session_id)

    def generate():
        try:
            yield sse_frame({"event": "status", "content": "正在分析您的出行需求..."})
            for frame in generate_draft_stream(
                req.query,
                session_id=req.session_id,
                user_id=user_id,
                model=req.model,
                preferences=req.preferences,
                params=req.params,
                carry=req.carry,
            ):
                kind = frame.get("kind")
                if kind == "progress":
                    continue  # HTTP 侧首帧已发 status，过程提示不再重复透传
                yield sse_frame({"event": kind, **{k: v for k, v in frame.items() if k != "kind"}})
            yield SSE_DONE
        except Exception as e:
            logger.error(f"行程草案生成失败: {e}", exc_info=True)
            yield sse_frame({"event": "error", "content": str(e)})

    return sse_stream_response(generate())


# ---------------------------------------------------------------------------
# 方案确认 (S4 → S5) —— 审批闭环引擎
# ---------------------------------------------------------------------------
@router.post("/trips/confirm", tags=["行程生成"])
async def confirm_trip(req: ConfirmTripRequest, request: Request):
    """确认行程草案：落库 + 政策检查 + 审批发起（审批只允许在用户确认后发生）。"""
    if deps.trip_store is None or deps.approval_engine is None:
        raise HTTPException(503, "服务未就绪")

    user_id = deps.resolve_user_id(request, req.session_id)
    try:
        return deps.approval_engine.confirm_draft(req.trip or {}, user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# 行程 CRUD
# ---------------------------------------------------------------------------
@router.get("/trips", tags=["行程管理"])
async def list_trips(
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """行程列表"""
    user_id = deps.resolve_user_id(request, session_id)
    trips = deps.trip_store.list_by_user(user_id)
    return {"trips": trips, "count": len(trips)}


@router.get("/trips/{trip_id}", tags=["行程管理"])
async def get_trip(
    trip_id: str,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """行程详情"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, request, session_id)
    return trip


@router.put("/trips/{trip_id}", tags=["行程管理"])
async def update_trip(
    trip_id: str,
    req: UpdateTripRequest,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """编辑行程（仅允许更新白名单字段；待审批行程不可调整）"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, request, session_id)
    _pending_guard(trip)
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
    request: Request,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """删除行程"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, request, session_id)
    deps.trip_store.delete(trip_id)
    return {"status": "ok", "trip_id": trip_id}


# ---------------------------------------------------------------------------
# 应变重排
# ---------------------------------------------------------------------------
@router.post("/trips/{trip_id}/reroute", tags=["行程管理"])
async def reroute_trip(
    trip_id: str,
    req: RerouteRequest,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """应变重排：指定活动变更后，重新排列受影响的后续行程。"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, request, session_id)
    _pending_guard(trip)

    if deps.reroute_engine is None:
        raise HTTPException(503, "重排引擎未就绪")

    updated_trip = deps.reroute_engine.reroute(trip, req.changed_activity, req.reason or "用户主动调整")
    deps.trip_store.update(trip_id, updated_trip)

    return {
        "status": "ok",
        "trip_id": trip_id,
        "message": updated_trip.get("reroute_summary", "行程已重排"),
        "reroute_summary": updated_trip.get("reroute_summary", ""),
    }


# ---------------------------------------------------------------------------
# 出行清单 / 总结 / 消费统计
# ---------------------------------------------------------------------------
@router.get("/trips/{trip_id}/checklist", tags=["行程管理"])
async def get_checklist(
    trip_id: str,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """获取出行清单"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, request, session_id)

    if trip.get("checklist"):
        return {"trip_id": trip_id, "checklist": trip["checklist"], "source": "trip"}

    items = deps.checklist_gen.generate(trip)
    trip["checklist"] = items
    deps.trip_store.update(trip_id, {"checklist": items})
    return {"trip_id": trip_id, "checklist": items, "source": "generated"}


@router.post("/trips/{trip_id}/summary", tags=["行程管理"])
async def generate_summary(
    trip_id: str,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """生成行程总结"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, request, session_id)

    summary = deps.summary_gen.generate(trip)
    return {"trip_id": trip_id, "summary": summary}


@router.get("/trips/{trip_id}/expenses", tags=["行程管理"])
async def get_expenses(
    trip_id: str,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """消费统计（复用 SummaryGenerator._calc_expenses 的规则计算逻辑）"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, request, session_id)

    expense_summary = SummaryGenerator._calc_expenses(trip, {})
    return {"trip_id": trip_id, "expense_summary": expense_summary}


# ---------------------------------------------------------------------------
# 跨服务桥：政策检查（行程 × 政策；政策能力归外接服务，行程数据归核心）
# ---------------------------------------------------------------------------
@router.post("/policies/check", tags=["差旅政策"])
async def check_policy_violations(trip_id: str, policy_id: str):
    """检查行程政策违规"""
    if deps.policy_service is None:
        raise HTTPException(503, "政策服务未就绪")
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")

    policy = deps.policy_service.policy_store.get(policy_id)
    if not policy:
        raise HTTPException(404, f"政策不存在: {policy_id}")

    violations = deps.policy_service.check_violations(trip, policy)
    return {
        "trip_id": trip_id,
        "policy_id": policy_id,
        "violations": violations,
        "has_violations": len(violations) > 0,
    }


# ---------------------------------------------------------------------------
# 行程单导出 —— 打印 / 另存为 PDF 友好的 HTML，零外部依赖
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
async def export_trip(
    trip_id: str,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（声明后做属主校验）"),
):
    """导出行程单：打印 / 另存为 PDF 友好的 HTML（零外部依赖）。"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    _deny_if_not_owner(trip, request, session_id)
    html = _render_itinerary_html(trip)
    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")
