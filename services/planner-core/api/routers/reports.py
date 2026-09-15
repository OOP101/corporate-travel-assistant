"""报表 Router (P2) —— 部门 / 月度 差旅与报销汇总（只读聚合，供管理后台）

聚合维度：
  - overview     : 全局 KPI（行程 / 报销 / 审批 的总量、金额、状态分布）
  - by-department: 按部门聚合（人数 / 行程数 / 预算 / 报销金额分布）
  - by-month     : 按月份聚合（行程数 / 预算 / 报销提交与已打款金额）
"""
import logging
import time
from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Query

from .. import deps

logger = logging.getLogger("planner-core.reports")

router = APIRouter()

_UNASSIGNED = "__unassigned__"


def _employee_dept_map() -> Dict[str, str]:
    """employee_id -> dept_id（含未归属标记）。"""
    m = {}
    for e in deps.employee_store.list_all():
        m[e.get("employee_id")] = e.get("dept_id") or _UNASSIGNED
    return m


def _dept_display(dept_id: str) -> str:
    if dept_id == _UNASSIGNED or not dept_id:
        return "未归属"
    d = deps.dept_store.get(dept_id)
    return d.get("name") if d else dept_id


@router.get("/reports/overview", tags=["报表"])
async def report_overview():
    """全局概览 KPI。"""
    trips = deps.trip_store.list_all()
    trip_status = defaultdict(int)
    trip_budget = 0.0
    for t in trips:
        trip_status[t.get("status", "unknown")] += 1
        trip_budget += float(t.get("budget_total") or 0)

    reimbs = deps.reimbursement_store.list_all()
    reimb_by_status = defaultdict(lambda: {"count": 0, "amount": 0.0})
    reimb_total = 0.0
    for r in reimbs:
        st = r.get("status", "unknown")
        reimb_by_status[st]["count"] += 1
        amt = float(r.get("amount") or 0)
        reimb_by_status[st]["amount"] += amt
        reimb_total += amt

    approves = deps.approval_store.list_all()
    appr_by_status = defaultdict(lambda: {"count": 0, "amount": 0.0})
    appr_total = 0.0
    for a in approves:
        st = a.get("status", "unknown")
        appr_by_status[st]["count"] += 1
        amt = float(a.get("total_amount") or 0)
        appr_by_status[st]["amount"] += amt
        appr_total += amt

    return {
        "trips": {
            "total": len(trips),
            "total_budget": round(trip_budget, 2),
            "by_status": dict(trip_status),
        },
        "reimbursements": {
            "total": len(reimbs),
            "total_amount": round(reimb_total, 2),
            "by_status": {k: {"count": v["count"], "amount": round(v["amount"], 2)} for k, v in reimb_by_status.items()},
        },
        "approvals": {
            "total": len(approves),
            "total_amount": round(appr_total, 2),
            "by_status": {k: {"count": v["count"], "amount": round(v["amount"], 2)} for k, v in appr_by_status.items()},
        },
    }


@router.get("/reports/by-department", tags=["报表"])
async def report_by_department():
    """按部门聚合：人数 / 行程 / 预算 / 报销分布。"""
    emp_dept = _employee_dept_map()
    emp_count = defaultdict(int)
    for d in emp_dept.values():
        emp_count[d] += 1

    agg = defaultdict(lambda: {
        "employee_count": 0, "trip_count": 0, "trip_budget": 0.0,
        "reimb_count": 0, "reimb_amount": 0.0,
        "reimbursed_amount": 0.0, "pending_amount": 0.0,
    })

    # 部门人数
    for d in emp_dept.values():
        agg[d]["employee_count"] += 1

    # 行程（按 user_id 是否命中员工映射）
    for t in deps.trip_store.list_all():
        d = emp_dept.get(t.get("user_id")) or _UNASSIGNED
        agg[d]["trip_count"] += 1
        agg[d]["trip_budget"] += float(t.get("budget_total") or 0)

    # 报销（按 employee_id 映射）
    for r in deps.reimbursement_store.list_all():
        d = emp_dept.get(r.get("employee_id")) or _UNASSIGNED
        amt = float(r.get("amount") or 0)
        agg[d]["reimb_count"] += 1
        agg[d]["reimb_amount"] += amt
        st = r.get("status")
        if st == "reimbursed":
            agg[d]["reimbursed_amount"] += amt
        elif st == "pending":
            agg[d]["pending_amount"] += amt

    rows = []
    for d, v in agg.items():
        rows.append({
            "dept_id": d,
            "dept_name": _dept_display(d),
            "employee_count": v["employee_count"],
            "trip_count": v["trip_count"],
            "trip_budget": round(v["trip_budget"], 2),
            "reimb_count": v["reimb_count"],
            "reimb_amount": round(v["reimb_amount"], 2),
            "reimbursed_amount": round(v["reimbursed_amount"], 2),
            "pending_amount": round(v["pending_amount"], 2),
        })
    rows.sort(key=lambda x: (x["dept_id"] == _UNASSIGNED, -x["trip_count"]))
    return {"departments": rows, "count": len(rows)}


@router.get("/reports/by-month", tags=["报表"])
async def report_by_month():
    """按月份聚合：行程数 / 预算 / 报销提交与已打款金额。"""
    month_trips = defaultdict(lambda: {"trip_count": 0, "trip_budget": 0.0})
    month_reimb = defaultdict(lambda: {"submitted": 0.0, "reimbursed": 0.0, "pending": 0.0})

    for t in deps.trip_store.list_all():
        m = (t.get("start_date") or "")[:7]
        if not m or m == "None":
            continue
        month_trips[m]["trip_count"] += 1
        month_trips[m]["trip_budget"] += float(t.get("budget_total") or 0)

    for r in deps.reimbursement_store.list_all():
        ts = r.get("created_at") or 0
        try:
            m = time.strftime("%Y-%m", time.localtime(ts))
        except Exception:
            continue
        amt = float(r.get("amount") or 0)
        month_reimb[m]["submitted"] += amt
        st = r.get("status")
        if st == "reimbursed":
            month_reimb[m]["reimbursed"] += amt
        elif st == "pending":
            month_reimb[m]["pending"] += amt

    rows = []
    for m in sorted(set(list(month_trips.keys()) + list(month_reimb.keys()))):
        t = month_trips.get(m, {"trip_count": 0, "trip_budget": 0.0})
        rb = month_reimb.get(m, {"submitted": 0.0, "reimbursed": 0.0, "pending": 0.0})
        rows.append({
            "month": m,
            "trip_count": t["trip_count"],
            "trip_budget": round(t["trip_budget"], 2),
            "reimb_submitted": round(rb["submitted"], 2),
            "reimb_reimbursed": round(rb["reimbursed"], 2),
            "reimb_pending": round(rb["pending"], 2),
        })
    return {"months": rows, "count": len(rows)}
