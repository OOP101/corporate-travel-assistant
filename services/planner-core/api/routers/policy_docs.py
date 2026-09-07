"""政策文档 Router —— 文档管理 + RAG 检索 (P1 企业化)"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from shared.embedding import get_embedder

from api import deps

router = APIRouter()


class CreatePolicyDocRequest(BaseModel):
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容")
    category: str = Field(default="general", description="分类")
    tags: List[str] = Field(default_factory=list, description="标签")
    source: str = Field(default="", description="来源")


class UpdatePolicyDocRequest(BaseModel):
    title: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)
    source: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


class PolicyDocSearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询")
    category: str = Field(default="", description="分类过滤")
    top_k: int = Field(default=5, ge=1, le=50, description="返回条数")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="最低相似度阈值")


def _keyword_search(query: str, category: str, top_k: int) -> List[dict]:
    """关键词检索（向量不可用时的降级路径）"""
    docs = deps.policy_doc_store.search_by_keyword(query)
    if category:
        docs = [d for d in docs if d.get("category") == category]
    return docs[:top_k]


@router.get("/policy-docs", tags=["政策文档"])
async def list_policy_docs(
    category: str = Query(default="", description="分类"),
    keyword: str = Query(default="", description="搜索关键词"),
):
    """政策文档列表"""
    if keyword:
        docs = deps.policy_doc_store.search_by_keyword(keyword)
    elif category:
        docs = deps.policy_doc_store.search_by_category(category)
    else:
        docs = deps.policy_doc_store.list_all()
    for d in docs:
        d.pop("embedding", None)  # 不向前端回传大向量
    return {"documents": docs, "count": len(docs)}


@router.post("/policy-docs", tags=["政策文档"])
async def create_policy_doc(req: CreatePolicyDocRequest):
    """创建政策文档"""
    doc = {
        "title": req.title,
        "content": req.content,
        "category": req.category,
        "tags": req.tags,
        "source": req.source,
    }
    doc_id = deps.policy_doc_store.save(doc)

    # 入库即建立向量索引（embedding 可用时；不可用则留给关键词检索）
    embedder = get_embedder()
    if embedder and embedder.available:
        deps.policy_doc_store.index_missing_embeddings(embedder)

    saved = deps.policy_doc_store.get(doc_id) or {}
    saved.pop("embedding", None)  # 不向前端回传大向量
    return {"status": "ok", "doc_id": doc_id, "document": saved}


# 必须在 /policy-docs/{doc_id} 之前注册（否则 search/reindex 被路径参数吞掉）
@router.post("/policy-docs/search", tags=["政策文档"])
async def search_policy_docs(req: PolicyDocSearchRequest):
    """
    政策文档检索（RAG 召回）

    优先走向量语义检索；embedding 不可用时自动降级为关键词检索。
    结果保留原文 excerpt，供 LLM 引用作答，满足合规可解释性。
    """
    embedder = get_embedder()
    mode = "keyword"

    if embedder and embedder.available:
        # 新入库文档无需人工重建索引，查询时增量补齐
        deps.policy_doc_store.index_missing_embeddings(embedder)
        docs = deps.policy_doc_store.vector_search(
            req.query,
            embedder=embedder,
            top_k=req.top_k,
            category=req.category,
            min_score=req.min_score,
        )
        if docs:
            mode = "vector"
        else:
            docs = _keyword_search(req.query, req.category, req.top_k)
    else:
        docs = _keyword_search(req.query, req.category, req.top_k)

    return {
        "documents": docs,
        "count": len(docs),
        "query": req.query,
        "mode": mode,
        "embedding_provider": embedder.mode if embedder else "none",
    }


@router.post("/policy-docs/reindex", tags=["政策文档"])
async def reindex_policy_docs(force: bool = Query(default=False, description="强制清空并重建全部向量")):
    """重建政策文档向量索引"""
    embedder = get_embedder()
    if not embedder or not embedder.available:
        raise HTTPException(503, "Embedding 未启用，无法建立向量索引（当前为关键词检索）")

    if force:
        for doc in deps.policy_doc_store.list_all():
            if doc.get("embedding"):
                deps.policy_doc_store.update(doc["doc_id"], {"embedding": [], "embedding_dim": 0})

    indexed = deps.policy_doc_store.index_missing_embeddings(embedder)
    return {
        "status": "ok",
        "provider": embedder.mode,
        "model": embedder.model_name,
        "dim": embedder.dim,
        "indexed_new": indexed,
        "total_docs": len(deps.policy_doc_store.list_all()),
        "with_embedding": len(deps.policy_doc_store.get_embedding_docs()),
    }


@router.get("/policy-docs/{doc_id}", tags=["政策文档"])
async def get_policy_doc(doc_id: str):
    """政策文档详情"""
    doc = deps.policy_doc_store.get(doc_id)
    if not doc:
        raise HTTPException(404, f"文档不存在: {doc_id}")
    doc.pop("embedding", None)
    return doc


@router.put("/policy-docs/{doc_id}", tags=["政策文档"])
async def update_policy_doc(doc_id: str, req: UpdatePolicyDocRequest):
    """更新政策文档"""
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")

    # 正文相关字段变更 → 作废旧向量，下次检索时自动重建
    if any(k in partial for k in ("title", "content", "tags")):
        partial["embedding"] = []
        partial["embedding_dim"] = 0

    updated = deps.policy_doc_store.update(doc_id, partial)
    if not updated:
        raise HTTPException(404, f"文档不存在: {doc_id}")

    if isinstance(updated, dict):
        updated.pop("embedding", None)
    return updated


@router.delete("/policy-docs/{doc_id}", tags=["政策文档"])
async def delete_policy_doc(doc_id: str):
    """删除政策文档"""
    deleted = deps.policy_doc_store.delete(doc_id)
    if not deleted:
        raise HTTPException(404, f"文档不存在: {doc_id}")
    return {"status": "ok", "doc_id": doc_id}
