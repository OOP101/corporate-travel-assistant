"""用户画像 Router —— 偏好画像 / 同行人 (PRD F1.2 / 7.4)"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api import deps

router = APIRouter()


class UpdateProfileRequest(BaseModel):
    budget_daily_range: Optional[list] = Field(default=None, description="每日预算区间 [low, high]")
    travel_style: Optional[str] = Field(default=None, description="出行风格 relaxed|compact|adventure|cultural")
    dietary: Optional[List[str]] = Field(default=None, description="饮食偏好")
    fitness_level: Optional[str] = Field(default=None, description="体力水平 low|normal|high")
    accommodation_pref: Optional[str] = Field(default=None, description="住宿偏好 hotel|hostel|homestay")
    visited_cities: Optional[List[str]] = Field(default=None, description="已去过的城市")
    extra: Optional[dict] = Field(default=None, description="额外偏好字段")


class AddCompanionRequest(BaseModel):
    name: str = Field(..., description="同行人姓名")
    role: str = Field(default="adult", description="角色 adult|child|elder")
    age: int = Field(default=0, description="年龄")
    notes: str = Field(default="", description="备注")


@router.get("/users/me/profile", tags=["用户画像"])
async def get_profile(request: Request, session_id: str = Query(default="", description="会话/用户 ID (兼容)")):
    """获取当前用户偏好画像"""
    user_id = session_id or getattr(request.state, "workspace_id", "default")
    profile = deps.profile_store.get(user_id)
    return {"user_id": user_id, "profile": profile}


@router.put("/users/me/profile", tags=["用户画像"])
async def update_profile(req: UpdateProfileRequest, request: Request, session_id: str = Query(default="")):
    """
    更新偏好画像 (部分更新)。

    仅传入字段会被覆盖，其余字段保留。返回更新后的完整画像。
    """
    user_id = session_id or getattr(request.state, "workspace_id", "default")
    # 仅收集非 None 字段
    partial = {k: v for k, v in req.model_dump().items() if v is not None}
    if not partial:
        raise HTTPException(400, "未提供任何要更新的字段")
    profile = deps.profile_store.update(user_id, partial)
    return {"user_id": user_id, "profile": profile}


@router.get("/users/me/companions", tags=["用户画像"])
async def list_companions(request: Request, session_id: str = Query(default="")):
    """获取同行人列表"""
    user_id = session_id or getattr(request.state, "workspace_id", "default")
    profile = deps.profile_store.get(user_id)
    companions = profile.get("companions", [])
    return {"user_id": user_id, "companions": companions, "count": len(companions)}


@router.post("/users/me/companions", tags=["用户画像"])
async def add_companion(req: AddCompanionRequest, request: Request, session_id: str = Query(default="")):
    """添加同行人"""
    user_id = session_id or getattr(request.state, "workspace_id", "default")
    companion = {
        "name": req.name,
        "role": req.role,
        "age": req.age,
        "notes": req.notes,
    }
    profile = deps.profile_store.add_companion(user_id, companion)
    return {
        "user_id": user_id,
        "companion": companion,
        "companions": profile.get("companions", []),
    }
