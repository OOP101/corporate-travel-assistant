"""文档语料存储基类 —— shared 公共层

把「带向量索引的文档语料」通用能力（关键词检索 / 增量建索引 / 语义检索）
从具体业务存储里抽出来，下游只需声明主键字段即可：

    class PolicyDocumentStore(DocumentCorpusStore):      # 企业差旅政策文档
        _id_field = "doc_id"
        _id_prefix = "doc_"

    class TravelGuideStore(DocumentCorpusStore):         # C 端景点 / 攻略语料
        _id_field = "guide_id"
        _id_prefix = "gd_"

两套语料字段结构一致（title / content / category / tags），检索语义也一致，
所以实现只应有一份。embedding 不可用时全部自动降级为关键词检索，
调用方从返回的 mode 字段即可判断当前处于哪条路径。
"""
from __future__ import annotations

import logging
from typing import List

from shared.embedding import cosine_similarity
from shared.store.base_store import BaseJsonStore

logger = logging.getLogger("shared.store.document")


def make_excerpt(content: str, limit: int = 120) -> str:
    """截取原文片段，用于检索结果的可解释性引用"""
    text = " ".join((content or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


class DocumentCorpusStore(BaseJsonStore):
    """带向量索引的文档语料存储（关键词 + 语义双路检索）"""

    # ------------------------------------------------------------------
    # 检索：关键词路（embedding 不可用时的降级路径）
    # ------------------------------------------------------------------
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
        """按关键词搜索文档标题与正文"""
        keyword_lower = keyword.lower()
        results = []
        for d in self._entities.values():
            if not d.get("is_active", True):
                continue
            if (keyword_lower in d.get("title", "").lower() or
                    keyword_lower in d.get("content", "").lower()):
                results.append(d)
        return results

    # ------------------------------------------------------------------
    # 索引：向量路
    # ------------------------------------------------------------------
    def get_embedding_docs(self) -> List[dict]:
        """获取所有已建立嵌入向量的文档"""
        return [
            d for d in self._entities.values()
            if d.get("is_active", True) and d.get("embedding")
        ]

    def index_missing_embeddings(self, embedder) -> int:
        """为缺失向量的文档增量建立索引，返回本次新增数量。

        embedder 不可用时返回 0，调用方应回落到关键词检索。
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
            self.update(doc[self._id_field], {
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
        """语义检索（RAG 召回）。

        返回按相似度降序的文档列表，每项附带 score 与原文片段 excerpt
        （保留原文用于回答引用，满足可解释性要求）。
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
            item["excerpt"] = make_excerpt(doc.get("content", ""))
            item.pop("embedding", None)      # 不在接口响应中回传大向量
            results.append(item)
        return results
