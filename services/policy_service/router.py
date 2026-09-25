"""政策外接服务 —— HTTP 路由（前端 / 集成直连；Agent 走 tools.py）

覆盖：/policies CRUD · /policies/match · /policy-docs CRUD · /search · /reindex
注意：/policies/check 依赖行程数据，归核心 API（core.api.trips）持有，不在本路由。
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from shared.embedding import get_embedder
from .service import PolicyService

router = APIRouter()

# 由 core.main lifespan 注入（避免 router ↔ main 循环导入）
service: Optional[PolicyService] = None


def _svc() -> PolicyService:
    if service is None:
        raise HTTPException(503, "政策服务未就绪")
    return service


# ---------------------------------------------------------------------------
# 差旅政策规则 CRUD
# ---------------------------------------------------------------------------
class CreatePolicyRequest(BaseModel):
    name: str = Field(..., description="政策名称")
    description: str = Field(default="", description="政策描述")
    level: str = Field(default="", description="适用职级")
    city_tier: str = Field(default="all", description="适用城市等级")
    flight_class: str = Field(default="economy", description="舱位标准")
    train_class: str = Field(default="second", description="火车座位标准")
    hotel_limit: float = Field(default=0, description="酒店每晚上限")
    meal_limit: float = Field(default=0, description="餐饮每日上限")
    transport_limit: float = Field(default=0, description="市内交通每日上限")
    daily_subsidy: float = Field(default=0, description="每日补贴")
    requires_approval: bool = Field(default=True, description="是否需要审批")
    approval_threshold: float = Field(default=0, description="审批金额阈值")


class UpdatePolicyRequest(BaseModel):
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    level: Optional[str] = Field(default=None)
    city_tier: Optional[str] = Field(default=None)
    flight_class: Optional[str] = Field(default=None)
    train_class: Optional[str] = Field(default=None)
    hotel_limit: Optional[float] = Field(default=None)
    meal_limit: Optional[float] = Field(default=None)
    transport_limit: Optional[float] = Field(default=None)
    daily_subsidy: Optional[float] = Field(default=None)
    requires_approval: Optional[bool] = Field(default=None)
    approval_threshold: Optional[float] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


@router.get("/policies", tags=["差旅政策"])
async def list_policies(level: str = Query(default="", description="职级")):
    """差旅政策列表"""
    svc = _svc()
    policies = svc.policy_store.get_by_level(level) if level else svc.policy_store.list_all()
    return {"policies": policies, "count": len(policies)}


@router.post("/policies", tags=["差旅政策"])
async def create_policy(req: CreatePolicyRequest):
    """创建差旅政策"""
    svc = _svc()
    policy = req.model_dump()
    policy_id = svc.policy_store.save(policy)
    return {"status": "ok", "policy_id": policy_id, "policy": svc.policy_store.get(policy_id)}


# --- 以下两条必须在 /policies/{policy_id} 之前注册 ---
@router.get("/policies/match", tags=["差旅政策"])
async def match_policy(
    level: str = Query(..., description="员工职级"),
    city_tier: str = Query(default="all", description="城市等级"),
):
    """匹配差旅政策"""
    svc = _svc()
    policy = svc.match_policy(level, city_tier)
    if not policy:
        raise HTTPException(404, f"未找到匹配的政策: level={level}, city_tier={city_tier}")
    return {"policy": policy}


@router.get("/policies/{policy_id}", tags=["差旅政策"])
async def get_policy(policy_id: str):
    """政策详情"""
    policy = _svc().policy_store.get(policy_id)
    if not policy:
        raise HTTPException(404, f"政策不存在: {policy_id}")
    return policy


@router.put("/policies/{policy_id}", tags=["差旅政策"])
async def update_policy(policy_id: str, req: UpdatePolicyRequest):
    """更新差旅政策"""
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")
    updated = _svc().policy_store.update(policy_id, partial)
    if not updated:
        raise HTTPException(404, f"政策不存在: {policy_id}")
    return updated


@router.delete("/policies/{policy_id}", tags=["差旅政策"])
async def delete_policy(policy_id: str):
    """删除差旅政策"""
    deleted = _svc().policy_store.delete(policy_id)
    if not deleted:
        raise HTTPException(404, f"政策不存在: {policy_id}")
    return {"status": "ok", "policy_id": policy_id}


# ---------------------------------------------------------------------------
# 政策文档（RAG 语料）CRUD + 检索 + 重建索引
# ---------------------------------------------------------------------------
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


@router.get("/policy-docs", tags=["政策文档"])
async def list_policy_docs(
    category: str = Query(default="", description="分类"),
    keyword: str = Query(default="", description="搜索关键词"),
):
    """政策文档列表"""
    svc = _svc()
    store = svc.policy_doc_store
    if keyword:
        docs = store.search_by_keyword(keyword)
    elif category:
        docs = store.search_by_category(category)
    else:
        docs = store.list_all()
    for d in docs:
        d.pop("embedding", None)  # 不向前端回传大向量
    return {"documents": docs, "count": len(docs)}


@router.post("/policy-docs", tags=["政策文档"])
async def create_policy_doc(req: CreatePolicyDocRequest):
    """创建政策文档（入库即建向量索引，embedding 可用时）"""
    svc = _svc()
    doc = req.model_dump()
    doc_id = svc.policy_doc_store.save(doc)

    embedder = get_embedder()
    if embedder and embedder.available:
        svc.policy_doc_store.index_missing_embeddings(embedder)

    saved = svc.policy_doc_store.get(doc_id) or {}
    saved.pop("embedding", None)
    return {"status": "ok", "doc_id": doc_id, "document": saved}


# 必须在 /policy-docs/{doc_id} 之前注册（否则 search/reindex 被路径参数吞掉）
@router.post("/policy-docs/search", tags=["政策文档"])
async def search_policy_docs(req: PolicyDocSearchRequest):
    """政策文档检索（RAG 召回；向量不可用自动降级关键词，保留原文摘录可解释）"""
    return _svc().search_docs(req.query, top_k=req.top_k, category=req.category, min_score=req.min_score)


@router.post("/policy-docs/reindex", tags=["政策文档"])
async def reindex_policy_docs(force: bool = Query(default=False, description="强制清空并重建全部向量")):
    """重建政策文档向量索引"""
    try:
        return {"status": "ok", **_svc().reindex_docs(force=force)}
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.get("/policy-docs/{doc_id}", tags=["政策文档"])
async def get_policy_doc(doc_id: str):
    """政策文档详情"""
    doc = _svc().policy_doc_store.get(doc_id)
    if not doc:
        raise HTTPException(404, f"文档不存在: {doc_id}")
    doc.pop("embedding", None)
    return doc


@router.put("/policy-docs/{doc_id}", tags=["政策文档"])
async def update_policy_doc(doc_id: str, req: UpdatePolicyDocRequest):
    """更新政策文档（正文变更作废旧向量，检索时自动重建）"""
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")
    if any(k in partial for k in ("title", "content", "tags")):
        partial["embedding"] = []
        partial["embedding_dim"] = 0
    updated = _svc().policy_doc_store.update(doc_id, partial)
    if not updated:
        raise HTTPException(404, f"文档不存在: {doc_id}")
    if isinstance(updated, dict):
        updated.pop("embedding", None)
    return updated


@router.delete("/policy-docs/{doc_id}", tags=["政策文档"])
async def delete_policy_doc(doc_id: str):
    """删除政策文档"""
    deleted = _svc().policy_doc_store.delete(doc_id)
    if not deleted:
        raise HTTPException(404, f"文档不存在: {doc_id}")
    return {"status": "ok", "doc_id": doc_id}
