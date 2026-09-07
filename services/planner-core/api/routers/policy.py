"""差旅政策 Router —— 政策配置 / 匹配 / 违规检查 (P1 企业化)

注意：/policies/match 与 /policies/check 必须定义在 /policies/{policy_id} 之前，
否则会被路径参数路由吞掉（此前 main.py 中的存量 bug，拆分时已修复）。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api import deps

router = APIRouter()


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
    if level:
        policies = deps.policy_store.get_by_level(level)
    else:
        policies = deps.policy_store.list_all()
    return {"policies": policies, "count": len(policies)}


@router.post("/policies", tags=["差旅政策"])
async def create_policy(req: CreatePolicyRequest):
    """创建差旅政策"""
    policy = {
        "name": req.name,
        "description": req.description,
        "level": req.level,
        "city_tier": req.city_tier,
        "flight_class": req.flight_class,
        "train_class": req.train_class,
        "hotel_limit": req.hotel_limit,
        "meal_limit": req.meal_limit,
        "transport_limit": req.transport_limit,
        "daily_subsidy": req.daily_subsidy,
        "requires_approval": req.requires_approval,
        "approval_threshold": req.approval_threshold,
    }
    policy_id = deps.policy_store.save(policy)
    return {"status": "ok", "policy_id": policy_id, "policy": deps.policy_store.get(policy_id)}


# --- 以下两条必须在 /policies/{policy_id} 之前注册 ---
@router.get("/policies/match", tags=["差旅政策"])
async def match_policy(
    level: str = Query(..., description="员工职级"),
    city_tier: str = Query(default="all", description="城市等级"),
):
    """匹配差旅政策"""
    policy = deps.policy_store.get_best_match(level, city_tier)
    if not policy:
        raise HTTPException(404, f"未找到匹配的政策: level={level}, city_tier={city_tier}")
    return {"policy": policy}


@router.post("/policies/check", tags=["差旅政策"])
async def check_policy_violations(trip_id: str, policy_id: str):
    """检查行程政策违规"""
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")

    policy = deps.policy_store.get(policy_id)
    if not policy:
        raise HTTPException(404, f"政策不存在: {policy_id}")

    violations = deps.policy_store.check_violations(trip, policy)
    return {
        "trip_id": trip_id,
        "policy_id": policy_id,
        "violations": violations,
        "has_violations": len(violations) > 0,
    }


@router.get("/policies/{policy_id}", tags=["差旅政策"])
async def get_policy(policy_id: str):
    """政策详情"""
    policy = deps.policy_store.get(policy_id)
    if not policy:
        raise HTTPException(404, f"政策不存在: {policy_id}")
    return policy


@router.put("/policies/{policy_id}", tags=["差旅政策"])
async def update_policy(policy_id: str, req: UpdatePolicyRequest):
    """更新差旅政策"""
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")
    updated = deps.policy_store.update(policy_id, partial)
    if not updated:
        raise HTTPException(404, f"政策不存在: {policy_id}")
    return updated


@router.delete("/policies/{policy_id}", tags=["差旅政策"])
async def delete_policy(policy_id: str):
    """删除差旅政策"""
    deleted = deps.policy_store.delete(policy_id)
    if not deleted:
        raise HTTPException(404, f"政策不存在: {policy_id}")
    return {"status": "ok", "policy_id": policy_id}
