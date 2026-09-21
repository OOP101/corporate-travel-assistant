"""
工具处理器 —— 每个工具的执行业务逻辑

当前工具：
  - plan_trip:         调用 planner-core 生成行程
  - chat_query:        用 LLM 回答旅行相关问题
  - manage_trip:       调用 planner-core 管理行程（列表）
  - emergency_assist:  应急协助（应急电话/证件丢失/就医/保险报案）

所有外部服务不可用时均降级返回提示文本。
"""
import logging
import re
import time
import requests
from typing import Dict, Any, Optional

from .registry import ToolResult
from .emergency import EmergencyAssistant
from .mcp_map import TencentMapMCP
from shared.http_client import ServiceClient

logger = logging.getLogger("journey-hub.tools")


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
    """
    工具处理器集合

    plan_trip   → planner-core POST /trips/generate → 返回行程信息
    chat_query  → LLM 直接回答旅行相关问题
    manage_trip → planner-core GET /trips → 列出已有行程
    """

    def __init__(
        self,
        llm_manager=None,
        planner_url: str = "http://127.0.0.1:8002",
        sense_url: str = "http://127.0.0.1:8003",
    ):
        self.llm = llm_manager
        self.planner_url = planner_url.rstrip("/")
        self.sense_url = sense_url.rstrip("/")
        self.client = ServiceClient(timeout=30)
        self.emergency = EmergencyAssistant(llm_manager)
        # 腾讯地图 MCP（未配置 Key / SDK 缺失 → None，功能静默关闭）
        self.mcp_map = TencentMapMCP.from_env()

    # ------------------------------------------------------------------
    # 行程规划
    # ------------------------------------------------------------------
    def plan_trip(
        self,
        query: str,
        session_id: str = "default",
        state: Dict[str, Any] = None,
    ) -> ToolResult:
        """调用 planner-core 生成行程（消费流式帧，聚合为完整摘要）"""
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
            logger.warning(f"planner-core 不可用: {e}")
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
        """流式版行程规划（v2 四态：clarify → generate 草案 → confirm → done）。

        帧约定:
          {"kind": "progress", "content": str}                     生成过程提示（不进最终正文）
          {"kind": "clarify",  "content": str, "missing": [...], "params": {...}}
                                                                   S2 澄清反问（附缺参清单，前端渲染选项）
          {"kind": "draft",    "trip": {...}, "defaulted": [...]}  S3 草案（未落库，前端渲染确认卡）
          {"kind": "text",     "content": str}                     人类可读摘要/政策预检/耗时（流式入正文）

        v2 语义：planner 生成的是「草案」，未落库、未审批；用户确认后由
        confirm_trip → planner POST /trips/confirm 完成落库与审批。
        """
        try:
            policy_line = ""
            timing_line = ""
            raw_len = 0
            last_report = 0
            got_result = False
            for event in self.client.post_stream(
                f"{self.planner_url}/trips/generate",
                json={
                    "query": query,
                    "session_id": session_id,
                    "model": (state or {}).get("model"),
                    "params": (state or {}).get("plan_params") or {},
                    "carry": (state or {}).get("plan_carry") or {},
                },
                timeout=300,  # 行程生成（含推理模型思考）耗时长，避免中途读超时
            ):
                ev = event.get("event")
                if ev == "status":
                    yield {"kind": "progress", "content": event.get("content") or "正在为您生成行程，请稍候…"}
                elif ev == "chunk":
                    # 不透传原始 JSON；按真实到达节奏折算进度提示（每次 ~600 字汇报一次）
                    raw_len += len(event.get("content") or "")
                    if raw_len - last_report >= 600:
                        last_report = raw_len
                        yield {
                            "kind": "progress",
                            "content": f"行程内容生成中…已生成 {raw_len} 字",
                        }
                elif ev == "clarify":
                    # S2 澄清：必填缺失，本次不生成
                    yield {
                        "kind": "clarify",
                        "content": event.get("content", ""),
                        "missing": event.get("missing", []),
                        "params": event.get("params", {}),
                    }
                    got_result = True
                    return
                elif ev == "error":
                    yield {"kind": "text", "content": f"❌ 行程生成失败：{event.get('content', '未知错误')}"}
                    return
                elif ev == "policy":
                    mark = "⚠️" if event.get("has_violations") else "✅"
                    policy_line = f"\n{mark} 政策预检：{(event.get('content') or '').replace('政策预检：', '')}"
                elif ev == "draft":
                    # S3 草案：未落库未审批，交前端渲染确认卡
                    yield {
                        "kind": "draft",
                        "trip": event.get("trip") or {},
                        "defaulted": event.get("defaulted") or [],
                        "params": event.get("params") or {},
                    }
                    got_result = True
                    # 人话摘要 + [代填] 标注 + 确认引导（文本流）
                    summary = self._format_draft_summary(event, policy_line)
                    for piece in self._chunk_text(summary, 60):
                        yield {"kind": "text", "content": piece}
                        time.sleep(0.02)
                elif ev == "timing":
                    # 埋点透传：planner 各阶段耗时，供用户/排查直接看到时间花在哪
                    timing_line = self._format_timing(event)

            if not got_result:
                yield {"kind": "text", "content": "行程草案未返回结果，请稍后重试。"}
                return

            if timing_line:
                yield {"kind": "text", "content": timing_line}
            # 摘要与政策预检已在 draft 分支输出；此处仅收尾
            return
        except Exception as e:
            logger.warning(f"planner-core 不可用: {e}")
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
        """S4 → S5：用户确认草案后，调 planner POST /trips/confirm 落库 + 政策 + 审批。

        Returns:
            dict: {success, message, trip_id, trip, events}
        """
        if not trip:
            return {"success": False, "message": "没有待确认的行程草案。", "trip_id": None}
        try:
            resp = self.client.post(
                f"{self.planner_url}/trips/confirm",
                json={"trip": trip, "session_id": session_id},
            )
            events = resp.get("events") or []
            policy_line = ""
            approval_line = ""
            for e in events:
                if e.get("event") == "policy":
                    mark = "⚠️" if e.get("has_violations") else "✅"
                    policy_line = f"\n{mark} 政策检查：{e.get('content', '')}"
                elif e.get("event") == "approval":
                    approval_line = f"\n🖊️ {e.get('content', '')}"
            trip_id = resp.get("trip_id", "")
            title = (resp.get("trip") or {}).get("title", "")
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
                "trip": resp.get("trip") or trip,
                "events": events,
            }
        except Exception as e:
            logger.warning(f"确认行程失败: {e}")
            return {"success": False, "message": "行程确认失败，请稍后重试。", "trip_id": None}

    @staticmethod
    def _chunk_text(text: str, width: int = 60):
        """把一段文本切成不超过 width 的片段（保留原换行，拼接后等于原文）。

        用于把「生成完成的格式化摘要」模拟成逐段流式，前端逐帧追加。
        """
        if not text:
            return
        while len(text) > width:
            yield text[:width]
            text = text[width:]
        if text:
            yield text

    @staticmethod
    def _format_timing(event: dict) -> str:
        """把 planner 的 timing 帧格式化为一行可读的耗时摘要"""
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

        # 首字延迟取生成阶段的 LLM 统计（没有则回退到提取阶段）
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
        """把 planner draft 事件格式化为「方案草案确认」摘要（PRD v2 S4）。

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

    @staticmethod
    def _format_trip_summary(done_event: dict) -> str:
        """把 planner done 事件的行程数据格式化为用户可读摘要"""
        trip = done_event.get("trip") or {}
        title = trip.get("title", "")
        destination = trip.get("destination", "")
        days = trip.get("days", []) or []
        checklist = trip.get("checklist", []) or []
        trip_id = done_event.get("trip_id", "")

        lines = ["🧳 行程已生成"]
        if title:
            lines.append(f"标题：{title}")
        if destination:
            lines.append(f"目的地：{destination}")
        if days:
            lines.append(f"天数：{len(days)} 天")
            for d in days:
                date = d.get("date", "")
                theme = d.get("theme", "")
                acts = d.get("activities", []) or []
                label = " / ".join(x for x in [date, theme] if x)
                lines.append(f"  · {label}（{len(acts)} 项活动）")
        if checklist:
            lines.append(f"出行清单：{len(checklist)} 项")
        if trip_id:
            lines.append(f"行程编号：{trip_id}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 智能问答
    # ------------------------------------------------------------------
    _POLICY_KEYWORDS = (
        "政策", "报销", "标准", "补贴", "审批", "制度", "规定",
        "住宿", "机票", "火车", "席", "上限", "材料", "发票", "多少钱",
    )

    def _policy_context(self, query: str) -> str:
        """政策类问答时检索知识库原文，作为回答依据注入（RAG 补充）。

        检索失败或非政策类问题返回空串，不阻塞问答主链路。
        """
        try:
            if not any(k in query for k in self._POLICY_KEYWORDS):
                return ""
            resp = self.client.post(
                f"{self.planner_url}/policy-docs/search",
                json={"query": query, "top_k": 2},
                timeout=15,
            )
            docs = (resp or {}).get("documents") or []
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
        """实时数据类问答时直接调用感知引擎 /query 直查，作为回答依据注入。

        走「按需直查」而非监控订阅；失败静默跳过，不阻塞主链路。
        """
        try:
            parts = []
            # 航班状态
            fm = re.search(r"([A-Za-z]{2}\d{2,4})", query)
            if any(k in query for k in self._REALTIME_FLIGHT_KW) and fm:
                resp = self.client.post(
                    f"{self.sense_url}/query",
                    json={"type": "flight", "flight_number": fm.group(1).upper()},
                    timeout=15,
                )
                data = (resp or {}).get("data") or {}
                if data:
                    parts.append(self._fmt_flight(data))
            # 天气
            if any(k in query for k in self._REALTIME_WEATHER_KW):
                city = self._detect_city(query)
                if city:
                    resp = self.client.post(
                        f"{self.sense_url}/query",
                        json={"type": "weather", "city": city},
                        timeout=15,
                    )
                    data = (resp or {}).get("data") or {}
                    if data:
                        parts.append(self._fmt_weather(data))
            if not parts:
                return ""
            note = "（以下为实时数据直查结果，接口不可用时为模拟数据）"
            return note + "\n" + "\n".join(parts)
        except Exception as e:
            logger.debug(f"实时数据直查跳过: {e}")
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
        """
        用 LLM 回答旅行相关问题

        构建出行管家角色 system prompt，结合会话上下文生成回复。
        政策类问题先检索差旅政策知识库原文作为回答依据（RAG）。
        LLM 不可用时降级为规则模板回复。
        """
        # 降级：LLM 不可用
        if self.llm is None or not self.llm.is_available():
            logger.warning("LLM 不可用，返回规则模板回复")
            return ToolResult(
                data=self._fallback_answer(query),
                success=False,
            )

        try:
            messages = [{"role": "system", "content": TRAVEL_ASSISTANT_SYSTEM_PROMPT}]

            # 注入会话上下文
            context = (state or {}).get("context_prompt", "")
            if context:
                messages.append({"role": "system", "content": context})

            # 注入政策知识库依据（RAG 补充）
            policy_context = self._policy_context(query)
            if policy_context:
                messages.append({"role": "system", "content": policy_context})

            # 注入实时数据直查依据（按需拉取，不等监控订阅）
            realtime_context = self._realtime_context(query)
            if realtime_context:
                messages.append({"role": "system", "content": realtime_context})

            # 注入地图实时数据（腾讯位置服务 MCP，地图类问题命中才拉取）
            map_context = self._map_mcp_context(query)
            if map_context:
                messages.append({"role": "system", "content": map_context})

            messages.append({"role": "user", "content": query})

            model = (state or {}).get("model")  # 前端选择的模型（可选）
            reply = self.llm.chat(messages, temperature=0.5, model=model)
            return ToolResult(data=reply)
        except Exception as e:
            logger.warning(f"LLM 调用失败，降级为模板回复: {e}")
            return ToolResult(
                data=self._fallback_answer(query),
                success=False,
            )

    # ------------------------------------------------------------------
    # 行程管理
    # ------------------------------------------------------------------
    def manage_trip(
        self,
        query: str,
        session_id: str = "default",
        state: Dict[str, Any] = None,
    ) -> ToolResult:
        """
        管理已有行程：查看列表 / 删除行程 / 修改行程标题。

        解析用户输入中的操作关键词与目标行程（trip_id 或标题），
        调用 planner-core 对应 CRUD 接口；默认返回行程列表。
        """
        try:
            # 识别操作类型
            delete_match = re.search(r"(?:删除|取消|移除)\s*(?:行程\s*|计划\s*|安排\s*)?(trip_[a-z0-9]+|[^\s，。]{1,30})", query)
            # “把X改名为Y”模式：目标行程是 X，新标题是 Y
            rename_match = re.search(r"(?:把|将)\s*([^\s，。]{1,30})\s*(?:改名为?|改成|重命名(?:为)?)\s*[：:]?\s*([^\s，。]{1,40})", query)
            update_match = re.search(r"(?:修改|更新|调整|重命名)\s*(?:行程\s*)?(trip_[a-z0-9]+|[^\s，。]{1,30})", query)

            # 无具体名称的删除：代词指代（“删除这个行程 / 删掉它 / 取消刚才的”）
            # 或仅说“删除行程” → 取最近更新的一条行程
            if not re.search(r"trip_[a-z0-9]+", query):
                pronoun_hit = re.search(
                    r"(?:删除|取消|移除)\s*(?:掉|了)?\s*(?:这个|该|此|这趟|刚才|当前|最近|它)\s*(?:的)?\s*(?:行程|计划|安排)?",
                    query,
                )
                bare_delete = re.search(r"(?:删除|取消|移除)\s*(?:行程|计划|安排)\s*$", query)
                if pronoun_hit or bare_delete:
                    trips = self._fetch_trips(session_id)
                    if not trips:
                        return ToolResult(data="当前没有可删除的行程。", success=False)
                    target = trips[0].get("trip_id") or trips[0].get("id")
                    title = trips[0].get("title") or target
                    self.client.delete(f"{self.planner_url}/trips/{target}")
                    return ToolResult(data=f"🗑️ 已删除行程「{title}」。")

            # 删除行程
            if delete_match:
                target = delete_match.group(1)
                trip_id = self._resolve_trip_id(target, session_id)
                if not trip_id:
                    return ToolResult(
                        data=f"没有找到名为「{target}」的行程，请确认行程名称或编号。",
                        success=False,
                    )
                resp = self.client.delete(f"{self.planner_url}/trips/{trip_id}")
                return ToolResult(data=f"🗑️ 已删除行程「{resp.get('trip_id', trip_id)}」。")

            # 修改行程（标题）
            if rename_match:
                target = rename_match.group(1)
                new_title = rename_match.group(2)
                trip_id = self._resolve_trip_id(target, session_id)
                if not trip_id:
                    return ToolResult(
                        data=f"没有找到名为「{target}」的行程，请确认行程名称或编号。",
                        success=False,
                    )
                resp = self.client.put(
                    f"{self.planner_url}/trips/{trip_id}",
                    json={"data": {"title": new_title}},
                )
                return ToolResult(data=f"✏️ 已修改行程标题为「{resp.get('title', new_title)}」。")

            if update_match:
                target = update_match.group(1)
                new_title_match = re.search(r"(?:改成|改名为|标题改为|标题改成)\s*[：:]?\s*([^\s，。]{1,40})", query)
                trip_id = self._resolve_trip_id(target, session_id)
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
                resp = self.client.put(
                    f"{self.planner_url}/trips/{trip_id}",
                    json={"data": {"title": new_title}},
                )
                return ToolResult(data=f"✏️ 已修改行程标题为「{resp.get('title', new_title)}」。")

            # 默认：查看行程列表
            return self._list_trips(session_id)
        except requests.HTTPError as e:
            logger.warning(f"planner-core 管理操作失败: {e}")
            return ToolResult(data="行程管理操作失败，请稍后重试。", success=False)
        except Exception as e:
            logger.warning(f"planner-core 不可用: {e}")
            return ToolResult(
                data="行程管理服务暂时不可用，请稍后重试。",
                success=False,
            )

    def _resolve_trip_id(self, target: str, session_id: str) -> Optional[str]:
        """把用户输入的目标（trip_id 或标题/简称/指代）解析为 trip_id。

        匹配优先级：精确 trip_id → 标题精确/子串 → 子序列相似度（适配中文简称，
        如“成都巡检行程”匹配“成都商务巡检与文化体验”）。
        """
        if re.fullmatch(r"trip_[a-z0-9]+", target):
            return target
        trips = self._fetch_trips(session_id)
        if not trips:
            return None
        norm = lambda s: (s or "").strip().lower()

        # 1) 标题精确匹配 / 子串包含（双向）
        for trip in trips:
            if not isinstance(trip, dict):
                continue
            title = norm(trip.get("title", ""))
            if not title:
                continue
            if title == norm(target) or target in title or title in target:
                return trip.get("trip_id") or trip.get("id")

        # 2) 子序列相似度：用户常丢中间字（“成都巡检行程”→“成都商务巡检与文化体验”）
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
        # 要求目标字符几乎全部作为子序列出现在标题中，避免误删
        if best and best_score >= 0.85:
            return best
        return None

    def _fetch_trips(self, session_id: str) -> list:
        """从 planner-core 拉取当前会话的行程列表"""
        resp = self.client.get(
            f"{self.planner_url}/trips",
            params={"session_id": session_id},
        )
        if isinstance(resp, dict):
            return resp.get("trips") or resp.get("data") or []
        return []

    def _list_trips(self, session_id: str) -> ToolResult:
        """列出当前会话的行程"""
        trips = self._fetch_trips(session_id)
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
        """
        应急协助工具

        根据用户输入匹配应急类别，返回标准化应急指引。
        覆盖：应急电话、证件丢失、就医导航、保险报案、紧急联系人。
        """
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
