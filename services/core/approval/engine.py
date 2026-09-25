"""审批闭环引擎 —— 企业智行唯一的业务主线（v3 一等模块）

状态机（PRD v2 S4→S5 + 审批门禁）：

    草案(draft) ──用户确认──▶ 落库 ──政策检查──▶ [需审批] pending_approval ──通过──▶ planned
                                    │                    │
                                    │                    ├─拒绝──▶ cancelled
                                    │                    └─取消──▶ cancelled
                                    └─[免审批]──────────────────▶ 直接生效(planned)

铁律：
  - 审批只允许在用户确认（S4 confirm）之后发起，确认前政策违例仅预警；
  - 待审批行程不可调整（reroute/update 门禁在 api 层拒绝）；
  - 政策检查经工具总线调「政策外接服务」，个人出游 / 无员工档案豁免。
"""
import logging
from typing import Optional

from core import deps

logger = logging.getLogger("core.approval")


class ApprovalEngine:
    """审批闭环：确认（落库+政策+审批发起）与审批流转（通过/拒绝/取消）的唯一入口"""

    def __init__(self, trip_store, approval_store, employee_store, policy_service):
        self.trips = trip_store
        self.approvals = approval_store
        self.employees = employee_store
        self.policy = policy_service

    # ------------------------------------------------------------------
    # S4 → S5：用户确认草案
    # ------------------------------------------------------------------
    def confirm_draft(self, trip_dict: dict, user_id: str) -> dict:
        """确认行程草案：落库 + 政策检查 + 审批发起。

        Returns:
            {status, trip_id, trip, events, message}
        """
        trip_dict = trip_dict or {}
        if not trip_dict.get("destination") and not trip_dict.get("title"):
            raise ValueError("无效的行程草案（缺少目的地/标题）")

        trip_dict["user_id"] = user_id
        if trip_dict.get("status") == "pending_approval":
            trip_dict["status"] = "draft"  # 草案不应携带旧状态

        trip_id = self.trips.save(trip_dict)

        # S5 链路：政策检查 + 审批发起（仅此路径允许触发审批）
        events = self._confirm_policy_flow(trip_dict, trip_id, user_id)
        if any(e.get("event") == "approval" for e in events):
            # 审批门禁：需审批的行程置为待审批，主管通过后才生效
            self.trips.update(trip_id, {"status": "pending_approval"})

        saved = self.trips.get(trip_id) or trip_dict
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

    def _confirm_policy_flow(self, trip_dict: dict, trip_id: str, user_id: str) -> list:
        """确认后的政策检查 → 超标提示 → 审批发起（经政策外接服务）。"""
        events = []
        if self.policy is None:
            return events
        employee = deps.employee_of(user_id) if deps.employee_store else None

        exempt = self.policy.exempt_reason(trip_dict, employee)
        if exempt:
            logger.info(f"跳过确认后政策/审批链路：{exempt}")
            return events

        try:
            policy, violations = self.policy.confirm_check(trip_dict, employee)
            if not policy:
                return events

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
            remark = "用户确认后发起"
            if trip_dict.get("scene"):
                remark += f" · 场景：{trip_dict['scene']}"
            if trip_dict.get("purpose"):
                remark += f" · 事由：{trip_dict['purpose']}"

            if needs_approval and employee and approver_id and self.approvals:
                if self.employees and not self.employees.get(approver_id):
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
                    approval_id = self.approvals.save(approval)
                    events.append({
                        "event": "approval",
                        "approval_id": approval_id,
                        "approver_id": approver_id,
                        "has_violations": len(violations) > 0,
                        "content": (
                            "已发起审批（审批人："
                            f"{(self.employees.get(approver_id) or {}).get('name', approver_id)}）"
                        ),
                    })
        except Exception as e:
            # 政策/审批是增强链路，失败不阻断行程确认
            logger.warning(f"确认后政策/审批链路失败: {e}")
        return events

    # ------------------------------------------------------------------
    # 审批流转
    # ------------------------------------------------------------------
    def create(self, approval: dict) -> dict:
        """手工发起审批（非自动链路）—— 落库并**同步把行程置为待审批**。

        为什么必须同步改行程状态：`approve()` 的回写条件是 `status == "pending_approval"`，
        若建单时不置位，审批通过后行程状态永远停在原处 —— 表现为「审批过了，行程却没生效」。
        仅对尚未生效的行程（无状态 / draft）置位，不去动已经 planned 的行程。
        """
        approval = dict(approval or {})
        approval.setdefault("status", "pending")
        approval_id = self.approvals.save(approval)

        trip_id = approval.get("trip_id")
        trip = self.trips.get(trip_id) if trip_id else None
        if trip and trip.get("status") in (None, "", "draft"):
            self.trips.update(trip_id, {"status": "pending_approval"})

        return self.approvals.get(approval_id) or approval

    def approve(self, approval_id: str, comment: str = "") -> dict:
        """审批通过：pending → approved；行程 pending_approval → planned（生效）。"""
        approval = self._get_pending(approval_id)
        updated = self.approvals.approve(approval_id, comment)

        trip_id = approval.get("trip_id")
        if trip_id and (self.trips.get(trip_id) or {}).get("status") == "pending_approval":
            self.trips.update(trip_id, {"status": "planned"})
        if approval.get("violations") and approval.get("trip_id"):
            self.trips.update(approval["trip_id"], {"policy_reviewed": True})
        return updated

    def reject(self, approval_id: str, comment: str = "") -> dict:
        """审批拒绝：pending → rejected；行程 pending_approval → cancelled（作废）。"""
        approval = self._get_pending(approval_id)
        updated = self.approvals.reject(approval_id, comment)

        trip_id = approval.get("trip_id")
        if trip_id and (self.trips.get(trip_id) or {}).get("status") == "pending_approval":
            self.trips.update(trip_id, {"status": "cancelled"})
        return updated

    def cancel(self, approval_id: str) -> dict:
        """取消审批（仅待审批可取消）。"""
        self._get_pending(approval_id)
        return self.approvals.update(approval_id, {"status": "cancelled"})

    def _get_pending(self, approval_id: str) -> dict:
        approval = self.approvals.get(approval_id)
        if not approval:
            raise LookupError(f"审批不存在: {approval_id}")
        if approval.get("status") != "pending":
            raise ValueError(f"审批状态不是待审批: {approval.get('status')}")
        return approval

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def enrich(self, approval: dict) -> dict:
        """为审批补充关联信息（行程标题/目的地、申请人/审批人姓名），避免暴露原始 ID。"""
        if approval.get("trip_id"):
            trip = self.trips.get(approval["trip_id"]) or {}
            approval["trip"] = {
                "trip_id": approval["trip_id"],
                "title": trip.get("title", ""),
                "destination": trip.get("destination", ""),
            }
        if approval.get("employee_id"):
            emp = (self.employees.get(approval["employee_id"]) or {}) if self.employees else {}
            approval["employee"] = {"employee_id": approval["employee_id"], "name": emp.get("name", "")}
        if approval.get("approver_id"):
            apr = (self.employees.get(approval["approver_id"]) or {}) if self.employees else {}
            approval["approver"] = {"approver_id": approval["approver_id"], "name": apr.get("name", "")}
        return approval
