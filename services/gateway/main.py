# -*- coding: utf-8 -*-
"""
企业智行 · 统一网关（单体模式）—— 单进程 · 单端口 · 一个总控台

把三个后端服务装配进**同一个进程**，对外只暴露一个端口（默认 8001）：

    /            → 行智 Journey Hub   （Agent 编排 / 对话 / 登录 / 管理）
    /planner/*   → 策程 Planner Core  （行程生成 / 组织 / 政策 / 审批 / 报销 / 报表）
    /sense/*     → 感知 Sense Engine  （监控订阅 / 实时直查）

设计要点：
  1. **不复制业务代码**：三个服务的 FastAPI app 原样加载，路由、中间件、lifespan 全部保留；
     微服务模式（`launcher.py start micro`，3 端口）与单服务调试仍然可用。
  2. **同进程别名加载**：三个服务都有顶层 `api` 包，直接 import 会互相覆盖，
     这里以 jh_api / pc_api / se_api 为别名包加载（服务内部已改为相对导入）。
  3. **lifespan 组合**：用 AsyncExitStack 按依赖顺序（journey → planner → sense）
     依次进入三个服务的 lifespan，关闭时逆序退出；journey 的 `app.state` 同步一份到网关，
     保证路由里 `request.app.state` 取得到登录/配置实例。
  4. 服务内部互调仍走 HTTP（PLANNER_SERVICE_URL=http://127.0.0.1:8001/planner），
     编排逻辑零改动，便于随时切回微服务模式。
"""
import importlib.util
import logging
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from shared.middleware.app_factory import create_app

BASE_DIR = Path(__file__).resolve().parents[2]
SERVICES_DIR = BASE_DIR / "services"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

logger = logging.getLogger("gateway")

# 网关端口（与 journey 原端口一致，前端代理无需改端口）
GATEWAY_PORT = int(__import__("os").getenv("GATEWAY_PORT", "8001"))


# ---------------------------------------------------------------------------
# 按别名加载各服务的 FastAPI app
# ---------------------------------------------------------------------------
def _load_service_app(alias: str, service: str) -> FastAPI:
    """把 services/<service>/api 作为独立包 <alias> 加载，返回其 FastAPI app。

    这样三个同名顶层 `api` 包可以在同一进程内共存；服务内部使用相对导入
    （from .auth import ...），因此加载即生效，无需改动业务代码。
    """
    service_dir = SERVICES_DIR / service
    api_dir = service_dir / "api"
    if not api_dir.exists():
        raise RuntimeError(f"服务目录不存在: {api_dir}")
    if str(service_dir) not in sys.path:
        # 各服务的其他顶层模块（state/tools/generators/store/alerts/...）名字不冲突
        sys.path.insert(0, str(service_dir))

    pkg_spec = importlib.util.spec_from_file_location(
        alias, api_dir / "__init__.py", submodule_search_locations=[str(api_dir)]
    )
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules[alias] = pkg
    pkg_spec.loader.exec_module(pkg)

    main_spec = importlib.util.spec_from_file_location(f"{alias}.main", api_dir / "main.py")
    main_mod = importlib.util.module_from_spec(main_spec)
    sys.modules[f"{alias}.main"] = main_mod
    main_spec.loader.exec_module(main_mod)
    return main_mod.app


# 加载顺序即依赖顺序（journey 编排 planner / sense）
journey_app = _load_service_app("jh_api", "journey-hub")
planner_app = _load_service_app("pc_api", "planner-core")
sense_app = _load_service_app("se_api", "sense-engine")


# ---------------------------------------------------------------------------
# 组合生命周期：三个服务的 lifespan 依次进入、逆序退出
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        # journey 的 lifespan 会把 user_store / config_store / llm_manager 挂到 app.state，
        # 其路由通过 request.app.state 读取，因此要挂在 journey_app 上；
        # 同时复制一份到网关 app，保证从网关层直接调试时也能取到。
        await stack.enter_async_context(journey_app.router.lifespan_context(journey_app))
        for _attr in ("user_store", "config_store", "llm_manager"):
            _v = getattr(journey_app.state, _attr, None)
            if _v is not None:
                setattr(app.state, _attr, _v)

        await stack.enter_async_context(planner_app.router.lifespan_context(planner_app))
        await stack.enter_async_context(sense_app.router.lifespan_context(sense_app))

        logger.info(
            "统一网关已就绪 [单体模式]: journey-hub + planner-core + sense-engine "
            f"装配于单进程单端口 {GATEWAY_PORT}"
        )
        yield
    logger.info("统一网关已关闭")


# ---------------------------------------------------------------------------
# 网关应用：先挂细分前缀，最后以 journey 兜底根路径
# ---------------------------------------------------------------------------
app = create_app(
    title="企业智行 · 统一网关",
    description=(
        "单体模式统一入口：单进程单端口承载 行智(Journey Hub) / 策程(Planner Core) / "
        "感知(Sense Engine)。各服务文档：/planner/docs、/sense/docs、/docs"
    ),
    lifespan=lifespan,
    # 子服务文档与健康检查同样免鉴权（与各自独立运行时的白名单保持一致）
    skip_auth_paths=[
        "/health", "/docs", "/openapi.json", "/metrics", "/redoc",
        "/planner/health", "/planner/docs", "/planner/openapi.json",
        "/sense/health", "/sense/docs", "/sense/openapi.json",
    ],
    tags=[
        {"name": "系统", "description": "健康检查、Prometheus 指标、服务索引"},
    ],
)


@app.get("/", tags=["系统"], include_in_schema=False)
async def service_index():
    """网关服务索引：一眼看清三条业务线挂在哪个前缀。"""
    return {
        "service": "企业智行 · 统一网关",
        "mode": "single-process",
        "port": GATEWAY_PORT,
        "services": {
            "journey-hub": {"prefix": "/", "docs": "/docs", "desc": "Agent 编排 · 对话 · 登录 · 管理"},
            "planner-core": {"prefix": "/planner", "docs": "/planner/docs", "desc": "行程生成 · 组织 · 政策 · 审批 · 报销 · 报表"},
            "sense-engine": {"prefix": "/sense", "docs": "/sense/docs", "desc": "监控订阅 · 实时直查"},
        },
    }


# 路由匹配按注册顺序：/planner、/sense 优先，其余路径落到 journey（含 /agent /auth /admin）
app.mount("/planner", planner_app)
app.mount("/sense", sense_app)
app.mount("/", journey_app)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("GATEWAY_HOST", "127.0.0.1"),
        port=GATEWAY_PORT,
        reload=False,
    )
