"""景点攻略 Router —— 景点/攻略语料管理 + RAG 检索（C 端个人出行）

与「政策文档」共用 shared 层的 DocumentCorpusStore，接口形态保持一致：
管理 CRUD + 语义检索（embedding 不可用时降级关键词）+ 重建索引。

区别仅在语料语义：本通道面向个人出游，为行程生成提供景点门票、建议游玩
时长、预约要求、避坑提示等真实内容，避免生成结果只有日程没有内容依据。
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from shared.embedding import get_embedder

from .. import deps

router = APIRouter()


class CreateGuideRequest(BaseModel):
    title: str = Field(..., description="景点/攻略标题")
    content: str = Field(..., description="攻略内容")
    category: str = Field(default="attraction", description="分类（attraction/food/transport/tips…）")
    tags: List[str] = Field(default_factory=list, description="标签（建议含城市名，便于关键词召回）")
    source: str = Field(default="", description="来源")


class UpdateGuideRequest(BaseModel):
    title: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)
    source: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


class GuideSearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询（城市名 / 景点名 / 玩法）")
    category: str = Field(default="", description="分类过滤")
    top_k: int = Field(default=5, ge=1, le=50, description="返回条数")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="最低相似度阈值")


def _keyword_search(query: str, category: str, top_k: int) -> List[dict]:
    """关键词检索（向量不可用时的降级路径）"""
    docs = deps.guide_store.search_by_keyword(query)
    if category:
        docs = [d for d in docs if d.get("category") == category]
    return docs[:top_k]


def _store():
    if deps.guide_store is None:
        raise HTTPException(503, "景点语料存储未初始化")
    return deps.guide_store


@router.get("/guides", tags=["景点攻略"])
async def list_guides(
    category: str = Query(default="", description="分类"),
    keyword: str = Query(default="", description="搜索关键词"),
):
    """景点/攻略语料列表"""
    store = _store()
    if keyword:
        docs = store.search_by_keyword(keyword)
    elif category:
        docs = store.search_by_category(category)
    else:
        docs = store.list_all()
    for d in docs:
        d.pop("embedding", None)
    return {"documents": docs, "count": len(docs)}


@router.post("/guides", tags=["景点攻略"])
async def create_guide(req: CreateGuideRequest):
    """新增景点/攻略语料"""
    store = _store()
    doc = {
        "title": req.title,
        "content": req.content,
        "category": req.category,
        "tags": req.tags,
        "source": req.source,
    }
    guide_id = store.save(doc)

    # 入库即建立向量索引（embedding 可用时；不可用则留给关键词检索）
    embedder = get_embedder()
    if embedder and embedder.available:
        store.index_missing_embeddings(embedder)

    saved = store.get(guide_id) or {}
    saved.pop("embedding", None)
    return {"status": "ok", "guide_id": guide_id, "document": saved}


# 必须在 /guides/{guide_id} 之前注册（否则 search/reindex 被路径参数吞掉）
@router.post("/guides/search", tags=["景点攻略"])
async def search_guides(req: GuideSearchRequest):
    """
    景点/攻略检索（RAG 召回）

    优先走向量语义检索；embedding 不可用时自动降级为关键词检索。
    结果保留原文 excerpt 供 LLM 引用，避免编造门票与预约信息。
    """
    store = _store()
    embedder = get_embedder()
    mode = "keyword"

    if embedder and embedder.available:
        store.index_missing_embeddings(embedder)
        docs = store.vector_search(
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


@router.post("/guides/reindex", tags=["景点攻略"])
async def reindex_guides(force: bool = Query(default=False, description="强制清空并重建全部向量")):
    """重建景点语料向量索引"""
    store = _store()
    embedder = get_embedder()
    if not embedder or not embedder.available:
        raise HTTPException(503, "Embedding 未启用，无法建立向量索引（当前为关键词检索）")

    if force:
        for doc in store.list_all():
            if doc.get("embedding"):
                store.update(doc["guide_id"], {"embedding": [], "embedding_dim": 0})

    indexed = store.index_missing_embeddings(embedder)
    return {
        "status": "ok",
        "provider": embedder.mode,
        "model": embedder.model_name,
        "dim": embedder.dim,
        "indexed_new": indexed,
        "total_docs": len(store.list_all()),
        "with_embedding": len(store.get_embedding_docs()),
    }


@router.get("/guides/{guide_id}", tags=["景点攻略"])
async def get_guide(guide_id: str):
    """景点/攻略语料详情"""
    doc = _store().get(guide_id)
    if not doc:
        raise HTTPException(404, f"语料不存在: {guide_id}")
    doc.pop("embedding", None)
    return doc


@router.put("/guides/{guide_id}", tags=["景点攻略"])
async def update_guide(guide_id: str, req: UpdateGuideRequest):
    """更新景点/攻略语料"""
    store = _store()
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")

    # 正文相关字段变更 → 作废旧向量，下次检索时自动重建
    if any(k in partial for k in ("title", "content", "tags")):
        partial["embedding"] = []
        partial["embedding_dim"] = 0

    updated = store.update(guide_id, partial)
    if not updated:
        raise HTTPException(404, f"语料不存在: {guide_id}")

    if isinstance(updated, dict):
        updated.pop("embedding", None)
    return updated


@router.delete("/guides/{guide_id}", tags=["景点攻略"])
async def delete_guide(guide_id: str):
    """删除景点/攻略语料"""
    deleted = _store().delete(guide_id)
    if not deleted:
        raise HTTPException(404, f"语料不存在: {guide_id}")
    return {"status": "ok", "guide_id": guide_id}
