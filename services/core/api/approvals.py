"""审批 API —— HTTP 薄壳，流转逻辑归 core.approval.engine（唯一业务主线）

鉴权口径（v3 加固，2026-09-25）：审批是本系统的**业务敏感面**，四个接口一律要求
调用方声明身份，并按「申请人 / 审批人」角色做授权，而不是放任任何人调用：

    GET    /approvals                      需声明身份；非管理员只能看到与自己相关的单
    POST   /approvals                      身份由登录态决定，**不接受请求体指定申请人**
    POST   /approvals/{id}/approve|reject  调用方须是该单的审批人，或管理员
    POST   /approvals/{id}/cancel          调用方须是该单的申请人，或管理员

身份来自 `core.deps.declared_user_id`：登录态（Bearer → username）优先，其次显式
session_id（保留「不登录也能跑通演示」的直连路径）。**完全未声明身份一律 401**，
不再放行 —— 旧版这四个接口无任何校验，任何可访问服务的人都能给自己开单并当场批掉。
"""
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import deps

logger = logging.getLogger("core.api.approvals")

router = APIRouter()


class CreateApprovalRequest(BaseModel):
    trip_id: str = Field(..., description="行程 ID")
    employee_id: str = Field(default="", description="申请人 ID（仅管理员可代指定，普通用户强制取登录态）")
    approver_id: str = Field(..., description="审批人 ID")
    remark: str = Field(default="", description="申请备注")


class ApproveRequest(BaseModel):
    comment: str = Field(default="", description="审批意见")


class RejectRequest(BaseModel):
    comment: str = Field(default="", description="拒绝原因")


def _engine():
    if deps.approval_engine is None:
        raise HTTPException(503, "审批闭环未就绪")
    return deps.approval_engine


def _caller(request: Request, session_id: str = "") -> str:
    """审批接口统一身份口径：必须声明身份，否则 401。

    注意 `declared_user_id` 自身会对「带了 Bearer 但验不过」直接抛 401，
    不会回退到 workspace —— 那种回退会把「登录失效」伪装成「查无数据」。
    """
    who = deps.declared_user_id(request, session_id)
    if not who:
        raise HTTPException(401, "审批操作需要登录身份")
    return who


def _is_admin(request: Request, who: str) -> bool:
    """是否为管理员（用于「跨人操作」的例外放行）。"""
    store = getattr(request.app.state, "user_store", None)
    user = store.get(who) if store else None
    return (user or {}).get("role") == "admin"


def _require_actor(request: Request, who: str, expected: str, what: str):
    """授权：调用方须是 `expected` 本人，或管理员。"""
    if who == expected or _is_admin(request, who):
        return
    raise HTTPException(403, f"无权{what}：该单归属 {expected or '未知'}，当前身份 {who}")


