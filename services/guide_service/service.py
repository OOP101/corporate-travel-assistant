"""攻略外接服务 —— 景点/攻略语料 RAG 检索（v3 Agent 可外接服务②，仅个人出游场景召回）

与政策服务同构：服务函数（本文件）+ Agent 工具（tools.py）+ HTTP 路由（router.py）。
语料为 C 端个人出行内容（门票、时长、预约要求、避坑提示），与差旅政策语料分离存储。
"""
import logging
from typing import List, Optional

from shared.embedding import get_embedder
from core.stores import TravelGuideStore

logger = logging.getLogger("guide_service")


class GuideService:
    """攻略服务实例：持有一个 TravelGuideStore（语料库）"""

    def __init__(self, guide_store: TravelGuideStore):
        self.guide_store = guide_store

    @staticmethod
    def _keyword_search(store, query: str, category: str, top_k: int) -> List[dict]:
        """关键词检索：按空白分词任一命中即召回（整串子串匹配会漏「杭州 西湖」）。"""
        docs = store.search_by_keyword(query)
        terms = [t for t in (query or "").split() if t] + [query or ""]
        if len(docs) < top_k:
            seen = {d.get("guide_id") for d in docs}
            partial = []
            for d in store.list_all():
                if d.get("guide_id") in seen or not d.get("is_active", True):
                    continue
                text = (d.get("title", "") + " " + d.get("content", "")).lower()
                if any(t.lower() in text for t in terms):
                    partial.append(d)
            docs.extend(partial)
        if category:
            docs = [d for d in docs if d.get("category") == category]
        return docs[:top_k]

    def search(
        self, query: str, top_k: int = 5, category: str = "", min_score: float = 0.0
    ) -> dict:
        """景点/攻略检索：向量优先，不可用降级关键词；保留原文 excerpt 防编造。"""
        store = self.guide_store
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

    def reindex(self, force: bool = False) -> dict:
        """重建景点语料向量索引。"""
        embedder = get_embedder()
        if not embedder or not embedder.available:
            raise RuntimeError("Embedding 未启用，无法建立向量索引（当前为关键词检索）")
        store = self.guide_store
        if force:
            for doc in store.list_all():
                if doc.get("embedding"):
                    store.update(doc["guide_id"], {"embedding": [], "embedding_dim": 0})
        return {
            "provider": embedder.mode,
            "model": embedder.model_name,
            "dim": embedder.dim,
            "indexed_new": store.index_missing_embeddings(embedder),
            "total_docs": len(store.list_all()),
            "with_embedding": len(store.get_embedding_docs()),
        }
