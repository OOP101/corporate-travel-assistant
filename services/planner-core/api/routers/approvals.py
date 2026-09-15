"""审批流转 Router —— 审批创建 / 通过 / 拒绝 / 取消 (P1 企业化)"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import deps

router = APIRouter()


def _enrich_approval(approval: dict) -> dict:
    """为审批补充关联信息（行程标题/目的地、申请人/审批人姓名），便于列表与详情直读，避免暴露原始 ID。"""
    if approval.get("trip_id"):
        trip = deps.trip_store.get(approval["trip_id"]) or {}
        approval["trip"] = {
            "trip_id": approval["trip_id"],
            "title": trip.get("title", ""),
            "destination": trip.get("destination", ""),
        }
    if approval.get("employee_id"):
        emp = deps.employee_store.get(approval["employee_id"]) or {}
        approval["employee"] = {
            "employee_id": approval["employee_id"],
            "name": emp.get("name", ""),
        }
    if approval.get("approver_id"):
        apr = deps.employee_store.get(approval["approver_id"]) or {}
        approval["approver"] = {
            "approver_id": approval["approver_id"],
            "name": apr.get("name", ""),
        }
    return approval


class CreateApprovalRequest(BaseModel):
    trip_id: str = Field(..., description="行程 ID")
    employee_id: str = Field(..., description="申请人 ID")
    approver_id: str = Field(..., description="审批人 ID")
    remark: str = Field(default="", description="申请备注")


class ApproveRequest(BaseModel):
    comment: str = Field(default="", description="审批意见")


class RejectRequest(BaseModel):
    comment: str = Field(default="", description="拒绝原因")


@router.get("/approvals", tags=["审批管理"])
async def list_approvals(
    employee_id: str = Query(default="", description="申请人 ID"),
    approver_id: str = Query(default="", description="审批人 ID"),
    status: str = Query(default="", description="审批状态"),
):
    """审批列表"""
    if employee_id:
        approvals = deps.approval_store.list_by_employee(employee_id)
    elif approver_id:
        approvals = deps.approval_store.list_by_approver(approver_id, status or "pending")
    else:
        approvals = deps.approval_store.list_all()

    # 过滤状态
    if status and not approver_id:
        approvals = [a for a in approvals if a.get("status") == status]

    return {"approvals": [_enrich_approval(a) for a in approvals], "count": len(approvals)}


@router.post("/approvals", tags=["审批管理"])
async def create_approval(req: CreateApprovalRequest):
    """创建审批请求"""
    # 验证行程存在
    trip = deps.trip_store.get(req.trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {req.trip_id}")

    # 验证员工存在
    employee = deps.employee_store.get(req.employee_id)
    if not employee:
        raise HTTPException(404, f"员工不存在: {req.employee_id}")

    # 验证审批人存在
    approver = deps.employee_store.get(req.approver_id)
    if not approver:
        raise HTTPException(404, f"审批人不存在: {req.approver_id}")

    # 获取匹配的政策并检查违规
    level = employee.get("level", "")
    policy = deps.policy_store.get_best_match(level)
    violations = []
    if policy:
        violations = deps.policy_store.check_violations(trip, policy)

    approval = {
        "trip_id": req.trip_id,
        "employee_id": req.employee_id,
        "approver_id": req.approver_id,
        "total_amount": trip.get("budget_total", 0),
        "policy_id": policy.get("policy_id", "") if policy else "",
        "violations": violations,
        "remark": req.remark,
        "status": "pending",
    }
    approval_id = deps.approval_store.save(approval)
    return {
        "status": "ok",
        "approval_id": approval_id,
        "approval": deps.approval_store.get(approval_id),
    }


@router.get("/approvals/{approval_id}", tags=["审批管理"])
async def get_approval(approval_id: str):
    """审批详情"""
    approval = deps.approval_store.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")

    # 补充关联信息
    if approval.get("trip_id"):
        approval["trip"] = deps.trip_store.get(approval["trip_id"])
    if approval.get("employee_id"):
        approval["employee"] = deps.employee_store.get(approval["employee_id"])
    if approval.get("approver_id"):
        approval["approver"] = deps.employee_store.get(approval["approver_id"])

    return approval


@router.post("/approvals/{approval_id}/approve", tags=["审批管理"])
async def approve_request(approval_id: str, req: ApproveRequest):
    """审批通过"""
    approval = deps.approval_store.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")
    if approval.get("status") != "pending":
        raise HTTPException(400, f"审批状态不是待审批: {approval.get('status')}")

    updated = deps.approval_store.approve(approval_id, req.comment)

    # PRD 3.5 审批门禁：主管通过后行程生效（pending_approval → planned）
    trip_id = approval.get("trip_id")
    if trip_id and (deps.trip_store.get(trip_id) or {}).get("status") == "pending_approval":
        deps.trip_store.update(trip_id, {"status": "planned"})

    # 如果有违规项，标记行程需要关注
    if approval.get("violations"):
        trip_id = approval.get("trip_id")
        if trip_id:
            deps.trip_store.update(trip_id, {"policy_reviewed": True})

    return {"status": "ok", "approval": updated}


@router.post("/approvals/{approval_id}/reject", tags=["审批管理"])
async def reject_request(approval_id: str, req: RejectRequest):
    """审批拒绝"""
    approval = deps.approval_store.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")
    if approval.get("status") != "pending":
        raise HTTPException(400, f"审批状态不是待审批: {approval.get('status')}")

    updated = deps.approval_store.reject(approval_id, req.comment)

    # PRD 3.5 审批门禁：主管拒绝则行程作废（pending_approval → cancelled），需重新规划
    trip_id = approval.get("trip_id")
    if trip_id and (deps.trip_store.get(trip_id) or {}).get("status") == "pending_approval":
        deps.trip_store.update(trip_id, {"status": "cancelled"})

    return {"status": "ok", "approval": updated}


@router.post("/approvals/{approval_id}/cancel", tags=["审批管理"])
async def cancel_approval(approval_id: str):
    """取消审批"""
    approval = deps.approval_store.get(approval_id)
    if not approval:
        raise HTTPException(404, f"审批不存在: {approval_id}")
    if approval.get("status") != "pending":
        raise HTTPException(400, f"审批状态不是待审批: {approval.get('status')}")

    updated = deps.approval_store.update(approval_id, {"status": "cancelled"})
    return {"status": "ok", "approval": updated}
