"""
LangGraph StateGraph —— 行智 · Journey Hub 核心编排器

节点：
  route   → 意图分类（plan | chat | manage）
  plan    → 调用规划工具 (plan_trip)
  chat    → 调用问答工具 (chat_query)
  manage  → 调用管理工具 (manage_trip)
  respond → 生成最终回复

流程：
  USER → route → [plan→respond] [chat→respond] [manage→respond]
"""
import logging
from typing import Literal, Dict, Any, Generator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from router.intent import IntentRouter, Intent
from router.preflight import PreflightChecker
from tools.registry import ToolRegistry
from tools.handlers import TRAVEL_ASSISTANT_SYSTEM_PROMPT
from memory.session import SessionManager
from shared.tracing import TraceContext, traced
from shared.metrics import node_duration, agent_request_duration, tool_call_counter

logger = logging.getLogger("journey-hub")


AgentState = Dict[str, Any]


class JourneyHubGraph:
    """
    Journey Hub 有状态工作流

    用法:
        hub = JourneyHubGraph(llm_manager=llm, tool_registry=registry)
        result = hub.invoke(session_id="abc123", user_input="帮我规划北京三日游")
    """

    def __init__(
        self,
        llm_manager,
        tool_registry: ToolRegistry,
        session_manager: SessionManager = None,
    ):
        self.llm = llm_manager
        self.tools = tool_registry
        self.sessions = session_manager or SessionManager()
        self.preflight = PreflightChecker(llm_manager)

        self.graph = self._build_graph()

    # ------------------------------------------------------------------
    # 构建图
    # ------------------------------------------------------------------
    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 工作流"""
        workflow = StateGraph(AgentState)

        workflow.add_node("route", self._route_intent)
        workflow.add_node("preflight", self._preflight_check)
        workflow.add_node("plan", self._execute_plan)
        workflow.add_node("chat", self._execute_chat)
        workflow.add_node("manage", self._execute_manage)
        workflow.add_node("emergency", self._execute_emergency)
        workflow.add_node("respond", self._generate_response)

        workflow.set_entry_point("route")

        workflow.add_conditional_edges(
            "route",
            self._decide_after_route,
            {
                "plan": "preflight",
                "chat": "chat",
                "manage": "manage",
                "emergency": "emergency",
            },
        )

        workflow.add_conditional_edges(
            "preflight",
            self._decide_after_preflight,
            {
                "plan": "plan",
                "respond": "respond",
            },
        )

        workflow.add_edge("plan", "respond")
        workflow.add_edge("chat", "respond")
        workflow.add_edge("manage", "respond")
        workflow.add_edge("emergency", "respond")
        workflow.add_edge("respond", END)

        self.checkpointer = MemorySaver()
        return workflow.compile(checkpointer=self.checkpointer)

    # ------------------------------------------------------------------
    # 节点：意图分类
    # ------------------------------------------------------------------
    def _route_intent(self, state: AgentState) -> AgentState:
        """意图分类节点"""
        with node_duration.labels(service="journey-hub", node="route").time():
            user_input = state.get("user_input", "")
            ctx = TraceContext(session_id=state.get("session_id", ""))

            with traced(ctx, "route_intent"):
                router = IntentRouter()
                intent = router.classify(user_input)
                state["intent"] = intent.value

                logger.info("intent_classified", extra={
                    "session_id": state.get("session_id"),
                    "input": user_input[:50],
                    "intent": intent.value,
                })

        return state

    def _decide_after_route(self, state: AgentState) -> Literal["plan", "chat", "manage", "emergency"]:
        """路由决策：返回意图名（与 add_conditional_edges 的映射 key 一致）"""
        intent = state.get("intent", "chat")
        if intent == "plan":
            return "plan"
        if intent == "manage":
            return "manage"
        if intent == "emergency":
            return "emergency"
        return "chat"

    # ------------------------------------------------------------------
    # 节点：前置校验
    # ------------------------------------------------------------------
    def _preflight_check(self, state: AgentState) -> AgentState:
        """规划前置校验：检查关键信息是否齐全"""
        with node_duration.labels(service="journey-hub", node="preflight").time():
            user_input = state.get("user_input", "")
            ctx = TraceContext(session_id=state.get("session_id", ""))

            with traced(ctx, "preflight_check"):
                followup = self.preflight.check(user_input, state.get("session_id", ""))
                if followup:
                    # 信息不全，设置追问回复，跳过规划
                    state["tool_result"] = followup
                    state["tool_success"] = True
                    state["preflight_followup"] = True
                    logger.info("preflight_missing_info", extra={
                        "session_id": state.get("session_id"),
                        "input": user_input[:50],
                    })
                else:
                    state["preflight_followup"] = False

        return state

    def _decide_after_preflight(self, state: AgentState) -> Literal["plan", "respond"]:
        """前置校验后决策：信息齐全则规划，否则直接回复追问"""
        if state.get("preflight_followup"):
            return "respond"
        return "plan"

    # ------------------------------------------------------------------
    # 节点：行程规划
    # ------------------------------------------------------------------
    def _execute_plan(self, state: AgentState) -> AgentState:
        """行程规划工具调用节点"""
        with node_duration.labels(service="journey-hub", node="plan").time():
            user_input = state.get("user_input", "")
            ctx = TraceContext(session_id=state.get("session_id", ""))

            with traced(ctx, "execute_plan"):
                self._run_tool("plan_trip", state, user_input)

        return state

    # ------------------------------------------------------------------
    # 节点：智能问答
    # ------------------------------------------------------------------
    def _execute_chat(self, state: AgentState) -> AgentState:
        """智能问答工具调用节点"""
        with node_duration.labels(service="journey-hub", node="chat").time():
            user_input = state.get("user_input", "")
            ctx = TraceContext(session_id=state.get("session_id", ""))

            with traced(ctx, "execute_chat"):
                # 注入会话上下文
                state["context_prompt"] = self.sessions.get_context_prompt(
                    state.get("session_id", "")
                )
                self._run_tool("chat_query", state, user_input)

        return state

    # ------------------------------------------------------------------
    # 节点：行程管理
    # ------------------------------------------------------------------
    def _execute_manage(self, state: AgentState) -> AgentState:
        """行程管理工具调用节点"""
        with node_duration.labels(service="journey-hub", node="manage").time():
            user_input = state.get("user_input", "")
            ctx = TraceContext(session_id=state.get("session_id", ""))

            with traced(ctx, "execute_manage"):
                self._run_tool("manage_trip", state, user_input)

        return state

    # ------------------------------------------------------------------
    # 节点：应急协助
    # ------------------------------------------------------------------
    def _execute_emergency(self, state: AgentState) -> AgentState:
        """应急协助工具调用节点"""
        with node_duration.labels(service="journey-hub", node="emergency").time():
            user_input = state.get("user_input", "")
            ctx = TraceContext(session_id=state.get("session_id", ""))

            with traced(ctx, "execute_emergency"):
                self._run_tool("emergency_assist", state, user_input)

        return state

    # ------------------------------------------------------------------
    # 节点：生成回复
    # ------------------------------------------------------------------
    def _generate_response(self, state: AgentState) -> AgentState:
        """生成最终回复"""
        with node_duration.labels(service="journey-hub", node="respond").time():
            ctx = TraceContext(session_id=state.get("session_id", ""))

            with traced(ctx, "generate_response"):
                # 工具结果已设则保留，否则用 LLM 兜底生成
                if state.get("tool_result"):
                    response = state["tool_result"]
                elif state.get("response"):
                    response = state["response"]
                else:
                    response = self._llm_fallback_response(state)

                state["response"] = response
                state["status"] = "completed"

            ctx.log()
        return state

    # ------------------------------------------------------------------
    # 流式调用入口
    # ------------------------------------------------------------------
    def invoke_stream(
        self, session_id: str, user_input: str, model: str = None
    ) -> Generator[Dict[str, str], None, None]:
        """
        流式调用：chat 意图逐 chunk 流式输出 LLM 回复，其余意图走完整图后整段返回。

        Yields 事件帧:
            {"event": "intent", "content": <intent>}
            {"event": "progress", "content": <生成过程提示>}   （plan 意图阶段提示）
            {"event": "chunk",  "content": <文本片段>}   （chat 逐 token / plan 逐段摘要）
            {"event": "respond", "content": <完整回复>}  （兼容前端整体替换契约）
        """
        intent = IntentRouter().classify(user_input)
        yield {"event": "intent", "content": intent.value}

        # chat 意图且 LLM 可用 → 真流式（与 chat_query 相同的 prompt 组装）
        if (
            intent == Intent.CHAT
            and self.llm
            and self.llm.is_available()
        ):
            context = self.sessions.get_context_prompt(session_id)
            messages = [{"role": "system", "content": TRAVEL_ASSISTANT_SYSTEM_PROMPT}]
            if context:
                messages.append({"role": "system", "content": context})
            # 政策类问题注入知识库原文依据（与 chat_query 的 RAG 补充一致）
            chat_handler = self.tools.get_handler("chat_query")
            if chat_handler is not None and hasattr(chat_handler, "_policy_context"):
                policy_ctx = chat_handler._policy_context(user_input)
                if policy_ctx:
                    messages.append({"role": "system", "content": policy_ctx})
            messages.append({"role": "user", "content": user_input})

            full = ""
            try:
                for chunk in self.llm.chat_stream(messages, temperature=0.5, model=model):
                    full += chunk
                    yield {"event": "chunk", "content": chunk}
            except Exception as e:
                logger.warning(f"流式问答失败，降级整段回复: {e}")
                if not full:
                    full = "抱歉，我暂时无法回答，请稍后重试。"
                    yield {"event": "chunk", "content": full}

            self.sessions.append(session_id, "user", user_input)
            self.sessions.append(session_id, "assistant", full)
            yield {"event": "respond", "content": full}
            return

        # plan 意图 → 流式透传规划进度、行程摘要与政策/审批结果
        if intent == Intent.PLAN:
            handler = self.tools.get_handler("plan_trip_stream") or self.tools.get_handler("plan_trip")
            full = ""
            if handler is not None:
                try:
                    for frame in handler(
                        query=user_input, session_id=session_id, state={"model": model}
                    ):
                        # 结构化帧：progress → 生成过程提示；text/str → 进入正文流
                        if isinstance(frame, dict) and frame.get("kind") == "progress":
                            yield {"event": "progress", "content": frame.get("content", "")}
                        else:
                            content = frame.get("content", "") if isinstance(frame, dict) else str(frame)
                            full += content
                            yield {"event": "chunk", "content": content}
                except Exception as e:
                    logger.warning(f"流式行程规划失败: {e}")
            if not full:
                full = "行程规划服务暂时不可用，请稍后重试。"
                yield {"event": "chunk", "content": full}
            self.sessions.append(session_id, "user", user_input)
            self.sessions.append(session_id, "assistant", full)
            yield {"event": "respond", "content": full}
            return

        # manage / emergency / chat 兜底 → 复用完整图
        result = self.invoke(session_id=session_id, user_input=user_input, model=model)
        yield {"event": "respond", "content": result.get("response", "")}

    # ------------------------------------------------------------------
    # 同步调用入口
    # ------------------------------------------------------------------
    def invoke(self, session_id: str, user_input: str, model: str = None) -> Dict[str, Any]:
        """
        同步调用（非流式）

        Args:
            session_id: 会话 ID
            user_input: 用户输入
            model: LLM 模型名（可选，缺省用服务端配置）

        Returns:
            {"response": str, "intent": str, "status": str, "session_id": str}
        """
        with agent_request_duration.labels(service="journey-hub", intent="sync").time():
            config = {"configurable": {"thread_id": session_id}}

            initial_state = {
                "session_id": session_id,
                "user_input": user_input,
                "intent": "",
                "tool_result": "",
                "tool_success": False,
                "response": "",
                "model": model,
            }

            result = self.graph.invoke(initial_state, config)

            # 写入会话历史
            self.sessions.append(session_id, "user", user_input)
            self.sessions.append(session_id, "assistant", result.get("response", ""))

            return {
                "response": result.get("response", ""),
                "intent": result.get("intent", ""),
                "status": result.get("status", "ok"),
                "session_id": session_id,
            }

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _run_tool(self, tool_name: str, state: AgentState, user_input: str):
        """执行工具并写入状态，同时记录指标"""
        try:
            result = self.tools.execute(
                tool_name=tool_name,
                query=user_input,
                session_id=state.get("session_id", ""),
                state=state,
            )
            state["tool_result"] = result.get("data", "")
            state["tool_success"] = result.get("success", False)
            state["tool_name"] = tool_name

            tool_call_counter.labels(
                tool=tool_name,
                status="success" if state["tool_success"] else "failed",
            ).inc()

            logger.info("tool_executed", extra={
                "session_id": state.get("session_id"),
                "tool": tool_name,
                "success": state["tool_success"],
            })
        except Exception as e:
            state["tool_result"] = f"工具调用失败: {e}"
            state["tool_success"] = False
            state["tool_name"] = tool_name
            tool_call_counter.labels(tool=tool_name, status="failed").inc()
            logger.error(f"tool_failed: {e}")

    def _llm_fallback_response(self, state: AgentState) -> str:
        """工具无结果时用 LLM 兜底生成回复，LLM 不可用时返回默认提示"""
        user_input = state.get("user_input", "")
        if self.llm and self.llm.is_available():
            try:
                messages = [
                    {"role": "system", "content": "你是行智·AI出行管家，请友好地回答用户的旅行问题。"},
                    {"role": "user", "content": user_input},
                ]
                return self.llm.chat(messages, temperature=0.5)
            except Exception as e:
                logger.warning(f"LLM 兜底回复失败: {e}")
        return "收到，我暂时无法处理该请求，请稍后重试或换个方式描述您的需求。"
