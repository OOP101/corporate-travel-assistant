"""攻略外接服务 —— Agent 工具出口 + HTTP 路由（合一文件：接口面小）

HTTP：/guides CRUD · /guides/search · /guides/reindex
工具：guide_search（个人出游语料召回，供问答/生成引用）
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.agent.registry import ToolResult
from shared.embedding import get_embedder
from .service import GuideService

router = APIRouter()

# 由 core.main lifespan 注入
service: Optional[GuideService] = None


def _svc() -> GuideService:
    if service is None:
        raise HTTPException(503, "攻略服务未就绪")
    return service


# ---------------------------------------------------------------------------
# Agent 工具出口
# ---------------------------------------------------------------------------
def register_tools(registry, svc: GuideService):
    """把攻略检索注册为 Agent 工具"""

    def guide_search(query: str, top_k: int = 3) -> ToolResult:
        """景点攻略召回：返回原文摘录（门票/时长/预约/避坑），仅个人出游使用"""
        if not (query or "").strip():
            return ToolResult(data="请提供要检索的景点或玩法。", success=False)
        res = svc.search(query, top_k=top_k)
        docs = res.get("documents") or []
        if not docs:
            return ToolResult(data=f"攻略语料中未找到与「{query}」相关的内容。", success=False)
        lines = [f"检索模式：{res.get('mode')}"]
        for d in docs:
            excerpt = d.get("excerpt") or (d.get("content") or "")[:120]
            lines.append(f"《{d.get('title', '攻略')}》{excerpt}")
        return ToolResult(data="\n".join(lines))

    registry.register(
        "guide_search", guide_search,
        "景点攻略检索（RAG，仅个人出游场景引用，避免编造门票与预约信息）",
    )


# ---------------------------------------------------------------------------
# HTTP 路由
# ---------------------------------------------------------------------------
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


@router.get("/guides", tags=["景点攻略"])
async def list_guides(
    category: str = Query(default="", description="分类"),
    keyword: str = Query(default="", description="搜索关键词"),
):
    """景点/攻略语料列表"""
    svc = _svc()
    store = svc.guide_store
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
    svc = _svc()
    guide_id = svc.guide_store.save(req.model_dump())

    embedder = get_embedder()
    if embedder and embedder.available:
        svc.guide_store.index_missing_embeddings(embedder)

    saved = svc.guide_store.get(guide_id) or {}
    saved.pop("embedding", None)
    return {"status": "ok", "guide_id": guide_id, "document": saved}


# 必须在 /guides/{guide_id} 之前注册（否则 search/reindex 被路径参数吞掉）
@router.post("/guides/search", tags=["景点攻略"])
async def search_guides(req: GuideSearchRequest):
    """景点/攻略检索（RAG 召回）"""
    return _svc().search(req.query, top_k=req.top_k, category=req.category, min_score=req.min_score)


@router.post("/guides/reindex", tags=["景点攻略"])
async def reindex_guides(force: bool = Query(default=False, description="强制清空并重建全部向量")):
    """重建景点语料向量索引"""
    try:
        return {"status": "ok", **_svc().reindex(force=force)}
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.get("/guides/{guide_id}", tags=["景点攻略"])
async def get_guide(guide_id: str):
    """景点/攻略语料详情"""
    doc = _svc().guide_store.get(guide_id)
    if not doc:
        raise HTTPException(404, f"语料不存在: {guide_id}")
    doc.pop("embedding", None)
    return doc


@router.put("/guides/{guide_id}", tags=["景点攻略"])
async def update_guide(guide_id: str, req: UpdateGuideRequest):
    """更新景点/攻略语料"""
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")
    if any(k in partial for k in ("title", "content", "tags")):
        partial["embedding"] = []
        partial["embedding_dim"] = 0
    updated = _svc().guide_store.update(guide_id, partial)
    if not updated:
        raise HTTPException(404, f"语料不存在: {guide_id}")
    if isinstance(updated, dict):
        updated.pop("embedding", None)
    return updated


@router.delete("/guides/{guide_id}", tags=["景点攻略"])
async def delete_guide(guide_id: str):
    """删除景点/攻略语料"""
    deleted = _svc().guide_store.delete(guide_id)
    if not deleted:
        raise HTTPException(404, f"语料不存在: {guide_id}")
    return {"status": "ok", "guide_id": guide_id}
