"""
统一 API 响应模型 —— 标准化成功/错误响应格式

前端可依赖固定的响应结构处理数据。
"""
from typing import Any, Optional, List
from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    """统一成功响应包装"""
    status: str = Field(default="ok", description="ok | error")
    data: Any = Field(default=None, description="业务数据")
    message: str = Field(default="", description="提示信息")


class PaginatedResponse(BaseModel):
    """分页响应"""
    status: str = "ok"
    data: Any = Field(default=None)
    total: int = 0
    page: int = 1
    page_size: int = 20


class ErrorResponse(BaseModel):
    """统一错误响应"""
    status: str = "error"
    error: str = Field(..., description="错误类型")
    detail: str = Field(default="", description="错误详情")


def ok(data: Any = None, message: str = "") -> dict:
    """快速构造成功响应"""
    return {"status": "ok", "data": data, "message": message}


def error(error: str, detail: str = "") -> dict:
    """快速构造错误响应"""
    return {"status": "error", "error": error, "detail": detail}
