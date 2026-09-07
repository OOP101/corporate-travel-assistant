"""
API Key 鉴权中间件 (shared 模块)
"""
import os
import secrets
from typing import Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class APIKeyAuth:
    """极简 API Key 鉴权"""

    def __init__(self):
        self._keys: dict = {}
        # 开发后门（ak_dev_local / ak_test_* 前缀、?api_key= 查询参数）仅在
        # 非生产环境生效；生产部署必须设置 APP_ENV=production 关闭
        self._dev_backdoor: bool = os.getenv("APP_ENV", "dev").lower() != "production"

    def register_workspace(self, workspace_id: str, api_key: str = None) -> str:
        key = api_key or f"ak_{secrets.token_hex(16)}"
        self._keys[key] = workspace_id
        return key

    def validate(self, api_key: str) -> Optional[str]:
        if api_key in self._keys:
            return self._keys[api_key]
        if self._dev_backdoor and (api_key.startswith("ak_test_") or api_key == "ak_dev_local"):
            return "default"
        return None

    def get_workspace(self, request: Request) -> str:
        api_key = (
            request.headers.get("X-API-Key") or
            request.headers.get("Authorization", "").replace("Bearer ", "") or
            # query 传 key 会泄入访问日志，仅开发环境允许
            (request.query_params.get("api_key", "") if self._dev_backdoor else "")
        )
        if not api_key:
            raise HTTPException(401, "Missing API Key (X-API-Key header)")
        workspace = self.validate(api_key)
        if workspace is None:
            raise HTTPException(403, "Invalid API Key")
        return workspace


class APIKeyMiddleware(BaseHTTPMiddleware):
    """FastAPI 中间件：自动提取 workspace_id 并注入 request.state"""

    def __init__(self, app, auth: APIKeyAuth, skip_paths: list = None):
        super().__init__(app)
        self.auth = auth
        self.skip_paths = skip_paths or ["/health", "/docs", "/openapi.json", "/metrics"]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self.skip_paths):
            return await call_next(request)

        try:
            workspace = self.auth.get_workspace(request)
            request.state.workspace_id = workspace
        except HTTPException as e:
            return JSONResponse(
                status_code=e.status_code,
                content={"error": e.detail, "detail": "请提供有效的 X-API-Key"},
            )

        return await call_next(request)


api_key_auth = APIKeyAuth()
