"""
FastAPI 应用工厂 —— 统一中间件、CORS、健康检查和指标端点

消除三个服务 main.py 中的重复配置代码。
"""
import os
import time
from typing import List, Optional, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from shared.config import settings
from shared.middleware.auth import APIKeyMiddleware, api_key_auth
from shared.metrics import get_metrics_response, http_requests_total, http_request_duration


# 可配置的 CORS 来源（生产环境应设置具体域名）
_CORS_ORIGINS: List[str] = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]

# 统一的 skip paths
_DEFAULT_SKIP_PATHS = ["/health", "/docs", "/openapi.json", "/metrics", "/redoc"]


def create_app(
    title: str,
    description: str,
    version: str = "1.0.0",
    lifespan: Optional[Callable] = None,
    cors_origins: Optional[List[str]] = None,
    skip_auth_paths: Optional[List[str]] = None,
    tags: Optional[List[dict]] = None,
) -> FastAPI:
    """
    创建标准化的 FastAPI 应用实例。

    自动配置:
      - CORS 中间件（修复 allow_origins + allow_credentials 冲突）
      - API Key 鉴权中间件
      - /health 健康检查端点
      - /metrics Prometheus 指标端点
    """
    app = FastAPI(
        title=title,
        description=description,
        version=version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # --- OpenAPI tags ---
    if tags:
        app.title = title
        app.openapi_tags = tags

    # --- CORS ---
    origins = cors_origins or _CORS_ORIGINS
    allow_credentials = origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- API Key 鉴权 ---
    skip_paths = skip_auth_paths or _DEFAULT_SKIP_PATHS
    app.add_middleware(
        APIKeyMiddleware,
        auth=api_key_auth,
        skip_paths=skip_paths,
    )

    # --- HTTP 请求级指标（计数 + 延迟；路径用路由模板，避免参数产生高基数标签）---
    service_label = title

    @app.middleware("http")
    async def http_metrics(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        # /metrics 自身的抓取请求不记，防止指标自我膨胀
        if path != "/metrics":
            status = str(response.status_code)
            http_requests_total.labels(
                service=service_label, method=request.method, path=path, status=status
            ).inc()
            http_request_duration.labels(
                service=service_label, method=request.method, path=path
            ).observe(time.time() - start)
        return response

    # --- 通用端点 ---
    @app.get("/health", tags=["系统"])
    async def health():
        return {"status": "ok", "service": title}

    @app.get("/metrics", tags=["系统"], include_in_schema=False)
    async def metrics():
        body, content_type = get_metrics_response()
        return Response(content=body, media_type=content_type)

    return app
