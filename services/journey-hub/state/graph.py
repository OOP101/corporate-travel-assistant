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

v2 行程规划对话流（PRD 行程规划对话流程-v2）：
  plan 意图按会话阶段四态流转（阶段存于 SessionManager metadata plan_stage）：
    ""       → 首轮：planner 抽参 → 缺参发 clarify（进入 clarify 阶段）/ 信息齐发 draft（进入 confirm 阶段）
    clarify  → 用户补充答案直通规划（合并后重新抽参）
    confirm  → 用户「确认」→ confirm_trip 落库+审批；「取消」→ 终止；其他 → 视为修改重新生成
"""
import logging
import re
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

# 同一行程最多澄清轮数（PRD §6.3：最多 2 轮反问，第 3 轮仍未补齐 → 引导手动创建）。
# 此前 clarify_count 只被塞进 clarify 帧当 round 展示、从不拦截，于是
# 「缺参 → 点『你看着办，按常见差旅默认补全』→ 还是缺参 → 再问一遍」形成死循环。
MAX_CLARIFY_ROUNDS = 2

# 澄清缺参 → 中文名（澄清上限提示用）
_CLARIFY_LABELS = {
    "scene": "出行场景",
    "destination": "目的地",
    "start_date": "出发日期",
    "days": "天数",
}


def _build_clarify_exhausted(missing: list, params: dict) -> str:
    """澄清轮次用尽话术（PRD §6.3）：告知还缺哪几项 + 引导手动创建。

    目的地没有可用的代填规则，所以缺它时必须终止追问而不是继续反问——
    否则用户每点一次授权入口都会原样重问一遍。
    """
    labels = [_CLARIFY_LABELS.get(m, m) for m in (missing or [])] or ["关键信息"]
    dest = (params or {}).get("destination") or ""
    return (
        f"我已经问了两轮，{'去' + dest + '的' if dest else '这趟'}行程还差"
        f"「{'、'.join(labels)}」没确定，这部分我不能凭空替你编。\n"
        "可以直接回我一句（例如「下周一去深圳出差 3 天」），"
        "也可以到「差旅行程」页手动填写后生成。"
    )


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
            {"event": "clarify", "missing": [...], "params": {...}} （S2 澄清反问，前端渲染选项）
            {"event": "confirm", "trip": {...}, "defaulted": [...]} （S4 方案确认卡，草案未落库）
            {"event": "trip_saved", "trip_id": ..., "trip": {...},
             "origin"/"destination"/"start_date"/"end_date",
             "attractions": [...], "weather": [...], "transport": {...}}  （S5 确认完成，已落库）
            {"event": "respond", "content": <完整回复>}  （兼容前端整体替换契约）
        """
        # v2 阶段路由：clarify 阶段的用户输入是澄清答案，直通规划；
        # confirm 阶段按「确认 / 取消 / 修改」分流
        stage = self.sessions.get_metadata(session_id, "plan_stage") or ""

        if stage == "confirm":
            text = (user_input or "").strip()
            if re.search(r"确认|确定|同意|提交|ok", text, re.I) and len(text) <= 12:
                yield {"event": "intent", "content": "plan"}
                async_result = self._confirm_pending_draft(session_id)
                yield from async_result
                return
            if re.search(r"取消|不确认|先不|算了|不要了", text) and len(text) <= 12:
                yield {"event": "intent", "content": "plan"}
                self.sessions.set_metadata(session_id, "plan_stage", "")
                self.sessions.set_metadata(session_id, "pending_draft", None)
                full = "好的，已取消本次行程方案，草案未提交、未落库。需要重新规划时随时告诉我。"
                yield {"event": "chunk", "content": full}
                self.sessions.append(session_id, "user", user_input)
                self.sessions.append(session_id, "assistant", full)
                yield {"event": "respond", "content": full}
                return
            # 其他输入视为修改参数 → 清阶段，走重新生成
            self.sessions.set_metadata(session_id, "plan_stage", "")

        intent = IntentRouter().classify(user_input)
        if stage == "clarify":
            # 澄清答案（如「商务出差 9/7 到 9/9」）按规划意图处理
            intent = Intent.PLAN
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
            # 地图类问题注入腾讯地图 MCP 实查依据（与 chat_query 一致，失败静默）
            if chat_handler is not None and hasattr(chat_handler, "_map_mcp_context"):
                map_ctx = chat_handler._map_mcp_context(user_input)
                if map_ctx:
                    messages.append({"role": "system", "content": map_ctx})
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

        # plan 意图 → 流式透传规划进度、草案摘要与澄清/确认结构化帧
        if intent == Intent.PLAN:
            handler = self.tools.get_handler("plan_trip_stream") or self.tools.get_handler("plan_trip")
            # 本轮之前的澄清轮次计数，用于执行 PRD §6.3 的「同一行程最多 2 轮」上限
            clarify_rounds = self.sessions.get_metadata(session_id, "clarify_count", 0) or 0
            full = ""
            if handler is not None:
                try:
                    for frame in handler(
                        query=user_input, session_id=session_id,
                        state={
                            "model": model,
                            # 澄清轮次续用：上轮已抽取参数随请求透传，避免多轮上下文丢失
                            "plan_carry": self.sessions.get_metadata(session_id, "plan_carry") or {},
                        },
                    ):
                        if not isinstance(frame, dict):
                            full += str(frame)
                            yield {"event": "chunk", "content": str(frame)}
                            continue
                        kind = frame.get("kind")
                        if kind == "progress":
                            yield {"event": "progress", "content": frame.get("content", "")}
                        elif kind == "clarify":
                            missing = frame.get("missing") or []
                            params_now = frame.get("params") or {}
                            new_round = clarify_rounds + 1
                            if new_round > MAX_CLARIFY_ROUNDS:
                                # PRD §6.3 上限：不再反问，改告知缺项 + 引导手动创建。
                                # 阶段与计数都保持不动：后续同类输入稳定复现这句终止提示，
                                # 不会退回「问一遍」——那正是用户点了 5 次的原死循环。
                                # carry 仍要更新：授权代填补上的日期/天数得记住，
                                # 用户补上目的地后即可直接出草案（不必重头再问一遍）。
                                self.sessions.set_metadata(session_id, "plan_carry", params_now)
                                terminal = _build_clarify_exhausted(missing, params_now)
                                full += terminal
                                yield {"event": "chunk", "content": terminal}
                            else:
                                # S2 澄清：记录阶段与已抽参数（下轮 carry 续用），前端渲染可点选项
                                self.sessions.set_metadata(session_id, "plan_stage", "clarify")
                                self.sessions.set_metadata(session_id, "plan_carry", params_now)
                                self.sessions.set_metadata(session_id, "clarify_count", new_round)
                                content = frame.get("content", "")
                                full += content
                                yield {
                                    "event": "clarify",
                                    "content": content,
                                    "missing": missing,
                                    "params": params_now,
                                    "round": new_round,
                                }
                                yield {"event": "chunk", "content": content}
                        elif kind == "draft":
                            # S3 草案：挂起待确认（未落库未审批），进入 confirm 阶段，carry 用毕清除
                            trip = frame.get("trip") or {}
                            self.sessions.set_metadata(session_id, "plan_stage", "confirm")
                            self.sessions.set_metadata(session_id, "pending_draft", trip)
                            self.sessions.set_metadata(session_id, "plan_carry", None)
                            self.sessions.set_metadata(session_id, "clarify_count", 0)
                            yield {
                                "event": "confirm",
                                "trip": trip,
                                "defaulted": frame.get("defaulted", []),
                            }
                        else:
                            content = frame.get("content", "")
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
    # v2：草案确认（S4 → S5）
    # ------------------------------------------------------------------
    def _confirm_pending_draft(self, session_id: str) -> Generator[Dict[str, Any], None, None]:
        """用户在 confirm 阶段回复「确认」：调 planner /trips/confirm 落库 + 审批。"""
        trip = self.sessions.get_metadata(session_id, "pending_draft")
        self.sessions.set_metadata(session_id, "plan_stage", "")
        self.sessions.set_metadata(session_id, "pending_draft", None)

        handler = self.tools.get_handler("confirm_trip")
        result = None
        if handler is not None:
            try:
                result = handler(session_id=session_id, trip=trip)
            except Exception as e:
                logger.warning(f"确认行程失败: {e}")
        if not result or not result.get("success"):
            full = (result or {}).get("message") or "行程确认失败，请稍后重试。"
            yield {"event": "chunk", "content": full}
        else:
            full = result.get("message", "")
            saved_trip = result.get("trip") or {}
            yield {
                "event": "trip_saved",
                "trip_id": result.get("trip_id"),
                "trip": saved_trip,
                **self._extract_trip_summary(saved_trip),
            }
            for piece in self._split_text(full, 60):
                yield {"event": "chunk", "content": piece}
        self.sessions.append(session_id, "user", "确认")
        self.sessions.append(session_id, "assistant", full)
        yield {"event": "respond", "content": full}

    @staticmethod
    def _split_text(text: str, width: int = 60):
        """打字机分段（与 handlers._chunk_text 同规则，graph 侧独立实现避免循环依赖）。"""
        while len(text) > width:
            yield text[:width]
            text = text[width:]
        if text:
            yield text

    @staticmethod
    def _extract_trip_summary(trip: dict) -> dict:
        """从已落库行程中提取订阅监控与展示所需的紧凑字段。"""
        days = trip.get("days") or []
        attractions = []
        for day in days:
            for act in day.get("activities") or []:
                if act.get("type") == "attraction" and act.get("title"):
                    attractions.append(act["title"])
        # 去重同时保持顺序
        seen = set()
        unique_attractions = []
        for name in attractions:
            if name not in seen:
                seen.add(name)
                unique_attractions.append(name)

        route = trip.get("route") or {}
        weather = trip.get("weather_forecast") or []
        return {
            "origin": trip.get("origin", ""),
            "destination": trip.get("destination", ""),
            "start_date": trip.get("start_date", ""),
            "end_date": trip.get("end_date", ""),
            "attractions": unique_attractions,
            "weather": weather[:3] if isinstance(weather, list) else [],
            "transport": {
                "distance_km": route.get("distance_km") if isinstance(route, dict) else None,
                "duration_min": route.get("duration_min") if isinstance(route, dict) else None,
            } if isinstance(route, dict) else None,
        }

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
