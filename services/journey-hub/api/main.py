"""
行智 · Journey Hub —— FastAPI 服务入口

AI出行管家 Agent 编排中心。

API:
  POST /agent/chat                → 非流式对话
  POST /agent/chat/stream         → SSE 流式对话
  GET  /agent/sessions            → 活跃会话列表
  POST /agent/session/{id}/clear  → 清除会话
  GET  /metrics                   → Prometheus 指标
  GET  /health                    → 健康检查
"""
import logging
import os
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from shared.llm import LLMManager
from shared.config import settings
from shared.logging_config import setup_logging
from shared.middleware import api_key_auth
from shared.middleware.app_factory import create_app
from shared.metrics import active_sessions
from shared.sse import SSE_DONE, sse_frame, sse_stream_response
from shared.tracing import TraceContext

from state import JourneyHubGraph
from tools import ToolRegistry, ToolHandlers
from memory.session import SessionManager
# 相对导入：api 包名在三个服务中重名，单进程统一网关下按别名加载，故不用绝对包名
from .auth import auth_router, UserStore, resolve_session_id
from .admin import router as admin_router, DEFAULT_MODELS, CONFIG_ID, ConfigStore

logger = logging.getLogger("journey-hub")


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

    # 日志
    setup_logging(
        level=settings.log_level,
        service="journey-hub",
        use_json=settings.log_json,
    )

    # 注册 API Key（来自统一配置，默认 dev key）
    api_key_auth.register_workspace("default", settings.dev_api_key)

    # LLM
    llm = LLMManager()
    llm.register(
        "openai_compatible",
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=0.3,
    )
    # 多模型：腾讯 TokenHub 统一网关（混元 / DeepSeek / 智谱）
    if settings.tencent_maas_api_key and settings.tencent_maas_base_url:
        llm.register(
            "tencent_maas",
            api_key=settings.tencent_maas_api_key,
            base_url=settings.tencent_maas_base_url,
            model="hy-mt2-pro",
            temperature=0.3,
        )
        for _m in ("hy-mt2-pro", "deepseek-v4-flash", "glm-5-turbo"):
            llm.register_model_route(_m, "tencent_maas")
        logger.info("已接入腾讯 TokenHub 多模型网关（hy-mt2-pro / deepseek-v4-flash / glm-5-turbo）")

    # 默认 provider（.env LLM_*）同样按模型名路由，避免未命中时张冠李戴
    if settings.llm_base_url:
        for _m in ("mimo-v2.5", "mimo-v2.5-pro"):
            llm.register_model_route(_m, "openai_compatible")

    # 用户与系统配置存储（登录 / 管理员界面）
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

    # 未显式传 model 时的默认模型：管理员配置优先，.env 兜底。
    # 保证「下拉框默认模型」与「不传参时的实际调用模型」一致（此前两者不一致）。
    llm.default_model = (config_store.get(CONFIG_ID) or {}).get(
        "default_model") or settings.llm_default_model or None

    # 挂到 app.state 供路由访问（登录 / 管理接口 / LLM 热更新）
    app.state.user_store = user_store
    app.state.config_store = config_store
    app.state.llm_manager = llm

    # 工具注册
    tool_handlers = ToolHandlers(
        llm_manager=llm,
        planner_url=settings.planner_service_url,
        sense_url=settings.sense_service_url,
    )

    tool_registry = ToolRegistry()
    tool_registry.register("plan_trip", tool_handlers.plan_trip, "行程规划")
    tool_registry.register("plan_trip_stream", tool_handlers.plan_trip_stream, "行程规划(流式)")
    tool_registry.register("confirm_trip", tool_handlers.confirm_trip, "行程草案确认(落库+审批)")
    tool_registry.register("chat_query", tool_handlers.chat_query, "智能问答")
    tool_registry.register("manage_trip", tool_handlers.manage_trip, "行程管理")
    tool_registry.register("emergency_assist", tool_handlers.emergency_assist, "应急协助")

    # 会话管理
    session_manager = SessionManager(max_history=20)

    # Journey Hub 图
    agent_hub = JourneyHubGraph(
        llm_manager=llm,
        tool_registry=tool_registry,
        session_manager=session_manager,
    )

    logger.info("行智·Journey Hub 已启动")
    yield

    logger.info("行智·Journey Hub 已关闭")


