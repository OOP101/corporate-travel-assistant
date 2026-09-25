"""工具处理器 —— Agent 每个工具的进程内执行逻辑（v3 重写）

v2 的问题：编排层经 HTTP 回调独立的规划服务 / 感知服务，
同进程绕一圈网络，还带来多个同名 `api` 包的别名加载复杂度。

v3：Agent 是内核，业务能力皆外接服务——全部进程内直调：
  plan_trip_stream → core.agent.pipeline（生成管线）
  confirm_trip     → core.approval.engine（审批闭环，唯一业务主线）
  chat_query       → LLM + 政策服务 RAG 注入 + 地图 MCP 注入（感知服务后续插装）
  manage_trip      → 行程存储直读直写
  emergency_assist → 应急指引（独立模块）

所有外部能力不可用时均降级返回提示文本，不阻断对话。
"""
import logging
import re
import time
from typing import Dict, Any, Optional

from core.agent.registry import ToolResult
from core.agent.emergency import EmergencyAssistant
from core.agent.mcp_map import TencentMapMCP

logger = logging.getLogger("core.agent.tools")


# ---------------------------------------------------------------------------
# 出行管家角色 System Prompt
# ---------------------------------------------------------------------------
TRAVEL_ASSISTANT_SYSTEM_PROMPT = (
    "你是「行智」，一位专业、贴心的 AI 出行管家。"
    "你精通国内外旅行规划、交通住宿、景点美食、签证保险、行程管理等知识。\n"
    "回答要求：\n"
    "1. 用简洁友好的中文回答用户的旅行问题；\n"
    "2. 提供实用、可操作的建议，必要时分点说明；\n"
    "3. 如果用户想规划完整行程，引导其使用行程规划功能；\n"
    "4. 涉及实时信息（票价、时刻表等）时提醒用户以官方为准。"
)


