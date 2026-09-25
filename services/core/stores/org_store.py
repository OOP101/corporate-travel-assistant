"""
组织与人员存储 —— 部门/员工/职级管理

使用 BaseJsonStore 实现持久化存储。
"""
import logging
import time
from typing import List, Optional, Dict

from shared.store.base_store import BaseJsonStore
from shared.store.document_store import DocumentCorpusStore

logger = logging.getLogger("core.store.org")


# 2026-09-25 收敛：DepartmentStore（部门）与 ReimbursementStore（报销）已删除
# —— 组织管理页 / 报销管理页及其 CRUD 路由同步下线，两个类零消费者。


class EmployeeStore(BaseJsonStore):
    """员工存储"""
    _id_field = "employee_id"
    _id_prefix = "emp_"

    def list_by_dept(self, dept_id: str) -> List[dict]:
        """列出指定部门的所有员工"""
        return [
            e for e in self._entities.values()
            if e.get("dept_id") == dept_id and e.get("is_active", True)
        ]

    def list_by_level(self, level: str) -> List[dict]:
        """列出指定职级的所有员工"""
        return [
            e for e in self._entities.values()
            if e.get("level") == level and e.get("is_active", True)
        ]

    def get_manager(self, employee_id: str) -> Optional[dict]:
        """获取员工的直属主管"""
        emp = self.get(employee_id)
        if not emp:
            return None
        manager_id = emp.get("manager_id", "")
        return self.get(manager_id) if manager_id else None

    def search(self, keyword: str) -> List[dict]:
        """按姓名/职位搜索员工"""
        keyword_lower = keyword.lower()
        return [
            e for e in self._entities.values()
            if e.get("is_active", True) and (
                keyword_lower in e.get("name", "").lower() or
                keyword_lower in e.get("title", "").lower() or
                keyword_lower in e.get("email", "").lower()
            )
        ]


class PolicyStore(BaseJsonStore):
    """差旅政策存储"""
    _id_field = "policy_id"
    _id_prefix = "pol_"

    def get_by_level(self, level: str) -> List[dict]:
        """获取适用于指定职级的政策"""
        return [
            p for p in self._entities.values()
            if p.get("is_active", True) and (
                p.get("level") == level or p.get("level") == ""
            )
        ]

    def get_best_match(self, level: str, city_tier: str = "all") -> Optional[dict]:
        """获取最匹配的政策 (精确匹配 > 通用)"""
        policies = self.get_by_level(level)
        
        # 优先精确匹配城市等级
        for p in policies:
            if p.get("city_tier") == city_tier:
                return p
        
        # 其次匹配通用政策
        for p in policies:
            if p.get("city_tier") == "all":
                return p
        
        return policies[0] if policies else None

    def check_violations(self, trip: dict, policy: dict) -> List[dict]:
        """检查行程是否违反政策"""
        violations = []
        
        if not policy:
            return violations
        
        total_cost = trip.get("budget_total", 0)
        hotel_limit = policy.get("hotel_limit", 0)
        meal_limit = policy.get("meal_limit", 0)
        transport_limit = policy.get("transport_limit", 0)
        
        # 检查各项费用
        for day in trip.get("days", []):
            for activity in day.get("activities", []):
                cost = activity.get("estimated_cost", 0)
                act_type = activity.get("type", "")
                
                if act_type == "accommodation" and hotel_limit > 0 and cost > hotel_limit:
                    violations.append({
                        "type": "hotel_exceed",
                        "activity": activity.get("title", ""),
                        "amount": cost,
                        "limit": hotel_limit,
                        "message": f"住宿费用 ¥{cost} 超过标准 ¥{hotel_limit}",
                    })
                
                if act_type == "dining" and meal_limit > 0 and cost > meal_limit:
                    violations.append({
                        "type": "meal_exceed",
                        "activity": activity.get("title", ""),
                        "amount": cost,
                        "limit": meal_limit,
                        "message": f"餐饮费用 ¥{cost} 超过标准 ¥{meal_limit}",
                    })
        
        return violations


class ApprovalStore(BaseJsonStore):
    """审批请求存储"""
    _id_field = "approval_id"
    _id_prefix = "apr_"

    def list_by_employee(self, employee_id: str) -> List[dict]:
        """列出员工提交的审批"""
        return [
            a for a in self._entities.values()
            if a.get("employee_id") == employee_id
        ]

    def list_by_approver(self, approver_id: str, status: str = "pending") -> List[dict]:
        """列出待审批的请求"""
        return [
            a for a in self._entities.values()
            if a.get("approver_id") == approver_id and a.get("status") == status
        ]

    def approve(self, approval_id: str, comment: str = "") -> Optional[dict]:
        """审批通过"""
        import time
        return self.update(approval_id, {
            "status": "approved",
            "approver_comment": comment,
            "approved_at": time.time(),
        })

    def reject(self, approval_id: str, comment: str = "") -> Optional[dict]:
        """审批拒绝"""
        return self.update(approval_id, {
            "status": "rejected",
            "approver_comment": comment,
        })


class PolicyDocumentStore(DocumentCorpusStore):
    """企业差旅政策文档存储（RAG 检索语料）

    检索与索引实现见 shared.store.document_store.DocumentCorpusStore ——
    政策文档与景点攻略语料共用同一套「关键词 + 语义」双路检索。
    """
    _id_field = "doc_id"
    _id_prefix = "doc_"
