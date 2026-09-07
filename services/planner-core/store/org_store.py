"""
组织与人员存储 —— 部门/员工/职级管理

使用 BaseJsonStore 实现持久化存储。
"""
import logging
import time
from typing import List, Optional, Dict

from shared.store.base_store import BaseJsonStore
from shared.embedding import cosine_similarity

logger = logging.getLogger("planner-core.store.org")


def _make_excerpt(content: str, limit: int = 120) -> str:
    """截取原文片段，用于检索结果的可解释性引用"""
    text = " ".join((content or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


class DepartmentStore(BaseJsonStore):
    """部门存储"""
    _id_field = "dept_id"
    _id_prefix = "dept_"

    def list_by_parent(self, parent_id: str = "") -> List[dict]:
        """列出指定上级部门的子部门"""
        return [
            d for d in self._entities.values()
            if d.get("parent_id", "") == parent_id
        ]

    def get_children_recursive(self, dept_id: str) -> List[str]:
        """递归获取所有子部门 ID"""
        children = []
        for d in self._entities.values():
            if d.get("parent_id") == dept_id:
                children.append(d["dept_id"])
                children.extend(self.get_children_recursive(d["dept_id"]))
        return children


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


class ReimbursementStore(BaseJsonStore):
    """报销单存储 (P2)"""
    _id_field = "reimbursement_id"
    _id_prefix = "reb_"

    def list_by_employee(self, employee_id: str) -> List[dict]:
        """列出某员工提交的报销单"""
        return [
            r for r in self._entities.values()
            if r.get("employee_id") == employee_id
        ]

    def list_by_approver(self, approver_id: str, status: str = "pending") -> List[dict]:
        """列出待某审批人处理的报销单"""
        return [
            r for r in self._entities.values()
            if r.get("approver_id") == approver_id and (not status or r.get("status") == status)
        ]

    def approve(self, reimbursement_id: str, comment: str = "") -> Optional[dict]:
        """审批通过"""
        return self.update(reimbursement_id, {
            "status": "approved",
            "approver_comment": comment,
            "approved_at": time.time(),
        })

    def reject(self, reimbursement_id: str, comment: str = "") -> Optional[dict]:
        """审批拒绝"""
        return self.update(reimbursement_id, {
            "status": "rejected",
            "approver_comment": comment,
        })

    def pay(self, reimbursement_id: str, operator: str = "") -> Optional[dict]:
        """打款（状态 → reimbursed）"""
        return self.update(reimbursement_id, {
            "status": "reimbursed",
            "paid_at": time.time(),
            "paid_by": operator,
        })


class PolicyDocumentStore(BaseJsonStore):
    """政策文档存储 (用于 RAG 检索)"""
    _id_field = "doc_id"
    _id_prefix = "doc_"

    def search_by_category(self, category: str) -> List[dict]:
        """按分类搜索文档"""
        return [
            d for d in self._entities.values()
            if d.get("is_active", True) and d.get("category") == category
        ]

    def search_by_tags(self, tags: List[str]) -> List[dict]:
        """按标签搜索文档 (OR 语义)"""
        return [
            d for d in self._entities.values()
            if d.get("is_active", True) and any(
                tag in d.get("tags", []) for tag in tags
            )
        ]

    def search_by_keyword(self, keyword: str) -> List[dict]:
        """按关键词搜索文档内容"""
        keyword_lower = keyword.lower()
        results = []
        for d in self._entities.values():
            if not d.get("is_active", True):
                continue
            if (keyword_lower in d.get("title", "").lower() or
                keyword_lower in d.get("content", "").lower()):
                results.append(d)
        return results

    def get_embedding_docs(self) -> List[dict]:
        """获取所有有嵌入向量的文档 (用于向量检索)"""
        return [
            d for d in self._entities.values()
            if d.get("is_active", True) and d.get("embedding")
        ]

    def index_missing_embeddings(self, embedder) -> int:
        """
        为缺失向量的文档建立向量索引（增量）。

        返回新增向量化的文档数量。embedder 不可用时返回 0，
        调用方应回落到关键词检索。
        """
        if not embedder or not embedder.available:
            return 0

        pending = [
            d for d in self._entities.values()
            if d.get("is_active", True) and not d.get("embedding")
        ]
        if not pending:
            return 0

        # 标题 + 正文一起向量化，提升短查询命中率
        texts = [f"{d.get('title', '')}\n{d.get('content', '')}".strip() for d in pending]
        vectors = embedder.embed(texts)
        if len(vectors) != len(pending):
            return 0

        count = 0
        for doc, vector in zip(pending, vectors):
            if not vector:
                continue
            self.update(doc["doc_id"], {
                "embedding": vector,
                "embedding_dim": len(vector),
            })
            count += 1
        return count

    def vector_search(
        self,
        query: str,
        embedder,
        top_k: int = 5,
        category: str = "",
        min_score: float = 0.0,
    ) -> List[dict]:
        """
        向量语义检索（RAG 召回）。

        返回按相似度降序的文档列表，每项附带 score 与原文片段 excerpt
        （保留原文用于回答引用，满足合规可解释性要求）。
        """
        if not query or not embedder or not embedder.available:
            return []

        query_vector = embedder.embed_one(query)
        if not query_vector:
            return []

        candidates = [
            d for d in self._entities.values()
            if d.get("is_active", True)
            and d.get("embedding")
            and (not category or d.get("category") == category)
        ]
        if not candidates:
            return []

        scored = []
        for doc in candidates:
            score = cosine_similarity(query_vector, doc["embedding"])
            if score >= min_score:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, doc in scored[:top_k]:
            item = dict(doc)
            item["score"] = round(score, 4)
            item["excerpt"] = _make_excerpt(doc.get("content", ""))
            item.pop("embedding", None)  # 不在接口响应中回传大向量
            results.append(item)
        return results