# ---------------------------------------------------------------------------
# FastAPI 应用（使用共享工厂）
# ---------------------------------------------------------------------------
app = create_app(
    title="行智 · Journey Hub",
    description="AI出行管家 Agent 编排中心 —— LangGraph 编排 + 意图路由 + 会话管理",
    lifespan=lifespan,
    tags=[
        {"name": "Agent 对话", "description": "智能对话、流式对话、会话管理"},
        {"name": "系统", "description": "健康检查、Prometheus 指标"},
    ],
)

app.include_router(auth_router)
app.include_router(admin_router)


@app.post("/agent/chat", response_model=ChatResponse, tags=["Agent 对话"])
def agent_chat(req: ChatRequest, request: Request):
    """非流式 Agent 对话

    同步 def 路由：agent_hub.invoke 内部是阻塞的 LLM/HTTP 调用（可达数十秒），
    必须走 FastAPI 线程池执行，否则会卡死事件循环、阻塞包括 /health 在内的所有请求。
    """
    if agent_hub is None:
        raise HTTPException(503, "服务未就绪")

    active_sessions.labels(service="journey-hub").inc()

    session_id = resolve_session_id(request, req.session_id)
    try:
        result = agent_hub.invoke(
            session_id=session_id,
            user_input=req.query,
            model=req.model,
        )
        active_sessions.labels(service="journey-hub").dec()

        return ChatResponse(
            response=result["response"],
            intent=result.get("intent", ""),
            session_id=result.get("session_id", req.session_id),
            status=result.get("status", "ok"),
        )
    except Exception as e:
        active_sessions.labels(service="journey-hub").dec()
        logger.error(f"agent_chat_error: {e}")
        raise HTTPException(500, f"Agent 处理失败: {e}")


@app.post("/agent/chat/stream", tags=["Agent 对话"])
async def agent_chat_stream(req: ChatRequest, request: Request):
    """
    SSE 流式 Agent 对话（真流式）

    发送事件帧：
      event: route       → 正在分析意图
      event: intent      → 意图分类结果
      event: progress    → 生成过程提示（plan 意图：分析/生成中进度，不进正文）
      event: chunk       → 回复文本片段（chat 逐 token；plan 为草案摘要逐段）
      event: clarify     → S2 澄清反问（missing 缺参清单 / params / round，前端渲染选项）
      event: confirm     → S4 方案确认卡（trip 草案未落库 / defaulted 代填项）
      event: trip_saved  → S5 确认完成（trip_id，已落库+审批）
      event: respond     → 完整回复（与 chunk 内容一致，兼容整体替换的前端契约）
      event: error       → 错误
    """
    if agent_hub is None:
        raise HTTPException(503, "服务未就绪")

    active_sessions.labels(service="journey-hub").inc()

    session_id = resolve_session_id(request, req.session_id)

    def generate():
        ctx = TraceContext(session_id=session_id)
        try:
            # 第1帧：正在分析意图
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
            active_sessions.labels(service="journey-hub").dec()

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
    """S4 → S5：确认行程草案（前端确认卡按钮）。

    调 planner POST /trips/confirm 落库 + 政策检查 + 审批发起；
    审批只在用户确认后发生（PRD v2 铁律）。
    """
    if agent_hub is None:
        raise HTTPException(503, "服务未就绪")
    handler = tool_registry.get_handler("confirm_trip") if tool_registry else None
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
    # tool 角色在前端按 assistant 呈现
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


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.journey_host, port=settings.journey_port)