@router.get("/approvals", tags=["审批管理"])
async def list_approvals(
    request: Request,
    employee_id: str = Query(default="", description="申请人 ID"),
    approver_id: str = Query(default="", description="审批人 ID"),
    status: str = Query(default="", description="审批状态"),
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """审批列表

    非管理员**只能看到与自己相关的单**：无论怎么传过滤参数，结果都会与
    「我是申请人 或 我是审批人」取交集，避免靠改 query 参数读全公司审批。
    """
    engine = _engine()
    who = _caller(request, session_id)
    store = engine.approvals

    if employee_id:
        approvals = store.list_by_employee(employee_id)
    elif approver_id:
        approvals = store.list_by_approver(approver_id, status or "pending")
    else:
        approvals = store.list_all()

    if status and not approver_id:
        approvals = [a for a in approvals if a.get("status") == status]

    if not _is_admin(request, who):
        approvals = [
            a for a in approvals
            if a.get("employee_id") == who or a.get("approver_id") == who
        ]

    return {"approvals": [engine.enrich(a) for a in approvals], "count": len(approvals)}


@router.post("/approvals", tags=["审批管理"])
async def create_approval(
    req: CreateApprovalRequest,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """手工创建审批请求（非自动链路；行程确认后的自动审批走引擎）

    申请人取登录态，**不接受请求体指定**（仅管理员可代指定）；
    建单时同步把行程置为待审批，否则后续审批通过将无法回写行程状态。
    """
    engine = _engine()
    who = _caller(request, session_id)

    if req.employee_id and req.employee_id != who and not _is_admin(request, who):
        raise HTTPException(403, "只能以本人身份发起审批")

    trip = engine.trips.get(req.trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {req.trip_id}")

    employee = engine.employees.get(req.employee_id or who) if engine.employees else None
    if not employee:
        raise HTTPException(404, f"员工不存在: {req.employee_id or who}")
    if engine.employees and not engine.employees.get(req.approver_id):
        raise HTTPException(404, f"审批人不存在: {req.approver_id}")

    violations = []
    policy_id = ""
    if engine.policy:
        policy, violations = engine.policy.confirm_check(trip, employee)
        policy_id = (policy or {}).get("policy_id", "")

    approval = engine.create({
        "trip_id": req.trip_id,
        "employee_id": employee.get("employee_id") or (req.employee_id or who),
        "approver_id": req.approver_id,
        "total_amount": trip.get("budget_total", 0),
        "policy_id": policy_id,
        "violations": violations,
        "remark": req.remark,
        "status": "pending",
    })
    logger.info(f"approval_created by {who}: {approval.get('approval_id')} trip={req.trip_id}")
    return {
        "status": "ok",
        "approval_id": approval.get("approval_id"),
        "approval": engine.enrich(approval),
    }


@router.get("/approvals/{approval_id}", tags=["审批管理"])
async def get_approval(
    approval_id: str,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """审批详情（仅申请人 / 审批人 / 管理员可读）"""
    engine = _engine()
    who = _caller(request, session_id)
    approval = engine.approvals.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")
    if not (
        who in (approval.get("employee_id"), approval.get("approver_id"))
        or _is_admin(request, who)
    ):
        raise HTTPException(404, f"审批不存在: {approval_id}")  # 不暴露存在性
    return engine.enrich(approval)


@router.post("/approvals/{approval_id}/approve", tags=["审批管理"])
async def approve_request(
    approval_id: str,
    req: ApproveRequest,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """审批通过：行程 pending_approval → planned（生效）。仅该单审批人或管理员可操作。"""
    engine = _engine()
    who = _caller(request, session_id)
    approval = engine.approvals.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")
    _require_actor(request, who, approval.get("approver_id", ""), "审批该申请")
    try:
        updated = engine.approve(approval_id, req.comment)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    logger.info(f"approval_approved by {who}: {approval_id}")
    return {"status": "ok", "approval": updated}


@router.post("/approvals/{approval_id}/reject", tags=["审批管理"])
async def reject_request(
    approval_id: str,
    req: RejectRequest,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """审批拒绝：行程 pending_approval → cancelled（作废）。仅该单审批人或管理员可操作。"""
    engine = _engine()
    who = _caller(request, session_id)
    approval = engine.approvals.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")
    _require_actor(request, who, approval.get("approver_id", ""), "拒绝该申请")
    try:
        updated = engine.reject(approval_id, req.comment)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    logger.info(f"approval_rejected by {who}: {approval_id}")
    return {"status": "ok", "approval": updated}


@router.post("/approvals/{approval_id}/cancel", tags=["审批管理"])
async def cancel_approval(
    approval_id: str,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """取消审批（仅待审批可取消）。仅申请人或管理员可操作。"""
    engine = _engine()
    who = _caller(request, session_id)
    approval = engine.approvals.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")
    _require_actor(request, who, approval.get("employee_id", ""), "取消该申请")
    try:
        updated = engine.cancel(approval_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    logger.info(f"approval_cancelled by {who}: {approval_id}")
    return {"status": "ok", "approval": updated}
