"""报销管理 Router —— 报销提交 / 审批 / 打款 (P2)

报销单关联一次行程的费用汇总（或前端传入的报销明细），按员工直属主管
自动指派审批人；审批通过后由财务/管理员打款（状态 → reimbursed）。
"""
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api import deps
from archive import SummaryGenerator

logger = logging.getLogger("planner-core.reimbursements")

router = APIRouter()


class SubmitReimbursementRequest(BaseModel):
    trip_id: str = Field(..., description="关联行程 ID")
    employee_id: str = Field(..., description="申请人（员工）ID")
    approver_id: str = Field(default="", description="审批人 ID（缺省按员工直属主管自动指派）")
    remark: str = Field(default="", description="报销说明")
    items: List[dict] = Field(default_factory=list, description="报销明细（可选；缺省按行程费用汇总）")


class ReimburseAction(BaseModel):
    comment: str = Field(default="", description="审批/打款意见")
    operator: str = Field(default="", description="操作人（打款记录）")


def _amount_of(trip: dict, items: List[dict]) -> float:
    """报销金额：有明细则累加明细，否则按行程费用汇总。"""
    if items:
        return round(sum(float(it.get("amount", 0) or 0) for it in items), 2)
    exp = SummaryGenerator._calc_expenses(trip, {})
    return round(float(exp.get("total", 0) or 0), 2)


@router.get("/reimbursements", tags=["报销管理"])
async def list_reimbursements(
    employee_id: str = Query(default="", description="申请人 ID"),
    approver_id: str = Query(default="", description="审批人 ID"),
    status: str = Query(default="", description="状态：pending/approved/rejected/reimbursed"),
):
    """报销单列表"""
    if employee_id:
        items = deps.reimbursement_store.list_by_employee(employee_id)
    elif approver_id:
        items = deps.reimbursement_store.list_by_approver(approver_id, status or "pending")
    else:
        items = deps.reimbursement_store.list_all()

    if status and not approver_id:
        items = [r for r in items if r.get("status") == status]

    return {"reimbursements": items, "count": len(items)}


@router.post("/reimbursements", tags=["报销管理"])
async def submit_reimbursement(req: SubmitReimbursementRequest):
    """提交报销单：校验行程/员工，自动计算金额与指派审批人。"""
    trip = deps.trip_store.get(req.trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {req.trip_id}")
    employee = deps.employee_store.get(req.employee_id)
    if not employee:
        raise HTTPException(404, f"员工不存在: {req.employee_id}")

    # 审批人：显式指定优先；否则按直属主管自动指派
    approver_id = req.approver_id
    if not approver_id:
        manager = deps.employee_store.get_manager(req.employee_id)
        if not manager:
            raise HTTPException(400, "员工无直属主管，请显式指定审批人 (approver_id)")
        approver_id = manager.get("employee_id")

    if not deps.employee_store.get(approver_id):
        raise HTTPException(404, f"审批人不存在: {approver_id}")

    amount = _amount_of(trip, req.items)
    if amount <= 0:
        raise HTTPException(400, "报销金额为 0，无法提交（行程无有效费用）")

    # 费用明细：前端传了用前端的，否则用行程费用按类别汇总
    if req.items:
        items = req.items
        breakdown = {}
    else:
        exp = SummaryGenerator._calc_expenses(trip, {})
        breakdown = exp.get("by_category", {}) or {}
        items = [{"category": k, "amount": round(float(v), 2)} for k, v in breakdown.items()]

    reimbursement = {
        "trip_id": req.trip_id,
        "employee_id": req.employee_id,
        "approver_id": approver_id,
        "amount": amount,
        "items": items,
        "breakdown": breakdown,
        "remark": req.remark,
        "status": "pending",
    }
    rid = deps.reimbursement_store.save(reimbursement)
    return {
        "status": "ok",
        "reimbursement_id": rid,
        "reimbursement": deps.reimbursement_store.get(rid),
    }


@router.get("/reimbursements/{reimbursement_id}", tags=["报销管理"])
async def get_reimbursement(reimbursement_id: str):
    """报销单详情（附带行程/员工/审批人信息）"""
    r = deps.reimbursement_store.get(reimbursement_id)
    if not r:
        raise HTTPException(404, f"报销单不存在: {reimbursement_id}")

    if r.get("trip_id"):
        r["trip"] = deps.trip_store.get(r["trip_id"])
    if r.get("employee_id"):
        r["employee"] = deps.employee_store.get(r["employee_id"])
    if r.get("approver_id"):
        r["approver"] = deps.employee_store.get(r["approver_id"])

    return r


@router.post("/reimbursements/{reimbursement_id}/approve", tags=["报销管理"])
async def approve_reimbursement(reimbursement_id: str, req: ReimburseAction):
    """审批通过"""
    r = deps.reimbursement_store.get(reimbursement_id)
    if not r:
        raise HTTPException(404, f"报销单不存在: {reimbursement_id}")
    if r.get("status") != "pending":
        raise HTTPException(400, f"报销单状态不是待审批: {r.get('status')}")

    updated = deps.reimbursement_store.approve(reimbursement_id, req.comment)
    return {"status": "ok", "reimbursement": updated}


@router.post("/reimbursements/{reimbursement_id}/reject", tags=["报销管理"])
async def reject_reimbursement(reimbursement_id: str, req: ReimburseAction):
    """审批拒绝"""
    r = deps.reimbursement_store.get(reimbursement_id)
    if not r:
        raise HTTPException(404, f"报销单不存在: {reimbursement_id}")
    if r.get("status") != "pending":
        raise HTTPException(400, f"报销单状态不是待审批: {r.get('status')}")

    updated = deps.reimbursement_store.reject(reimbursement_id, req.comment)
    return {"status": "ok", "reimbursement": updated}


@router.post("/reimbursements/{reimbursement_id}/pay", tags=["报销管理"])
async def pay_reimbursement(reimbursement_id: str, req: ReimburseAction):
    """打款（仅审批通过的报销单可打款）"""
    r = deps.reimbursement_store.get(reimbursement_id)
    if not r:
        raise HTTPException(404, f"报销单不存在: {reimbursement_id}")
    if r.get("status") != "approved":
        raise HTTPException(400, f"仅审批通过的报销单可打款，当前状态: {r.get('status')}")

    updated = deps.reimbursement_store.pay(reimbursement_id, req.operator)
    return {"status": "ok", "reimbursement": updated}