class ToolHandlers:
    """工具处理器集合（v3 进程内版）"""

    def __init__(
        self,
        llm_manager=None,
        trip_store=None,
        approval_engine=None,
        policy_service=None,
    ):
        self.llm = llm_manager
        self.trips = trip_store
        self.approvals = approval_engine
        self.policy = policy_service
        self.emergency = EmergencyAssistant(llm_manager)
        # 腾讯地图 MCP（未配置 Key / SDK 缺失 → None，功能静默关闭）
        self.mcp_map = TencentMapMCP.from_env()

    # ------------------------------------------------------------------
    # 行程规划（经生成管线）
    # ------------------------------------------------------------------
    def plan_trip(
        self,
        query: str,
        session_id: str = "default",
        state: Dict[str, Any] = None,
    ) -> ToolResult:
        """生成行程草案（消费管线帧，聚合为完整摘要）"""
        try:
            frames = list(self.plan_trip_stream(query, session_id, state))
            text = "".join(
                (f.get("content", "") if isinstance(f, dict) and f.get("kind") in ("text", "clarify")
                 else (f if isinstance(f, str) else ""))
                for f in frames
            )
            failed = text.startswith("❌") or "暂时不可用" in text or "未返回结果" in text
            return ToolResult(data=text, success=not failed)
        except Exception as e:
            logger.warning(f"行程管线不可用: {e}")
            return ToolResult(
                data=(
                    "行程规划服务暂时不可用，请稍后重试。\n"
                    "您也可以告诉我目的地、出行天数和偏好，"
                    "我会先为您整理一份初步建议。"
                ),
                success=False,
            )

    def plan_trip_stream(
        self,
        query: str,
        session_id: str = "default",
        state: Dict[str, Any] = None,
    ):
        """流式行程规划（v2 四态：clarify → draft → confirm → done）。

        帧约定（与生成管线一致）:
          {"kind": "progress", "content": str}
          {"kind": "clarify",  "content": str, "missing": [...], "params": {...}}
          {"kind": "draft",    "trip": {...}, "defaulted": [...], "params": {...}}
          {"kind": "policy",   ...}
          {"kind": "timing",   "model": str, "phases": {...}}
          {"kind": "text",     "content": str}
        """
        try:
            from core.agent.pipeline import generate_draft_stream

            policy_line = ""
            timing_line = ""
            raw_len = 0
            last_report = 0
            got_result = False
            user_id = (state or {}).get("user_id") or session_id

            for frame in generate_draft_stream(
                query,
                session_id=session_id,
                user_id=user_id,
                model=(state or {}).get("model"),
                params=(state or {}).get("plan_params") or {},
                carry=(state or {}).get("plan_carry") or {},
            ):
                kind = frame.get("kind")
                if kind == "progress":
                    yield {"kind": "progress", "content": frame.get("content") or "正在为您生成行程，请稍候…"}
                elif kind == "chunk":
                    # 不透传原始 JSON；按真实到达节奏折算进度提示（每次 ~600 字汇报一次）
                    raw_len += len(frame.get("content") or "")
                    if raw_len - last_report >= 600:
                        last_report = raw_len
                        yield {
                            "kind": "progress",
                            "content": f"行程内容生成中…已生成 {raw_len} 字",
                        }
                elif kind == "clarify":
                    yield {
                        "kind": "clarify",
                        "content": frame.get("content", ""),
                        "missing": frame.get("missing", []),
                        "params": frame.get("params", {}),
                    }
                    got_result = True
                    return
                elif kind == "error":
                    yield {"kind": "text", "content": f"❌ 行程生成失败：{frame.get('content', '未知错误')}"}
                    return
                elif kind == "policy":
                    mark = "⚠️" if frame.get("has_violations") else "✅"
                    policy_line = f"\n{mark} 政策预检：{(frame.get('content') or '').replace('政策预检：', '')}"
                elif kind == "draft":
                    yield {
                        "kind": "draft",
                        "trip": frame.get("trip") or {},
                        "defaulted": frame.get("defaulted") or [],
                        "params": frame.get("params") or {},
                    }
                    got_result = True
                    summary = self._format_draft_summary(frame, policy_line)
                    for piece in self._chunk_text(summary, 60):
                        yield {"kind": "text", "content": piece}
                        time.sleep(0.02)
                elif kind == "timing":
                    timing_line = self._format_timing(frame)

            if not got_result:
                yield {"kind": "text", "content": "行程草案未返回结果，请稍后重试。"}
                return
            if timing_line:
                yield {"kind": "text", "content": timing_line}
        except Exception as e:
            logger.warning(f"行程管线不可用: {e}")
            yield {
                "kind": "text",
                "content": (
                    "行程规划服务暂时不可用，请稍后重试。\n"
                    "您也可以告诉我目的地、出行天数和偏好，"
                    "我会先为您整理一份初步建议。"
                ),
            }

    def confirm_trip(
        self,
        session_id: str = "default",
        trip: Dict[str, Any] = None,
        state: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """S4 → S5：用户确认草案 → 审批闭环引擎（落库 + 政策 + 审批发起）。"""
        if not trip:
            return {"success": False, "message": "没有待确认的行程草案。", "trip_id": None}
        if self.approvals is None:
            return {"success": False, "message": "审批闭环未就绪，请稍后重试。", "trip_id": None}
        try:
            user_id = (state or {}).get("user_id") or session_id
            result = self.approvals.confirm_draft(trip, user_id)
            events = result.get("events") or []
            policy_line = ""
            approval_line = ""
            for e in events:
                if e.get("event") == "policy":
                    mark = "⚠️" if e.get("has_violations") else "✅"
                    policy_line = f"\n{mark} 政策检查：{e.get('content', '')}"
                elif e.get("event") == "approval":
                    approval_line = f"\n🖊️ {e.get('content', '')}"
            trip_id = result.get("trip_id", "")
            title = (result.get("trip") or {}).get("title", "")
            message = f"✅ 行程「{title}」已确认保存（编号 {trip_id}）"
            if trip_id:
                message += f"\n🧳 行程编号：{trip_id}"
            if policy_line:
                message += policy_line
            if approval_line:
                message += approval_line
            if not approval_line:
                message += "\n（按当前政策无需审批或缺少审批人，行程直接生效）"
            return {
                "success": True,
                "message": message,
                "trip_id": trip_id,
                "trip": result.get("trip") or trip,
                "events": events,
            }
        except ValueError as e:
            return {"success": False, "message": str(e), "trip_id": None}
        except Exception as e:
            logger.warning(f"确认行程失败: {e}")
            return {"success": False, "message": "行程确认失败，请稍后重试。", "trip_id": None}

    @staticmethod
    def _chunk_text(text: str, width: int = 60):
        """把一段文本切成不超过 width 的片段（保留原换行，拼接后等于原文）。"""
        if not text:
            return
        while len(text) > width:
            yield text[:width]
            text = text[width:]
        if text:
            yield text

    @staticmethod
    def _format_timing(event: dict) -> str:
        """把 timing 帧格式化为一行可读的耗时摘要"""
        phases = event.get("phases") or {}
        if not phases:
            return ""

        labels = {
            "extract": "提取", "generate": "生成", "parse": "解析",
            "save": "落库", "policy": "政策",
        }

        def ms(v) -> str:
            return f"{v / 1000:.1f}s" if v >= 1000 else f"{int(v)}ms"

        parts = []
        for key in ("extract", "generate", "parse", "save", "policy"):
            ph = phases.get(key)
            if not isinstance(ph, dict):
                continue
            dur = ph.get("duration_ms")
            if dur is None:
                continue
            parts.append(f"{labels[key]} {ms(dur)}")

        total = (phases.get("api_total") or {}).get("duration_ms")
        tail = f" · 总计 {ms(total)}" if total is not None else ""

        first = None
        for key in ("generate", "extract"):
            llm = (phases.get(key) or {}).get("llm")
            if isinstance(llm, dict) and llm.get("first_chunk_ms") is not None:
                first = llm["first_chunk_ms"]
                break
        head = f" · 首字 {ms(first)}" if first is not None else ""

        model = event.get("model")
        model_tag = f" [{model}]" if model and model != "default" else ""
        return f"\n⏱️ 耗时：{' · '.join(parts)}{tail}{head}{model_tag}"

    @staticmethod
    def _format_draft_summary(draft_event: dict, policy_line: str = "") -> str:
        """把 draft 帧格式化为「方案草案确认」摘要（PRD v2 S4）。

        代填项带 [代填] 标注；酒店为腾讯地图真实 POI 候选；结尾给确认引导。
        """
        trip = draft_event.get("trip") or {}
        defaulted = draft_event.get("defaulted") or []
        params = draft_event.get("params") or {}
        days = trip.get("days", []) or []

        scene_names = {
            "business": "商务出差", "meeting": "会议参展", "visit": "客户拜访",
            "team": "团队出行", "personal": "个人出游",
        }
        scene = trip.get("scene") or params.get("scene") or ""
        scene_label = scene_names.get(scene, scene) if scene else ""

        lines = ["📋 行程方案草案（未提交，请确认）"]
        if trip.get("title"):
            lines.append(f"标题：{trip['title']}")
        if scene_label:
            lines.append(f"场景：{scene_label}")
        dates = " ~ ".join(x for x in [trip.get("start_date"), trip.get("end_date")] if x)
        if dates:
            suffix = f"（{len(days)} 天）" if days else ""
            lines.append(f"日期：{dates}{suffix}")
        if trip.get("destination"):
            lines.append(f"目的地：{trip['destination']}")
        if trip.get("origin"):
            lines.append(f"出发地：{trip['origin']}")
        party = trip.get("travel_party") or []
        if party:
            names = "、".join(
                (p.get("name") or p.get("role") or "") if isinstance(p, dict) else str(p)
                for p in party
            )
            if names:
                lines.append(f"出行人：{names}")
        budget = trip.get("budget_total")
        if budget:
            lines.append(f"预算：¥{float(budget):,.0f}")
        hotels = trip.get("hotel_options") or []
        if hotels:
            main = hotels[0]
            extra = f"（另有 {len(hotels) - 1} 家备选，确认页可换）" if len(hotels) > 1 else ""
            addr = f"（{main.get('address')}）" if main.get("address") else ""
            lines.append(f"酒店建议：{main.get('name', '')}{addr}{extra} · 价格以预订平台为准")

        # 代填项显式标注（PRD v2 §4.1：代填值必须展示给用户确认）
        for d in defaulted:
            field_names = {
                "num_adults": "人数", "budget_total": "预算", "origin": "出发地",
            }
            name = field_names.get(d.get("field"), d.get("field"))
            lines.append(f"[代填] {name}：{d.get('note', '')}")

        for i, d in enumerate(days, 1):
            date = d.get("date", "")
            theme = d.get("theme", "")
            acts = d.get("activities", []) or []
            label = " / ".join(x for x in [date, theme] if x)
            lines.append(f"  · Day {i} {label}（{len(acts)} 项活动）")

        if policy_line:
            lines.append(policy_line.strip())
        lines.append("👇 请确认：回复「确认」提交审批，或直接说出要调整的内容重新生成。")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 智能问答
    # ------------------------------------------------------------------
    _POLICY_KEYWORDS = (
        "政策", "报销", "标准", "补贴", "审批", "制度", "规定",
        "住宿", "机票", "火车", "席", "上限", "材料", "发票", "多少钱",
    )

    def _policy_context(self, query: str) -> str:
        """政策类问答时经政策外接服务检索原文，作为回答依据注入（RAG）。

        检索失败或非政策类问题返回空串，不阻塞问答主链路。
        """
        try:
            if self.policy is None or not any(k in query for k in self._POLICY_KEYWORDS):
                return ""
            res = self.policy.search_docs(query, top_k=2)
            docs = (res or {}).get("documents") or []
            if not docs:
                return ""
            parts = []
            for d in docs:
                excerpt = d.get("excerpt") or (d.get("content") or "")[:120]
                parts.append(f"《{d.get('title', '政策文档')}》{excerpt}")
            return (
                "以下是公司差旅政策相关原文，回答时请依据这些内容，"
                "并在要点后注明出自哪份文档：\n" + "\n".join(parts)
            )
        except Exception as e:
            logger.debug(f"政策检索跳过: {e}")
            return ""

    _REALTIME_WEATHER_KW = ("天气", "气温", "下雨", "降雨", "温度", "空气质量", "紫外线", "气象")
    _REALTIME_FLIGHT_KW = ("航班", "延误", "起飞", "登机", "取消航班", "准点")
    _MAJOR_CITIES = (
        "北京", "上海", "广州", "深圳", "成都", "杭州", "西安", "重庆", "南京", "武汉",
        "天津", "苏州", "青岛", "厦门", "长沙", "郑州", "昆明", "哈尔滨", "沈阳", "济南",
        "合肥", "福州", "南昌", "贵阳", "南宁", "兰州", "太原", "石家庄", "长春", "海口",
        "宁波", "东莞", "无锡", "佛山", "大连",
    )

    def _detect_city(self, query: str) -> str:
        """从问句中提取城市名（已知大城市或 'X天气' 句式）"""
        for c in self._MAJOR_CITIES:
            if c in query:
                return c
        m = re.search(r"([一-龥]{2,4})(?:的)?天气", query)
        if m:
            return m.group(1)
        return ""

    def _realtime_context(self, query: str) -> str:
        """实时数据直查上下文 —— 感知外接服务（v3 规划中，MVP 未插装）。

        接入后按「按需直查」调用航班/天气/路况查询；当前返回空串跳过。
        """
        return ""

    @staticmethod
    def _fmt_weather(d: dict) -> str:
        cond = d.get("text") or d.get("condition") or "未知"
        temp = d.get("temp", "")
        tag = " [模拟]" if d.get("mock") else ""
        return (
            f"【天气·{d.get('city', '')}】{cond} {temp}°C，"
            f"体感 {d.get('feels_like', temp)}°C{tag}"
        )

    @staticmethod
    def _fmt_flight(d: dict) -> str:
        tag = " [模拟]" if d.get("mock") else ""
        return (
            f"【航班·{d.get('flight_number', '')}】{d.get('origin', '')}→"
            f"{d.get('destination', '')} 状态：{d.get('status', '')}，"
            f"起飞 {d.get('scheduled_departure', '')}{tag}"
        )

    def _map_mcp_context(self, query: str) -> str:
        """腾讯地图 MCP 实查上下文：地图类问题命中规则才调用，失败静默回退。"""
        if self.mcp_map is None or not self.mcp_map.is_available():
            return ""
        try:
            res = self.mcp_map.query(query)
        except Exception as e:
            logger.warning(f"地图 MCP 上下文构建失败: {e}")
            return ""
        if not res or not res.get("text"):
            return ""
        return (f"【地图实时数据 · 腾讯位置服务 MCP】（工具 {res.get('tool')} 实查，"
                f"回答以下问题时引用这些事实，并提醒以实际为准）：\n{res['text'][:1500]}")

    def chat_query(
        self,
        query: str,
        session_id: str = "default",
        state: Dict[str, Any] = None,
    ) -> ToolResult:
        """用 LLM 回答旅行相关问题（政策 RAG / 地图 MCP 依据注入；LLM 不可用降级模板）。"""
        if self.llm is None or not self.llm.is_available():
            logger.warning("LLM 不可用，返回规则模板回复")
            return ToolResult(
                data=self._fallback_answer(query),
                success=False,
            )

        try:
            messages = [{"role": "system", "content": TRAVEL_ASSISTANT_SYSTEM_PROMPT}]

            context = (state or {}).get("context_prompt", "")
            if context:
                messages.append({"role": "system", "content": context})

            policy_context = self._policy_context(query)
            if policy_context:
                messages.append({"role": "system", "content": policy_context})

            realtime_context = self._realtime_context(query)
            if realtime_context:
                messages.append({"role": "system", "content": realtime_context})

            map_context = self._map_mcp_context(query)
            if map_context:
                messages.append({"role": "system", "content": map_context})

            messages.append({"role": "user", "content": query})

            model = (state or {}).get("model")
            reply = self.llm.chat(messages, temperature=0.5, model=model)
            return ToolResult(data=reply)
        except Exception as e:
            logger.warning(f"LLM 调用失败，降级为模板回复: {e}")
            return ToolResult(
                data=self._fallback_answer(query),
                success=False,
            )

    # ------------------------------------------------------------------
    # 行程管理（进程内存储直读直写）
    # ------------------------------------------------------------------
    def manage_trip(
        self,
        query: str,
        session_id: str = "default",
        state: Dict[str, Any] = None,
    ) -> ToolResult:
        """管理已有行程：查看列表 / 删除行程 / 修改行程标题。"""
        if self.trips is None:
            return ToolResult(data="行程管理服务暂时不可用。", success=False)
        user_id = (state or {}).get("user_id") or session_id
        try:
            delete_match = re.search(r"(?:删除|取消|移除)\s*(?:行程\s*|计划\s*|安排\s*)?(trip_[a-z0-9]+|[^\s，。]{1,30})", query)
            rename_match = re.search(r"(?:把|将)\s*([^\s，。]{1,30})\s*(?:改名为?|改成|重命名(?:为)?)\s*[：:]?\s*([^\s，。]{1,40})", query)
            update_match = re.search(r"(?:修改|更新|调整|重命名)\s*(?:行程\s*)?(trip_[a-z0-9]+|[^\s，。]{1,30})", query)

            # 无具体名称的删除：代词指代或仅说“删除行程” → 取最近更新的一条
            if not re.search(r"trip_[a-z0-9]+", query):
                pronoun_hit = re.search(
                    r"(?:删除|取消|移除)\s*(?:掉|了)?\s*(?:这个|该|此|这趟|刚才|当前|最近|它)\s*(?:的)?\s*(?:行程|计划|安排)?",
                    query,
                )
                bare_delete = re.search(r"(?:删除|取消|移除)\s*(?:行程|计划|安排)\s*$", query)
                if pronoun_hit or bare_delete:
                    trips = self._fetch_trips(user_id)
                    if not trips:
                        return ToolResult(data="当前没有可删除的行程。", success=False)
                    target = trips[0].get("trip_id") or trips[0].get("id")
                    title = trips[0].get("title") or target
                    self.trips.delete(target)
                    return ToolResult(data=f"🗑️ 已删除行程「{title}」。")

            if delete_match:
                target = delete_match.group(1)
                trip_id = self._resolve_trip_id(target, user_id)
                if not trip_id:
                    return ToolResult(
                        data=f"没有找到名为「{target}」的行程，请确认行程名称或编号。",
                        success=False,
                    )
                self.trips.delete(trip_id)
                return ToolResult(data=f"🗑️ 已删除行程「{trip_id}」。")

            if rename_match:
                target = rename_match.group(1)
                new_title = rename_match.group(2)
                trip_id = self._resolve_trip_id(target, user_id)
                if not trip_id:
                    return ToolResult(
                        data=f"没有找到名为「{target}」的行程，请确认行程名称或编号。",
                        success=False,
                    )
                updated = self.trips.update(trip_id, {"title": new_title})
                return ToolResult(data=f"✏️ 已修改行程标题为「{(updated or {}).get('title', new_title)}」。")

            if update_match:
                target = update_match.group(1)
                new_title_match = re.search(r"(?:改成|改名为|标题改为|标题改成)\s*[：:]?\s*([^\s，。]{1,40})", query)
                trip_id = self._resolve_trip_id(target, user_id)
                if not trip_id:
                    return ToolResult(
                        data=f"没有找到名为「{target}」的行程，请确认行程名称或编号。",
                        success=False,
                    )
                if not new_title_match:
                    return ToolResult(
                        data="请告诉我修改后的新标题，例如：把「成都3日游」改名为「成都亲子游」。",
                        success=False,
                    )
                new_title = new_title_match.group(1)
                updated = self.trips.update(trip_id, {"title": new_title})
                return ToolResult(data=f"✏️ 已修改行程标题为「{(updated or {}).get('title', new_title)}」。")

            return self._list_trips(user_id)
        except Exception as e:
            logger.warning(f"行程管理操作失败: {e}")
            return ToolResult(data="行程管理操作失败，请稍后重试。", success=False)

    def _resolve_trip_id(self, target: str, user_id: str) -> Optional[str]:
        """把用户输入的目标（trip_id 或标题/简称/指代）解析为 trip_id。

        匹配优先级：精确 trip_id → 标题精确/子串 → 子序列相似度（适配中文简称）。
        """
        if re.fullmatch(r"trip_[a-z0-9]+", target):
            return target
        trips = self._fetch_trips(user_id)
        if not trips:
            return None
        norm = lambda s: (s or "").strip().lower()

        for trip in trips:
            if not isinstance(trip, dict):
                continue
            title = norm(trip.get("title", ""))
            if not title:
                continue
            if title == norm(target) or target in title or title in target:
                return trip.get("trip_id") or trip.get("id")

        def subseq_ratio(a: str, b: str) -> float:
            it = iter(b)
            return sum(1 for ch in a if ch in it) / max(len(a), 1)

        best, best_score = None, 0.0
        for trip in trips:
            if not isinstance(trip, dict):
                continue
            title = norm(trip.get("title", ""))
            if not title or len(target) < 2:
                continue
            score = subseq_ratio(target, title)
            if score > best_score:
                best_score, best = score, trip.get("trip_id") or trip.get("id")
        if best and best_score >= 0.85:
            return best
        return None

    def _fetch_trips(self, user_id: str) -> list:
        """当前用户的行程列表（存储直读）"""
        if self.trips is None:
            return []
        return self.trips.list_by_user(user_id) or []

    def _list_trips(self, user_id: str) -> ToolResult:
        """列出当前用户的行程"""
        trips = self._fetch_trips(user_id)
        if not trips:
            return ToolResult(data="您目前还没有已保存的行程。需要我帮您规划一个新的行程吗？")

        lines = ["📋 您的行程列表："]
        for i, trip in enumerate(trips, 1):
            if isinstance(trip, dict):
                title = trip.get("title", "未命名行程")
                status = trip.get("status", "")
                trip_id = trip.get("trip_id") or trip.get("id", "")
                suffix = f"（{status}）" if status else ""
                lines.append(f"  {i}. {title}{suffix}" + (f" [{trip_id}]" if trip_id else ""))
            else:
                lines.append(f"  {i}. {trip}")
        return ToolResult(data="\n".join(lines))

    # ------------------------------------------------------------------
    # 应急协助
    # ------------------------------------------------------------------
    def emergency_assist(
        self,
        query: str,
        session_id: str = "default",
        state: Dict[str, Any] = None,
    ) -> ToolResult:
        """应急协助工具（应急电话/证件丢失/就医导航/保险报案）"""
        try:
            result = self.emergency.handle(query, session_id)
            return ToolResult(data=result)
        except Exception as e:
            logger.error(f"应急协助处理失败: {e}")
            return ToolResult(
                data=(
                    "🆘 应急协助暂时不可用。\n"
                    "如遇紧急情况：\n"
                    "· 国内报警 110 / 急救 120\n"
                    "· 境外领事保护 +86-10-12308\n"
                    "请直接拨打上述电话求助。"
                ),
                success=False,
            )

    # ------------------------------------------------------------------
    # 降级模板回复
    # ------------------------------------------------------------------
    def _fallback_answer(self, query: str) -> str:
        """LLM 不可用时的规则模板回复"""
        return (
            f"我是行智·AI出行管家，关于「{query}」——\n"
            "智能问答服务暂时受限，但我可以为您提供以下帮助：\n"
            "1. 行程规划 —— 告诉我目的地和出行时间，为您定制行程；\n"
            "2. 行程管理 —— 查看或管理您已保存的行程；\n"
            "3. 旅行问答 —— 解答交通、住宿、景点、美食等问题。\n"
            "请稍后重试，或直接描述您的出行需求。"
        )
