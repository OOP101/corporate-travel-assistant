"""审批 API —— HTTP 薄壳，流转逻辑归 core.approval.engine（唯一业务主线）"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core import deps

router = APIRouter()


class CreateApprovalRequest(BaseModel):
    trip_id: str = Field(..., description="行程 ID")
    employee_id: str = Field(..., description="申请人 ID")
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


@router.get("/approvals", tags=["审批管理"])
async def list_approvals(
    employee_id: str = Query(default="", description="申请人 ID"),
    approver_id: str = Query(default="", description="审批人 ID"),
    status: str = Query(default="", description="审批状态"),
):
    """审批列表"""
    engine = _engine()
    store = engine.approvals
    if employee_id:
        approvals = store.list_by_employee(employee_id)
    elif approver_id:
        approvals = store.list_by_approver(approver_id, status or "pending")
    else:
        approvals = store.list_all()

    if status and not approver_id:
        approvals = [a for a in approvals if a.get("status") == status]

    return {"approvals": [engine.enrich(a) for a in approvals], "count": len(approvals)}


@router.post("/approvals", tags=["审批管理"])
async def create_approval(req: CreateApprovalRequest):
    """创建审批请求（手工发起；行程确认后的自动审批走引擎）"""
    engine = _engine()
    trip = engine.trips.get(req.trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {req.trip_id}")

    employee = engine.employees.get(req.employee_id) if engine.employees else None
    if not employee:
        raise HTTPException(404, f"员工不存在: {req.employee_id}")

    approver = engine.employees.get(req.approver_id) if engine.employees else None
    if not approver:
        raise HTTPException(404, f"审批人不存在: {req.approver_id}")

    violations = []
    policy_id = ""
    if engine.policy:
        policy, violations = engine.policy.confirm_check(trip, employee)
        policy_id = (policy or {}).get("policy_id", "")

    approval = {
        "trip_id": req.trip_id,
        "employee_id": req.employee_id,
        "approver_id": req.approver_id,
        "total_amount": trip.get("budget_total", 0),
        "policy_id": policy_id,
        "violations": violations,
        "remark": req.remark,
        "status": "pending",
    }
    approval_id = engine.approvals.save(approval)
    return {
        "status": "ok",
        "approval_id": approval_id,
        "approval": engine.approvals.get(approval_id),
    }


@router.get("/approvals/{approval_id}", tags=["审批管理"])
async def get_approval(approval_id: str):
    """审批详情"""
    engine = _engine()
    approval = engine.approvals.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")
    return engine.enrich(approval)


@router.post("/approvals/{approval_id}/approve", tags=["审批管理"])
async def approve_request(approval_id: str, req: ApproveRequest):
    """审批通过：行程 pending_approval → planned（生效）"""
    engine = _engine()
    try:
        updated = engine.approve(approval_id, req.comment)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "approval": updated}


@router.post("/approvals/{approval_id}/reject", tags=["审批管理"])
async def reject_request(approval_id: str, req: RejectRequest):
    """审批拒绝：行程 pending_approval → cancelled（作废）"""
    engine = _engine()
    try:
        updated = engine.reject(approval_id, req.comment)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "approval": updated}


@router.post("/approvals/{approval_id}/cancel", tags=["审批管理"])
async def cancel_approval(approval_id: str):
    """取消审批（仅待审批可取消）"""
    engine = _engine()
    try:
        updated = engine.cancel(approval_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "approval": updated}
