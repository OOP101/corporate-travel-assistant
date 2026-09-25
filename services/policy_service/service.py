"""政策外接服务 —— 差旅政策规则检查 + 政策文档 RAG 检索（v3 Agent 可外接服务①）

v3 定位：政策不再是「拆分出来的 CRUD 模块」，而是 Agent 可插拔的外接服务：
  - 服务函数（本文件）   → 供审批闭环 / 行程管线进程内调用
  - Agent 工具（tools.py）→ 经工具总线注册，chat/plan 可直接调用
  - HTTP 路由（router.py）→ 供前端 / 集成直连

依赖方向：政策服务只依赖 shared 与自身存储；核心（core）调用本服务，
本服务绝不反向 import core（含审批闭环在内的调用方把 employee 数据传进来）。
"""
import logging
from typing import List, Optional

from shared.embedding import get_embedder
from core.stores import PolicyStore, PolicyDocumentStore

logger = logging.getLogger("policy_service")

# 免做企业差旅政策检查的场景（个人出游为 C 端场景，与差旅政策无关）
POLICY_EXEMPT_SCENES = {"personal"}


class PolicyService:
    """政策服务实例：持有一个 PolicyStore（规则）与一个 PolicyDocumentStore（RAG 语料）"""

    def __init__(self, policy_store: PolicyStore, policy_doc_store: PolicyDocumentStore):
        self.policy_store = policy_store
        self.policy_doc_store = policy_doc_store

    # ------------------------------------------------------------------
    # 规则匹配与违规检查
    # ------------------------------------------------------------------
    def match_policy(self, level: str = "", city_tier: str = "all") -> Optional[dict]:
        """按职级匹配差旅政策（解析不到员工时按通用政策）"""
        return self.policy_store.get_best_match(level or "", city_tier)

    def check_violations(self, trip: dict, policy: dict) -> list:
        return self.policy_store.check_violations(trip, policy)

    def exempt_reason(self, trip: dict, employee: Optional[dict]) -> str:
        """是否免做政策检查与审批；返回免检原因，空串表示需要检查。

        两类豁免（延续 v2 语义）：
        1. 个人出游场景 —— 与「企业差旅政策」无关；
        2. 无员工档案的用户 —— 没有职级可匹配，套用通用政策没有意义。
        """
        scene = str((trip or {}).get("scene") or "").strip().lower()
        if scene in POLICY_EXEMPT_SCENES:
            return f"场景「{scene}」为个人出游，不适用企业差旅政策"
        if not employee:
            return "无员工档案，无可匹配的职级政策"
        return ""

    def preview_trip(self, trip: dict, employee: Optional[dict]) -> dict:
        """政策预检（S4 确认页预警用）——只检查不审批（审批绝不先于用户确认）。"""
        exempt = self.exempt_reason(trip, employee)
        if exempt:
            logger.info(f"跳过政策预检：{exempt}")
            return {}
        policy = self.match_policy((employee or {}).get("level", ""))
        if not policy:
            return {}
        try:
            violations = self.check_violations(trip, policy)
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

    def confirm_check(self, trip: dict, employee: Optional[dict]) -> tuple:
        """确认后（S5）的政策检查：返回 (policy, violations)。"""
        policy = self.match_policy((employee or {}).get("level", ""))
        if not policy:
            return None, []
        return policy, self.check_violations(trip, policy)

    # ------------------------------------------------------------------
    # 政策文档 RAG 检索（问答引用 / Agent 工具共用）
    # ------------------------------------------------------------------
    @staticmethod
    def _keyword_search(store, query: str, category: str, top_k: int) -> List[dict]:
        """关键词检索（向量不可用时的降级路径）。

        v3 改进：查询按空白分词后任一词命中即召回（v2 是整串子串匹配，
        「住宿 上限」这类自然查询会因空格而漏召回），全词优先、部分词殿后。
        """
        docs = store.search_by_keyword(query)
        terms = [t for t in (query or "").split() if t] + [query or ""]
        if len(docs) < top_k:
            seen = {d.get("doc_id") for d in docs}
            partial = []
            for d in store.list_all():
                if d.get("doc_id") in seen or not d.get("is_active", True):
                    continue
                text = (d.get("title", "") + " " + d.get("content", "")).lower()
                if any(t.lower() in text for t in terms):
                    partial.append(d)
            docs.extend(partial)
        if category:
            docs = [d for d in docs if d.get("category") == category]
        return docs[:top_k]

    def search_docs(
        self, query: str, top_k: int = 5, category: str = "", min_score: float = 0.0
    ) -> dict:
        """政策文档检索：优先向量语义，embedding 不可用自动降级关键词。

        结果保留原文 excerpt 供 LLM 引用作答（合规可解释）。
        """
        store = self.policy_doc_store
        embedder = get_embedder()
        mode = "keyword"
        if embedder and embedder.available:
            store.index_missing_embeddings(embedder)
            docs = store.vector_search(
                query, embedder=embedder, top_k=top_k,
                category=category, min_score=min_score,
            )
            if docs:
                mode = "vector"
            else:
                docs = self._keyword_search(store, query, category, top_k)
        else:
            docs = self._keyword_search(store, query, category, top_k)

        return {
            "documents": docs,
            "count": len(docs),
            "query": query,
            "mode": mode,
            "embedding_provider": embedder.mode if embedder else "none",
        }

    def reindex_docs(self, force: bool = False) -> dict:
        """重建政策文档向量索引（embedding 不可用时抛 RuntimeError）。"""
        embedder = get_embedder()
        if not embedder or not embedder.available:
            raise RuntimeError("Embedding 未启用，无法建立向量索引（当前为关键词检索）")
        store = self.policy_doc_store
        if force:
            for doc in store.list_all():
                if doc.get("embedding"):
                    store.update(doc["doc_id"], {"embedding": [], "embedding_dim": 0})
        return {
            "provider": embedder.mode,
            "model": embedder.model_name,
            "dim": embedder.dim,
            "indexed_new": store.index_missing_embeddings(embedder),
            "total_docs": len(store.list_all()),
            "with_embedding": len(store.get_embedding_docs()),
        }
