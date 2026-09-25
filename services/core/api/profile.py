"""用户档案 API —— 出行偏好画像与常用同行人（「我的档案」页的数据面）

为什么单独成文件：`ProfileStore` 在 `core.main` 的 lifespan 里早已实例化
（`deps.profile_store`），但 v3 切型删路由时把它一起"留成了孤儿" —— 全仓只有赋值、
没有任何读取点，前端 ProfilePage 因此整页 404。本模块按前端既有契约把四个端点补齐。

响应形状对齐前端 `api/planner.js` 的既有约定（**改这里必须同步改前端**）：
    GET  /users/me/profile        → {profile}
    PUT  /users/me/profile        → {profile}   （body 为裸 partial，空提交 400）
    GET  /users/me/companions     → {companions}
    POST /users/me/companions     → {companions}

身份口径与行程一致：Bearer 登录态 > 显式 session_id > API Key 的 workspace 兜底
（保留「不登录也能跑通演示」的路径），统一走 `core.deps.resolve_user_id`。
"""
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import deps

logger = logging.getLogger("core.api.profile")

router = APIRouter()


class CompanionRequest(BaseModel):
    name: str = Field(..., min_length=1, description="同行人姓名")
    role: str = Field(default="adult", description="与本人关系：adult / child / elder")
    age: int = Field(default=0, ge=0, le=120)
    notes: str = Field(default="")


def _store():
    if deps.profile_store is None:
        raise HTTPException(503, "档案存储未就绪")
    return deps.profile_store


@router.get("/users/me/profile", tags=["我的档案"])
async def get_my_profile(
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """读取当前用户偏好画像（不存在时返回字段补全后的默认画像）。"""
    user_id = deps.resolve_user_id(request, session_id)
    return {"profile": _store().get(user_id)}


@router.put("/users/me/profile", tags=["我的档案"])
async def update_my_profile(
    data: dict,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """部分更新偏好画像（空提交 400，避免把一次误触当成"清空全部偏好"）。"""
    if not data:
        raise HTTPException(400, "未提供任何要更新的字段")
    user_id = deps.resolve_user_id(request, session_id)
    try:
        profile = _store().update(user_id, data)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"偏好字段不合法: {e}")
    logger.info(f"profile_updated: {user_id}")
    return {"profile": profile}


@router.get("/users/me/companions", tags=["我的档案"])
async def list_my_companions(
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """常用同行人列表。"""
    user_id = deps.resolve_user_id(request, session_id)
    profile = _store().get(user_id)
    return {"companions": profile.get("companions", [])}


@router.post("/users/me/companions", tags=["我的档案"])
async def add_my_companion(
    req: CompanionRequest,
    request: Request,
    session_id: str = Query(default="", description="调用方身份（未登录时的兜底声明）"),
):
    """新增常用同行人（返回全量列表，前端直接替换渲染）。"""
    user_id = deps.resolve_user_id(request, session_id)
    profile = _store().add_companion(user_id, req.model_dump())
    logger.info(f"companion_added: {user_id} → {req.name}")
    return {"companions": profile.get("companions", [])}
