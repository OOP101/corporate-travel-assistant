"""企业智行 · Agent 内核（v3）—— 单服务 · 单端口 · Agent 原生

v3 架构（从「三层微服务 + 10 个 CRUD 路由」推倒重构）：

    Agent 内核（本服务）
      ├─ LangGraph 意图路由（plan / chat / manage / respond / emergency）
      ├─ 行程生成引擎（场景澄清 · 两阶段输出 · 授权代填）
      ├─ 审批闭环（唯一业务主线：确认门禁 → 政策检查 → 审批 → 生效/作废）
      └─ 会话与鉴权（HMAC 无状态 token · 自助注册）
    工具总线（ToolRegistry）：一切能力皆工具，可插拔、失败降级
    外接服务：政策服务（规则+RAG）· 攻略服务（RAG）· 地图 MCP（感知服务规划中）

启动：python -m uvicorn core.main:app --port 8001（在 services/ 目录下）
"""
import logging
import os
import sys
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

# 进程引导：launcher 以 services/ 为 cwd 启动 uvicorn，这里补齐仓库根到 sys.path（shared 依赖）
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from shared.llm import LLMManager
from shared.embedding import EmbeddingManager, init_embedder
from shared.config import settings
from shared.logging_config import setup_logging
from shared.middleware import api_key_auth
from shared.middleware.app_factory import create_app
from shared.metrics import active_sessions
from shared.sse import SSE_DONE, sse_frame, sse_stream_response
from shared.tracing import TraceContext

from core import deps
from core.stores import (
    TripStore, ProfileStore, TemplateStore, DepartmentStore, EmployeeStore,
    PolicyStore, PolicyDocumentStore, TravelGuideStore, ApprovalStore,
)
from core.generation import ChecklistGenerator, RerouteEngine
from core.archive import SummaryGenerator
from core.agent.graph import JourneyHubGraph
from core.agent.registry import ToolRegistry
from core.agent.handlers import ToolHandlers
from core.memory.session import SessionManager
from core.approval.engine import ApprovalEngine
from core.auth import auth_router, UserStore, resolve_session_id
from core.admin import router as admin_router, DEFAULT_MODELS, CONFIG_ID, ConfigStore
from core.api import trips as trips_api
from core.api import approvals as approvals_api
from policy_service.service import PolicyService
from policy_service import router as policy_router, tools as policy_tools
from guide_service.service import GuideService
from guide_service import router as guide_router

logger = logging.getLogger("core")


# ---------------------------------------------------------------------------
# 全局服务实例
# ---------------------------------------------------------------------------
agent_hub: Optional[JourneyHubGraph] = None
session_manager: Optional[SessionManager] = None
tool_registry: Optional[ToolRegistry] = None


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    query: str = Field(..., description="用户输入")
    session_id: str = Field(default="default")
    model: Optional[str] = Field(default=None, description="LLM 模型名（可选，缺省用 .env 配置）")


class ChatResponse(BaseModel):
    response: str
    intent: str = ""
    session_id: str = ""
    status: str = "ok"


class PlanConfirmRequest(BaseModel):
    session_id: str = Field(default="default")
    trip: dict = Field(..., description="确认的行程草案（SSE confirm 事件帧的 trip 字段）")


# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_hub, session_manager, tool_registry

    setup_logging(
        level=settings.log_level,
        service="core",
        use_json=settings.log_json,
    )

    api_key_auth.register_workspace("default", settings.dev_api_key)

    # ---- LLM 网关 ----
    llm = LLMManager()
    llm.register(
        "openai_compatible",
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    # 腾讯 TokenHub 统一网关（deepseek-v4-flash / kimi-k3 / hy-mt2-pro / hy-mt2-lite）
    if settings.tencent_maas_api_key and settings.tencent_maas_base_url:
        llm.register(
            "tencent_maas",
            api_key=settings.tencent_maas_api_key,
            base_url=settings.tencent_maas_base_url,
            model="deepseek-v4-flash",
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        for _m in ("deepseek-v4-flash", "kimi-k3", "hy-mt2-pro", "hy-mt2-lite"):
            llm.register_model_route(_m, "tencent_maas")
        logger.info("已接入腾讯 TokenHub 多模型网关")

    # ---- 存储（内核资产）----
    deps.trip_store = TripStore(data_dir=settings.trip_data_dir)
    deps.profile_store = ProfileStore(data_dir=settings.profile_data_dir)
    deps.template_store = TemplateStore(data_dir=settings.template_data_dir)
    org_dir = deps.org_data_dir()
    deps.dept_store = DepartmentStore(data_dir=os.path.join(org_dir, "departments"))
    deps.employee_store = EmployeeStore(data_dir=os.path.join(org_dir, "employees"))

    # ---- 生成器 ----
    deps.llm_manager = llm
    deps.checklist_gen = ChecklistGenerator(llm)
    deps.summary_gen = SummaryGenerator(llm)
    deps.reroute_engine = RerouteEngine(llm)

    # ---- Embedding（可插拔三后端：local / api / none，未配置降级关键词）----
    embedder = EmbeddingManager(
        provider=settings.embedding_provider,
        local_model=settings.embedding_model,
        api_base_url=settings.embedding_base_url or settings.llm_base_url,
        api_key=settings.embedding_api_key or settings.llm_api_key,
        api_model=settings.embedding_api_model or settings.embedding_model,
        dim=settings.embedding_dim,
    )
    init_embedder(embedder)

    # ---- 外接服务①：政策（规则 + 文档 RAG）----
    deps.policy_service = PolicyService(
        policy_store=PolicyStore(data_dir=os.path.join(org_dir, "policies")),
        policy_doc_store=PolicyDocumentStore(data_dir=os.path.join(org_dir, "policy_docs")),
    )
    policy_router.service = deps.policy_service

    # ---- 外接服务②：攻略（个人出游语料 RAG）----
    deps.guide_service = GuideService(
        guide_store=TravelGuideStore(data_dir=os.path.join(org_dir, "guide_docs")),
    )
    guide_router.service = deps.guide_service

    # ---- 审批闭环（唯一业务主线）----
    deps.approval_engine = ApprovalEngine(
        trip_store=deps.trip_store,
        approval_store=ApprovalStore(data_dir=os.path.join(org_dir, "approvals")),
        employee_store=deps.employee_store,
        policy_service=deps.policy_service,
    )

    # ---- 工具总线：内核工具 + 外接服务工具 ----
    tool_handlers = ToolHandlers(
        llm_manager=llm,
        trip_store=deps.trip_store,
        approval_engine=deps.approval_engine,
        policy_service=deps.policy_service,
    )
    tool_registry = ToolRegistry()
    tool_registry.register("plan_trip", tool_handlers.plan_trip, "行程规划")
    tool_registry.register("plan_trip_stream", tool_handlers.plan_trip_stream, "行程规划(流式)")
    tool_registry.register("confirm_trip", tool_handlers.confirm_trip, "行程草案确认(落库+审批)")
    tool_registry.register("chat_query", tool_handlers.chat_query, "智能问答")
    tool_registry.register("manage_trip", tool_handlers.manage_trip, "行程管理")
    tool_registry.register("emergency_assist", tool_handlers.emergency_assist, "应急协助")
    policy_tools.register_tools(tool_registry, deps.policy_service)
    guide_router.register_tools(tool_registry, deps.guide_service)

    # ---- 会话与 Agent 图 ----
    session_manager = SessionManager(max_history=20)
    agent_hub = JourneyHubGraph(
        llm_manager=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
    )

    # ---- 用户与系统配置存储（登录 / 管理员界面）----
    system_dir = os.path.join(os.path.dirname(settings.trip_data_dir), "system")
    user_store = UserStore(data_dir=os.path.join(system_dir, "users"))
    if not user_store.get("admin"):
        user_store.create_user("admin", "admin123", role="admin")
        logger.info("已创建种子管理员账号: admin")
    if not user_store.get("web-user"):
        user_store.create_user("web-user", "123456", role="user")

    config_store = ConfigStore(data_dir=os.path.join(system_dir, "config"))
    if not config_store.get(CONFIG_ID):
        config_store.save({
            "config_id": CONFIG_ID,
            "available_models": DEFAULT_MODELS,
            "default_model": settings.llm_model or DEFAULT_MODELS[0]["model_id"],
            "llm_base_url": settings.llm_base_url,
            "llm_api_key": settings.llm_api_key,
        })
    llm.default_model = (config_store.get(CONFIG_ID) or {}).get(
        "default_model") or settings.llm_default_model or None

    app.state.user_store = user_store
    app.state.config_store = config_store
    app.state.llm_manager = llm

    logger.info(
        f"企业智行 · Agent 内核已启动 (LLM={'on' if llm.is_available() else 'off(demo)'}, "
        f"Embedding={embedder.mode}, 工具数={len(tool_registry.list_tool_names())})"
    )
    yield
    logger.info("企业智行 · Agent 内核已关闭")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = create_app(
    title="企业智行 · Agent 内核（v3）",
    description="AI出行管家 Agent 原生架构 —— LangGraph 编排 + 审批闭环 + 外接服务总线",
    lifespan=lifespan,
    tags=[
        {"name": "Agent 对话", "description": "智能对话、流式对话、会话管理"},
        {"name": "行程生成", "description": "自然语言 → 结构化行程（SSE 流式）"},
        {"name": "行程管理", "description": "行程 CRUD、应变重排、出行清单、总结"},
        {"name": "审批管理", "description": "审批闭环流转（唯一业务主线）"},
        {"name": "差旅政策", "description": "外接服务：政策配置与违规检查"},
        {"name": "政策文档", "description": "外接服务：政策文档 RAG 检索"},
        {"name": "景点攻略", "description": "外接服务：个人出游语料 RAG 检索"},
        {"name": "系统", "description": "健康检查、Prometheus 指标"},
    ],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(trips_api.router)
app.include_router(approvals_api.router)
app.include_router(policy_router.router)
app.include_router(guide_router.router)


# ---------------------------------------------------------------------------
# Agent 对话端点
# ---------------------------------------------------------------------------
@app.post("/agent/chat", response_model=ChatResponse, tags=["Agent 对话"])
def agent_chat(req: ChatRequest, request: Request):
    """非流式 Agent 对话

    同步 def 路由：agent_hub.invoke 内部是阻塞的 LLM 调用（可达数十秒），
    必须走 FastAPI 线程池执行，否则会卡死事件循环、阻塞包括 /health 在内的所有请求。
    """
    if agent_hub is None:
        raise HTTPException(503, "服务未就绪")

    active_sessions.labels(service="core").inc()

    session_id = resolve_session_id(request, req.session_id)
    try:
        result = agent_hub.invoke(
            session_id=session_id,
            user_input=req.query,
            model=req.model,
        )
        active_sessions.labels(service="core").dec()

        return ChatResponse(
            response=result["response"],
            intent=result.get("intent", ""),
            session_id=result.get("session_id", req.session_id),
            status=result.get("status", "ok"),
        )
    except Exception as e:
        active_sessions.labels(service="core").dec()
        logger.error(f"agent_chat_error: {e}")
        raise HTTPException(500, f"Agent 处理失败: {e}")


@app.post("/agent/chat/stream", tags=["Agent 对话"])
async def agent_chat_stream(req: ChatRequest, request: Request):
    """
    SSE 流式 Agent 对话（真流式）

    事件帧：
      event: route       → 正在分析意图
      event: intent      → 意图分类结果
      event: progress    → 生成过程提示（plan 意图，不进正文）
      event: chunk       → 回复文本片段（chat 逐 token；plan 为草案摘要逐段）
      event: clarify     → S2 澄清反问（missing 缺参清单 / params / round）
      event: confirm     → S4 方案确认卡（trip 草案未落库 / defaulted 代填项）
      event: trip_saved  → S5 确认完成（trip_id，已落库+审批）
      event: respond     → 完整回复（兼容整体替换的前端契约）
      event: error       → 错误
    """
    if agent_hub is None:
        raise HTTPException(503, "服务未就绪")

    active_sessions.labels(service="core").inc()

    session_id = resolve_session_id(request, req.session_id)

    def generate():
        ctx = TraceContext(session_id=session_id)
        try:
            yield sse_frame({"event": "route", "content": "正在分析意图..."})

            final_response = ""
            for evt in agent_hub.invoke_stream(
                session_id=session_id,
                user_input=req.query,
                model=req.model,
            ):
                if evt.get("event") == "chunk":
                    final_response += evt.get("content", "")
                elif evt.get("event") == "respond":
                    final_response = evt.get("content", final_response)
                yield sse_frame(evt)

            yield SSE_DONE
            ctx.log()

        except Exception as e:
            logger.error(f"agent_chat_stream_error: {e}")
            yield sse_frame({"event": "error", "content": str(e)})
        finally:
            active_sessions.labels(service="core").dec()

    return sse_stream_response(generate())


@app.get("/agent/sessions", tags=["Agent 对话"])
async def list_sessions():
    """活跃会话列表（调试用）"""
    if not session_manager:
        return {"sessions": [], "count": 0}
    sessions = session_manager.list_sessions()
    return {"sessions": sessions, "count": len(sessions)}


@app.post("/agent/plan/confirm", tags=["Agent 对话"])
def agent_plan_confirm(req: PlanConfirmRequest, request: Request):
    """S4 → S5：确认行程草案（前端确认卡按钮；审批只在用户确认后发生）"""
    if agent_hub is None or tool_registry is None:
        raise HTTPException(503, "服务未就绪")
    handler = tool_registry.get_handler("confirm_trip")
    if handler is None:
        raise HTTPException(503, "确认服务未就绪")
    result = handler(session_id=resolve_session_id(request, req.session_id), trip=req.trip)
    if not result.get("success"):
        raise HTTPException(502, result.get("message", "行程确认失败"))
    return result


@app.get("/agent/session/{session_id}/history", tags=["Agent 对话"])
async def session_history(session_id: str, last_n: int = Query(20, ge=1, le=100)):
    """读取会话历史（供前端切换菜单/刷新后恢复对话上下文）"""
    if not session_manager:
        return {"session_id": session_id, "messages": [], "count": 0}
    msgs = session_manager.get_history(session_id, last_n=last_n)
    for m in msgs:
        if m.get("role") == "tool":
            m["role"] = "assistant"
    return {"session_id": session_id, "messages": msgs, "count": len(msgs)}


@app.post("/agent/session/{session_id}/clear", tags=["Agent 对话"])
async def clear_session(session_id: str):
    """清除会话"""
    if session_manager:
        session_manager.clear(session_id)
    if agent_hub:
        agent_hub.sessions.clear(session_id)
    return {"status": "ok", "session_id": session_id}


@app.get("/agent/tools", tags=["Agent 对话"])
async def list_tools():
    """工具总线清单：Agent 当前可插拔的全部能力（外接服务自检用）"""
    if not tool_registry:
        return {"tools": [], "count": 0}
    tools = [{"name": n, "description": d} for n, d in tool_registry.list_tools()]
    return {"tools": tools, "count": len(tools)}


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("GATEWAY_PORT", "8001")))
