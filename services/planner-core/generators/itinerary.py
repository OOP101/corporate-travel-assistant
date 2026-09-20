"""
行程生成器 —— 策程 · Planner Core 核心模块

两阶段生成流程:
  1. 参数提取 (chat_json): 从用户自然语言中提取目的地、日期、人数、预算等结构化参数
  2. 行程生成 (chat / chat_stream): 依据参数 + 规划规则生成结构化行程 JSON

降级策略:
  - LLM 不可用时 (is_available() == False) 走 _demo_generate()，返回示例行程模板
  - LLM 调用异常时捕获并降级到示例模板，保证无 key 也能演示

埋点 (2026-09-03): 5 模型性能对比
  - self._phase_timings 记录每个阶段耗时：参数提取(extract)、行程生成(generate)、
  - 解析(parse)、保存(save)，各阶段附 LLM 调用统计（duration_ms / tokens / first_chunk_ms）
  - API 层在 done 后发出 timing SSE 帧，前端/外部脚本可直接消费
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Generator, Optional

from shared.llm import LLMManager, parse_json_tolerant
from shared.config import settings
from shared.embedding import get_embedder
from shared.geo import TencentMapClient, QWeatherClient
from shared.store.document_store import make_excerpt
from shared.models import (
    Trip, TripDay, Activity, ActivityType, TripStatus,
    Location, TravelPartyMember,
)
from .template import build_trip_from_template
from .fast_extract import fast_covers_required, fast_extract_params

logger = logging.getLogger("planner-core.generators.itinerary")


# ---------------------------------------------------------------------------
# 行程规划规则 (系统提示词内嵌) —— v2：基础规则 + 按 scene 拆分的场景规则
# ---------------------------------------------------------------------------
PLANNING_RULES_BASE = """\
你是「策程」AI 行程规划引擎，请严格遵循以下规划规则生成行程：

【节奏规则】
1. 相邻活动之间的通勤时间 (transport) 原则上 ≤ 30 分钟，超出需在 tips 中提示。
2. 每日用餐 (dining) 预留 1~1.5 小时；正餐安排在 11:30-13:00 与 17:30-19:00。
3. 每日首项活动建议 09:00 开始，末项不超过 22:00 结束。

【质量规则】
4. 时间段不得重叠，按时间升序排列。
5. location 必须含 name；能给出经纬度则填写 lat/lng (WGS84)，否则填 0。
6. booking_required=true 的活动 (如热门景点、演出) 须在 tips 中注明预约方式。
7. estimated_cost 为该项单人预估花费 (元)；ticket_price 为门票单价。
8. budget_total 应与各日合计大致吻合。
"""

# 场景规则（PRD v2 §3.1）：business/meeting/visit 禁景点，personal 才是旅游节奏
_SCENE_RULES = {
    "business": """\

【场景规则：商务出差】
- 以会议 (meeting)、客户拜访、现场办公类活动为主体；【禁止】生成景点 (attraction)、购物等旅游活动。
- 住宿参考「推荐酒店候选」，默认选会场/客户地附近；行程含往返交通衔接与晚间工作缓冲。
- 标题体现出差事由（如「深圳客户拜访之行」），不要出现「之旅」「游」等旅游措辞。
""",
    "meeting": """\

【场景规则：会议/参展】
- 围绕会程时间表排期：参会/布展/撤展为主体活动；【禁止】生成景点旅游活动。
- 布展日预留布展缓冲时间，撤展日预留物流打包时间；住宿选场馆附近。
""",
    "visit": """\

【场景规则：客户拜访】
- 按客户约见时间排期，拜访/商务宴请为主体；【禁止】生成景点旅游活动。
- 拜访前预留通勤与准备缓冲；住宿默认选客户地附近。
""",
    "team": """\

【场景规则：团队出行】
- 统一集合节奏：明确集合时间地点，含集体活动与住宿分配说明。
- 团建/培训类活动优先；个人自由活动时段需显式标注。
""",
    "personal": """\

【场景规则：个人出游】
- 单日景点 (attraction) 不超过 4 个，避免行程过载。
- 亲子场景 (同行人含 child): 每日安排 1~2 个休息 (rest) 时段，活动节奏放缓。
- 老人同行 (elder): 减少高强度步行，景点间优先短途交通。
""",
}

_SCENE_NAMES = {
    "business": "商务出差", "meeting": "会议参展",
    "visit": "客户拜访", "team": "团队出行", "personal": "个人出游",
}

# 城际交通方式（v2.1：用户可选，默认飞机；确认页可更换）
_TRANSPORT_NAMES = {"airplane": "飞机", "train": "高铁/火车", "drive": "自驾"}
_TRANSPORT_ALIASES = {
    "飞机": "airplane", "航班": "airplane", "flight": "airplane", "plane": "airplane", "坐飞机": "airplane",
    "高铁": "train", "火车": "train", "动车": "train", "rail": "train", "train": "train",
    "自驾": "drive", "开车": "drive", "driving": "drive", "car": "drive",
}


def normalize_transport(value) -> str:
    """交通方式归一化：别名/中英文 → airplane/train/drive；不识别返回空串（由默认兜底）。"""
    v = str(value or "").strip().lower()
    if v in _TRANSPORT_NAMES:
        return v
    return _TRANSPORT_ALIASES.get(v, "")


def scene_rules(scene: str) -> str:
    """按场景返回规则块；未知场景默认个人出游（旅游节奏）。"""
    return _SCENE_RULES.get((scene or "").strip(), _SCENE_RULES["personal"])


def planning_rules(scene: str) -> str:
    """v2：基础规则 + 场景规则 + 输出格式（PLANNING_RULES 按 scene 动态拼装）。"""
    return PLANNING_RULES_BASE + scene_rules(scene) + _OUTPUT_FORMAT


_OUTPUT_FORMAT = """\

【输出格式】严格输出 JSON 对象，结构如下:
{
  "title": "行程标题",
  "destination": "目的地城市",
  "origin": "出发城市",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "budget_total": 5000,
  "travel_party": [
    {"name": "姓名", "role": "adult|child|elder|business", "age": 30}
  ],
  "days": [
    {
      "date": "YYYY-MM-DD",
      "theme": "当日主题",
      "activities": [
        {
          "time_start": "09:00",
          "time_end": "11:30",
          "type": "attraction|transport|dining|accommodation|shopping|rest|meeting|other",
          "title": "活动名称",
          "location": {"name": "地点名", "lat": 0.0, "lng": 0.0, "address": "地址"},
          "ticket_price": 0,
          "booking_required": false,
          "tips": "注意事项",
          "estimated_cost": 0
        }
      ]
    }
  ],
  "checklist": ["证件类: 身份证/护照", "衣物类: ..."]
}

只输出 JSON，不要任何解释性文字。\
"""

# 兼容保留：personal 场景的完整规则（tests / 老调用方引用）
PLANNING_RULES = PLANNING_RULES_BASE + _SCENE_RULES["personal"] + _OUTPUT_FORMAT

# 必填参数（缺失必须澄清，不得生成）—— PRD v2 §4.1
REQUIRED_PARAMS = ("scene", "destination", "start_date", "days")
# 允许代填的参数（兜底补默认并记入 defaulted，由用户确认页展示）
AUTOFILL_PARAMS = ("origin", "num_adults", "budget_total")


class ItineraryGenerator:
    """
    行程生成器

    用法:
        llm = LLMManager()
        llm.register("openai_compatible", api_key="...", base_url="...", model="...")
        gen = ItineraryGenerator(llm)
        trip_dict = gen.generate("下周末去杭州玩两天，两大一小")
    """

    def __init__(self, llm_manager: LLMManager, guide_store=None):
        self.llm = llm_manager
        self.model: Optional[str] = None  # 前端选择的模型（可选，缺省用注册配置）
        # 景点/攻略语料库（可选）。仅个人出游场景用于 RAG 召回，注入生成提示词。
        self.guide_store = guide_store
        # 埋点：每个阶段耗时 + LLM 调用统计，由 API 层在 SSE done 帧前发出 timing 帧
        self._phase_timings: dict = {}
        self._last_guides: list = []

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def generate(self, query: str, preferences: dict = None, explicit: dict = None, carry: dict = None):
        """
        生成完整行程 (非流式)。

        Args:
            query: 用户自然语言需求，如 "8月20日去成都三日游，亲子"
            preferences: 偏好补充 (budget、style、dietary 等)
            explicit: 用户已确认的结构化参数（scene/日期等，优先级高于 LLM 抽取）
            carry: 澄清轮次已抽取的参数（低优先级续用，避免多轮上下文丢失）

        Returns:
            Trip.to_dict() —— 行程字典；必填缺失时返回 None（last_missing 为缺参清单）
        """
        preferences = preferences or {}
        self._phase_timings = {}
        self.last_missing: list = []
        self.last_params: dict = {}
        self.last_defaulted: list = []
        self._last_guides: list = []

        if not self.llm.is_available():
            logger.info("LLM 不可用，使用演示模式生成行程")
            demo = self._demo_generate(query, preferences)
            self.last_params = {"scene": "personal", "destination": demo.get("destination", "")}
            return self._attach_external(demo, self._empty_ext())

        try:
            # 阶段一：提取参数（v2：显式参数合并 + 缺参判定 + 代填记录）
            t0 = time.monotonic()
            params, missing, defaulted = self._extract_params(query, preferences, explicit, carry)
            llm_stats = getattr(self, "_extract_llm_stats", None) or self.llm.get_last_stats() or {}
            self._phase_timings["extract"] = {
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "llm": llm_stats,
            }
            self.last_params, self.last_missing, self.last_defaulted = params, missing, defaulted
            logger.info(f"参数提取完成: {params} missing={missing}")

            # 必填缺失 → 不生成，由 API 层发 clarify 澄清帧（PRD v2 §4.1）
            if missing:
                return None

            # 阶段一·五：外部数据 enrichment（腾讯地图地理编码/路线、和风天气、酒店 POI）
            # 失败一律 None 兜底，绝不阻断生成
            ext = self._enrich_external(params)
            self._current_ext = ext

            # 阶段二：生成行程
            # v3 模板直出（商务类场景，0 LLM）：未覆盖再走大模型
            t0 = time.monotonic()
            template_trip = build_trip_from_template(params, preferences, query)
            if template_trip is not None:
                self._sync_template_budget_defaulted(template_trip)
                template_trip["scene"] = params.get("scene") or "personal"
                template_trip["purpose"] = params.get("purpose") or ""
                self._phase_timings["generate"] = {
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "llm": {"mode": "template", "skipped": True},
                }
                return self._attach_external(template_trip, ext)

            trip_dict = self._generate_trip(params, query, preferences, ext)
            llm_stats = self.llm.get_last_stats() or {}
            self._phase_timings["generate"] = {
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "llm": llm_stats,
            }
            return trip_dict

        except Exception as e:
            logger.error(f"行程生成失败，降级到演示模式: {e}")
            demo = self._demo_generate(query, preferences)
            return self._attach_external(demo, self._empty_ext())

    def generate_stream(
        self, query: str, preferences: dict = None, explicit: dict = None, carry: dict = None
    ) -> Generator[str, None, None]:
        """
        流式生成行程。

        先非流式提取参数，再流式输出行程 JSON 文本。
        每个文本块通过 yield 返回。流结束后内部解析完整文本为 Trip 对象，
        解析结果挂到 self._last_trip 供调用方 (API 层) 处理。

        v2 语义：产出「草案」——必填参数缺失时不生成（last_missing 供 API 发
        clarify 帧）；生成完成也不落库、不触发审批，由调用方确认后走 confirm。

        Args:
            query: 用户自然语言需求
            preferences: 偏好补充
            explicit: 用户已确认的结构化参数
            carry: 澄清轮次已抽取的参数（低优先级续用）

        Yields:
            str —— 行程 JSON 的文本片段
        """
        preferences = preferences or {}
        self._last_trip: Optional[dict] = None
        self.last_error: Optional[str] = None
        self.last_missing: list = []
        self.last_params: dict = {}
        self.last_defaulted: list = []
        self._phase_timings = {}
        self._last_guides = []
        gen_started_at = time.monotonic()

        if not self.llm.is_available():
            logger.info("LLM 不可用，流式演示模式")
            demo = self._demo_generate(query, preferences)
            demo = self._attach_external(demo, self._empty_ext())
            self.last_params = {"scene": "personal", "destination": demo.get("destination", "")}
            text = json.dumps(demo, ensure_ascii=False, indent=2)
            # 模拟分块输出
            chunk_size = 80
            for i in range(0, len(text), chunk_size):
                yield text[i:i + chunk_size]
            self._last_trip = demo
            return

        try:
            # 阶段一：提取参数 (v2 + 埋点；v3 规则抽取命中时 0 LLM)
            t0 = time.monotonic()
            params, missing, defaulted = self._extract_params(query, preferences, explicit, carry)
            llm_stats = getattr(self, "_extract_llm_stats", None) or self.llm.get_last_stats() or {}
            self._phase_timings["extract"] = {
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "llm": llm_stats,
            }
            self.last_params, self.last_missing, self.last_defaulted = params, missing, defaulted
            logger.info(f"流式参数提取完成: {params} missing={missing}")

            # 必填缺失 → 不生成（API 层据此发 clarify 帧）
            if missing:
                return

            # 阶段一·五：外部数据 enrichment（腾讯地图/和风），失败不阻断
            ext = self._enrich_external(params)
            self._current_ext = ext

            # 阶段二：行程生成
            # v3 模板直出：商务类场景行程结构固定（去程→入住→拜访/会议→返程），
            # 骨架由代码确定性拼装（0 LLM 调用，毫秒级），大模型只负责阶段一抽参。
            # 生成耗时从 ~17s 降到 ~2s（仅剩抽参）。personal 或模板未覆盖（返回
            # None）→ 回退大模型流式生成。
            t0 = time.monotonic()
            template_trip = build_trip_from_template(params, preferences, query)
            if template_trip is not None:
                self._sync_template_budget_defaulted(template_trip)
                self._phase_timings["generate"] = {
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "llm": {"mode": "template", "skipped": True},
                }
                text = json.dumps(template_trip, ensure_ascii=False, indent=2)
                for i in range(0, len(text), 80):
                    yield text[i:i + 80]
                t_parse = time.monotonic()
                template_trip["scene"] = params.get("scene") or "personal"
                template_trip["purpose"] = params.get("purpose") or ""
                template_trip = self._attach_external(template_trip, ext)
                self._phase_timings["parse"] = {
                    "duration_ms": int((time.monotonic() - t_parse) * 1000),
                    "text_len": len(text),
                }
                self._last_trip = template_trip
                self._phase_timings["total"] = {
                    "duration_ms": int((time.monotonic() - gen_started_at) * 1000),
                }
                return

            # 阶段二：流式生成 (埋点 first_chunk_ms / 总耗时)
            t0 = time.monotonic()
            messages = self._build_generation_prompt(params, query, preferences, ext)
            full_text = ""
            for chunk in self.llm.chat_stream(messages, temperature=0.4, max_tokens=8192, model=self.model):
                full_text += chunk
                yield chunk
            llm_stats = self.llm.get_last_stats() or {}
            self._phase_timings["generate"] = {
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "llm": llm_stats,
            }

            # 解析完整文本（非 LLM；记录耗时便于判断 JSON 解析是否成瓶颈）
            t0 = time.monotonic()
            trip_dict = self._parse_trip_text(full_text, params, preferences)
            trip_dict["scene"] = params.get("scene") or "personal"
            trip_dict["purpose"] = params.get("purpose") or ""
            trip_dict = self._attach_external(trip_dict, ext)
            self._phase_timings["parse"] = {
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "text_len": len(full_text),
            }
            self._last_trip = trip_dict

            self._phase_timings["total"] = {
                "duration_ms": int((time.monotonic() - gen_started_at) * 1000),
            }

        except Exception as e:
            logger.error(f"流式生成失败: {e}")
            # 不向正文流 yield 错误 JSON（会混入行程文本导致解析失败），
            # 记录错误并降级演示行程，由 API 层根据 last_error 发独立 error 帧
            self.last_error = str(e)
            self._last_trip = self._attach_external(
                self._demo_generate(query, preferences), self._empty_ext()
            )
            self._phase_timings["error"] = {"message": str(e)}

    def _sync_template_budget_defaulted(self, template_trip: dict) -> None:
        """模板直出估算了预算时，同步代填记录口径（确认页展示「按模板估算」）。

        用户明确给了预算时 trip.budget_estimated 为 False，代填记录不动。
        """
        if not template_trip.get("budget_estimated"):
            return
        est = template_trip.get("budget_total") or 0
        self.last_defaulted = [
            d if d.get("field") != "budget_total" else {
                "field": "budget_total",
                "value": est,
                "note": "未提及预算，按模板标准估算（往返大交通+住宿+餐饮+市内交通），确认页可调整",
            }
            for d in self.last_defaulted
        ]

    # ------------------------------------------------------------------
    # Prompt 构建
    # ------------------------------------------------------------------
    def _build_extraction_prompt(self, query: str, preferences: dict = None, explicit: dict = None) -> list:
        """构建参数提取 prompt（v2）——示例即「未提及=null」，杜绝诱导默认值。"""
        preferences = preferences or {}
        today = datetime.now().strftime("%Y-%m-%d")

        system = (
            "你是行程参数提取助手。从用户的自然语言需求中提取结构化行程参数。\n"
            f"今天是 {today}，请据此推断「下周末」「下个月」等相对日期为绝对日期 (YYYY-MM-DD)。\n"
            "铁律：用户没有明确提到的字段一律填 null，禁止猜测、禁止编造默认值。"
            "天数/日期只有在用户明确说了（含「3天」「下周一到周三」这类表达）才能填。"
            "只输出 JSON，不要解释。"
        )
        user = f"""请从以下需求中提取行程参数，输出 JSON:
{{
  "scene": "business|meeting|visit|team|personal (出行场景，用户未明确说出差/开会/拜访/团建/游玩时不猜，填 null)",
  "destination": "目的地城市 (未提及则为 null)",
  "origin": "出发城市 (未提及则为 null)",
  "transport": "airplane|train|drive (城际交通方式；用户提到飞机/航班填 airplane，高铁/火车/动车填 train，自驾/开车填 drive，未提及则为 null)",
  "start_date": "YYYY-MM-DD (未提及则为 null)",
  "end_date": "YYYY-MM-DD (未提及则为 null)",
  "days": "整数天数 (未提及则为 null)",
  "purpose": "出差事由/拜访对象/会议名称 (未提及则为 null)",
  "num_adults": "成人数 (未提及则为 null)",
  "num_children": "儿童数 (未提及则为 null)",
  "num_elders": "老人数 (未提及则为 null)",
  "budget_total": "预算金额 (未提及则为 null)",
  "dietary": ["饮食偏好 (未提及则为空数组)"],
  "notes": "其他备注 (未提及则为 null)"
}}

用户需求: {query}
补充偏好: {json.dumps(preferences, ensure_ascii=False)}
"""
        if explicit:
            user += (
                "\n【用户已确认提供的参数（以此为准，无需再从需求中推断）】\n"
                f"{json.dumps(explicit, ensure_ascii=False)}\n"
            )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _build_generation_prompt(
        self, params: dict, query: str, preferences: dict = None, ext: dict = None
    ) -> list:
        """构建行程生成 prompt，让 LLM 生成结构化行程 JSON。"""
        preferences = preferences or {}

        party_desc = self._describe_party(params)
        scene = params.get("scene") or "personal"
        user = f"""请根据以下参数生成完整行程。

【用户原始需求】
{query}

【提取参数（生成内容必须全部来源于这些参数，禁止臆造）】
场景: {_SCENE_NAMES.get(scene, scene)}
目的地: {params.get('destination') or '未指定'}
出发地: {params.get('origin') or '未指定（交通自理）'}
交通方式: {_TRANSPORT_NAMES.get(params.get('transport') or 'airplane', '飞机')}（往返大交通与首末日活动必须与该方式匹配：飞机=航班与机场往返衔接；高铁/火车=车次与车站往返衔接；自驾=参考驾车里程与驾驶时间安排途中休息）
日期: {params.get('start_date', '?')} ~ {params.get('end_date', '?')}（{params.get('days', '?')} 天）
事由: {params.get('purpose') or '未提及'}
同行人: {party_desc}
预算: {'¥' + str(params['budget_total']) if params.get('budget_total') else '按差旅标准'}
饮食偏好: {', '.join(params.get('dietary') or []) or '无特殊'}
备注: {params.get('notes') or ''}

【补充偏好】
{json.dumps(preferences, ensure_ascii=False)}
"""
        # 外部实时数据注入（有 key 且调用成功才注入，否则仅附注未接入）
        if ext:
            user += self._external_prompt_block(ext, params)

        # 景点/攻略语料注入（仅个人出游召回；商务/会议/拜访/团队为空，不污染提示词）
        self._last_guides = self._retrieve_guides(params)
        if self._last_guides:
            user += self._guide_prompt_block(self._last_guides)

        user += "\n请严格按规则与输出格式生成行程 JSON。\\"
        return [
            {"role": "system", "content": planning_rules(scene)},
            {"role": "user", "content": user},
        ]

    # ------------------------------------------------------------------
    # 外部数据 enrichment（腾讯地图 / 和风）
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_ext() -> dict:
        """空占位（无 key / 降级时挂在行程单上，结构保持一致）。"""
        return {"geo": {}, "route": None, "weather": None, "hotels": None, "real": False}

    def _enrich_external(self, params: dict) -> dict:
        """调用腾讯地图/和风获取实时地理、天气、酒店数据，供生成提示词与行程单使用。

        任何外部调用失败均返回 None。返回结构:
          {
            "geo": {"origin": {...}, "destination": {...}},
            "route": {"distance_km", "duration_min"} | None,
            "weather": [day...] | None,
            "hotels": [hotel...] | None,
            "real": bool   # 是否配置了任一 key（用于决定注入/标注）
          }
        """
        tm = TencentMapClient()
        qweather = QWeatherClient()
        result = {"geo": {}, "route": None, "weather": None, "hotels": None, "real": False}
        try:
            origin = params.get("origin")
            dest = params.get("destination")
            if origin:
                g = tm.geocode(origin)
                if g:
                    result["geo"]["origin"] = g
            if dest:
                g = tm.geocode(dest)
                if g:
                    result["geo"]["destination"] = g
            if result["geo"].get("origin") and result["geo"].get("destination"):
                result["route"] = tm.driving_route(
                    result["geo"]["origin"], result["geo"]["destination"]
                )
            if dest:
                result["weather"] = qweather.forecast_7d(dest)
                result["hotels"] = tm.poi_hotels(
                    city=dest, geo=result["geo"].get("destination")
                )
            result["real"] = bool(settings.tencent_map_key or settings.weather_api_key)
            logger.info(
                f"外部数据 enrichment: geo_keys={list(result['geo'].keys())}, "
                f"route={result['route'] is not None}, "
                f"weather={result['weather'] is not None}, "
                f"hotels={result['hotels'] is not None}, real={result['real']}"
            )
        except Exception as e:
            logger.warning(f"外部数据 enrichment 异常（不影响生成）: {e}")
        return result

    def _external_prompt_block(self, ext: dict, params: dict) -> str:
        """把外部实时数据拼成提示词约束段。"""
        if not ext.get("real"):
            return (
                "\n【外部实时数据】未配置腾讯地图/和风天气 API Key，"
                "本行程未参考实时地图、天气与酒店数据，请勿编造具体天气或酒店信息。\n"
            )
        lines = ["\n【外部实时数据（务必参考，但仅作规划依据，不要原样输出原始坐标）】"]

        geo = ext.get("geo", {})
        if geo.get("origin"):
            o = geo["origin"]
            lines.append(f"- 出发地「{params.get('origin', '')}」坐标: {o['lng']},{o['lat']}")
        if geo.get("destination"):
            d = geo["destination"]
            lines.append(f"- 目的地「{params.get('destination', '')}」坐标: {d['lng']},{d['lat']}")
        if ext.get("route"):
            r = ext["route"]
            lines.append(f"- 出发地→目的地驾车约 {r['distance_km']} km / {r['duration_min']} 分钟")

        weather = ext.get("weather")
        if weather:
            lines.append("- 目的地逐日天气预报（恶劣天气日避免安排户外景点，改室内备选，并在 tips 注明天气）：")
            for w in weather:
                lines.append(
                    f"  · {w['date']} {w['cond_day']}（{w['temp_min']}~{w['temp_max']}°C）"
                )

        hotels = ext.get("hotels")
        if hotels:
            lines.append("- 推荐酒店候选（住宿优先从以下选择，标注「推荐酒店」，价格/余量以实际预订为准）：")
            for h in hotels:
                addr = f"（{h['address']}）" if h.get("address") else ""
                lines.append(f"  · {h['name']}{addr}")

        return "\n".join(lines) + "\n"

    def _attach_external(self, trip_dict: dict, ext: dict) -> dict:
        """把外部数据挂到行程字典（落库 + 前端展示）。"""
        if not isinstance(trip_dict, dict):
            return trip_dict
        ext = ext or {}
        trip_dict["geo"] = ext.get("geo", {})
        trip_dict["route"] = ext.get("route")
        trip_dict["weather_forecast"] = ext.get("weather")
        trip_dict["hotel_options"] = ext.get("hotels")
        trip_dict["external_data"] = {"real": bool(ext.get("real", False))}

        # 景点语料引用（仅个人出游召回时有值，供前端展示「内容依据」）
        guides = getattr(self, "_last_guides", None) or []
        if guides:
            trip_dict["guide_refs"] = [
                {
                    "guide_id": g.get("guide_id"),
                    "title": g.get("title"),
                    "category": g.get("category"),
                    "source": g.get("source", ""),
                }
                for g in guides
            ]
        return trip_dict

    # ------------------------------------------------------------------
    # 景点/攻略语料 RAG（C 端个人出游）
    # ------------------------------------------------------------------
    def _retrieve_guides(self, params: dict, top_k: int = 5) -> list:
        """按目的地召回景点/攻略语料。

        仅 scene=personal 启用：商务/会议/拜访/团队场景禁景点，注入语料只会
        污染提示词。embedding 可用走向量语义检索，不可用自动降级关键词检索。
        任何异常返回空列表，绝不阻断生成。
        """
        if not self.guide_store:
            return []
        scene = str(params.get("scene") or "personal").strip().lower()
        if scene != "personal":
            return []
        dest = str(params.get("destination") or "").strip()
        if not dest:
            return []

        query = dest
        notes = str(params.get("notes") or "").strip()
        if notes:
            query = f"{dest} {notes}"

        try:
            embedder = get_embedder()
            if embedder and embedder.available:
                self.guide_store.index_missing_embeddings(embedder)
                docs = self.guide_store.vector_search(query, embedder=embedder, top_k=top_k)
                if docs:
                    logger.info(f"景点语料召回(vector): {[d.get('title') for d in docs]}")
                    return docs
            docs = self.guide_store.search_by_keyword(dest)[:top_k]
            logger.info(f"景点语料召回(keyword): {[d.get('title') for d in docs]}")
            return docs
        except Exception as e:
            logger.warning(f"景点语料召回失败（不影响生成）: {e}")
            return []

    def _guide_prompt_block(self, guides: list) -> str:
        """把景点/攻略语料拼成提示词约束段。"""
        if not guides:
            return ""
        lines = [
            "\n【景点/攻略语料（行程中的景点应优先从以下语料选择，门票/建议时长/预约要求以此为准；"
            "语料未覆盖的景点不要编造具体票价与预约方式，只写不确定项并在 tips 提示自行核实）】"
        ]
        for g in guides:
            title = g.get("title") or ""
            excerpt = g.get("excerpt") or make_excerpt(g.get("content", ""))
            lines.append(f"- {title}：{excerpt}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # 内部: 提取与生成
    # ------------------------------------------------------------------
    def _extract_params(self, query: str, preferences: dict, explicit: dict = None, carry: dict = None):
        """v2 参数提取：LLM 抽取 → 显式参数合并 → 澄清轮次参数续用 → 缺参判定 → 可代填兜底。

        取值优先级：explicit（确认页显式参数）> LLM 本轮抽取 > carry（前几轮澄清已抽取值）。

        Returns:
            (params, missing, defaulted)
              params     合并后的完整参数 dict（可代填字段已兜底）
              missing    必填缺失清单（scene/destination/start_date/days），非空则不得生成
              defaulted  代填记录 [{field, value, note}]，由确认页以 [代填] 展示
        """
        explicit = {k: v for k, v in (explicit or {}).items() if v not in (None, "", [])}
        carry = {k: v for k, v in (carry or {}).items() if v not in (None, "", [])}

        raw = {}
        llm_stats = {}
        if explicit and all(explicit.get(k) for k in REQUIRED_PARAMS):
            # 显式参数已覆盖全部必填（确认页改参重生成等）→ 无需任何抽取调用
            llm_stats = {"mode": "explicit", "skipped": True}
        elif self.llm.is_available():
            # v3 两级抽取：常见差旅句式走规则直取（0 LLM，毫秒级）；
            # 命中不全才回退大模型（复杂句式/相对日期仍可靠）。不混拼两套口径。
            fast = fast_extract_params(query)
            if fast_covers_required(fast):
                raw = fast
                llm_stats = {"mode": "fast_regex", "skipped": True}
            else:
                messages = self._build_extraction_prompt(query, preferences, explicit)
                raw = self.llm.chat_json(messages, temperature=0.1, max_tokens=1024, model=self.model) or {}

        def pick(field):
            """字段取值：显式参数 > LLM 提取 > 澄清轮次续用；空/null 视为未提供。"""
            if field in explicit:
                return explicit[field]
            v = raw.get(field)
            if v in (None, "", [], "null"):
                return carry.get(field)
            return v

        params = {
            "scene": pick("scene"),
            "destination": pick("destination"),
            "origin": pick("origin"),
            "transport": pick("transport"),
            "start_date": pick("start_date"),
            "end_date": pick("end_date"),
            "days": pick("days"),
            "purpose": pick("purpose"),
            "num_adults": pick("num_adults"),
            "num_children": pick("num_children"),
            "num_elders": pick("num_elders"),
            "budget_total": pick("budget_total"),
            "dietary": pick("dietary") or [],
            "notes": pick("notes") or "",
        }
        params["scene"] = params["scene"] if params["scene"] in _SCENE_NAMES else None
        params["transport"] = normalize_transport(params.get("transport"))

        # 日期/天数归一：days 与 (start_date,end_date) 二选一即可满足
        try:
            if params.get("days") is not None:
                params["days"] = max(1, int(params["days"]))
        except (TypeError, ValueError):
            params["days"] = None
        if params.get("start_date") and not params.get("end_date") and params.get("days"):
            try:
                start = datetime.strptime(str(params["start_date"]), "%Y-%m-%d")
                params["end_date"] = (start + timedelta(days=params["days"] - 1)).strftime("%Y-%m-%d")
            except ValueError:
                params["end_date"] = None
        if params.get("start_date") and params.get("end_date") and not params.get("days"):
            try:
                s = datetime.strptime(str(params["start_date"]), "%Y-%m-%d")
                e = datetime.strptime(str(params["end_date"]), "%Y-%m-%d")
                params["days"] = max(1, (e - s).days + 1)
            except ValueError:
                pass

        # 1) 必填缺失 → 澄清（PRD v2 §4.1：不得生成）
        missing = []
        if not params.get("scene"):
            missing.append("scene")
        if not params.get("destination"):
            missing.append("destination")
        if not params.get("start_date"):
            missing.append("start_date")
        if not params.get("days"):
            missing.append("days")

        # 2) 可代填字段兜底（有明确规则，非模型自由发挥），记入 defaulted 供确认页展示
        defaulted = []
        if params.get("num_adults") is None and not any(
            params.get(k) for k in ("num_children", "num_elders")
        ):
            params["num_adults"] = 1
            defaulted.append({"field": "num_adults", "value": 1, "note": "未提及人数，默认 1 人"})
        if params.get("budget_total") is None:
            params["budget_total"] = 0
            defaulted.append({"field": "budget_total", "value": 0, "note": "未提及预算，按差旅标准核算"})
        if not params.get("origin"):
            params["origin"] = ""
            defaulted.append({"field": "origin", "value": "未填写", "note": "未提及出发地，交通信息自理"})
        if not params.get("transport"):
            params["transport"] = "airplane"
            defaulted.append({"field": "transport", "value": "airplane", "note": "默认飞机，确认页可更换"})

        # 抽取阶段 LLM 状态（fast_regex / explicit 时为 skipped，调用方埋点用）
        self._extract_llm_stats = llm_stats
        return params, missing, defaulted

    @staticmethod
    def build_clarify_question(missing: list, params: dict) -> str:
        """按缺失清单生成澄清话术（PRD v2 §6.2 模板，确定性拼接，不依赖 LLM）。"""
        dest = params.get("destination") or "目的地"
        questions = []
        if "scene" in missing:
            questions.append(
                f"请问这次去{dest}是？商务出差 / 会议参展 / 客户拜访 / 团队出行 / 个人出游"
            )
        if "destination" in missing:
            questions.append("请问目的地是哪里？")
        if "start_date" in missing or "days" in missing:
            questions.append("计划哪几天去？可以说「下周一」「9/7-9/9」或「3 天」这样的表达。")
        return "为了帮你排出合适的行程，请补充几个信息：\n" + "\n".join(
            f"{i}. {q}" for i, q in enumerate(questions, 1)
        )

    def _generate_trip(
        self, params: dict, query: str, preferences: dict, ext: dict = None
    ) -> dict:
        """非流式生成行程，解析为 Trip 字典。"""
        messages = self._build_generation_prompt(params, query, preferences, ext)
        text = self.llm.chat(
            messages, temperature=0.3, model=self.model,
            max_tokens=8192, response_format={"type": "json_object"},
        )
        trip_dict = self._parse_trip_text(text, params, preferences)
        trip_dict["scene"] = params.get("scene") or "personal"
        trip_dict["purpose"] = params.get("purpose") or ""
        return self._attach_external(trip_dict, ext or self._empty_ext())

    def _parse_trip_text(
        self, text: str, params: dict, preferences: dict
    ) -> dict:
        """将 LLM 输出文本解析为 Trip.to_dict()。"""
        data = self._safe_json_loads(text)
        if data is None:
            # 五层容错全失败 → 请模型修补一次（长输出被截断时的最后一根稻草）
            data = self._repair_json_with_llm(text)
        if data is None:
            logger.warning("LLM 输出 JSON 解析失败（含 LLM 修补），降级到演示模式")
            return self._demo_generate(params.get("notes") or "", preferences)

        # 构建 Trip 对象
        trip = Trip(
            title=data.get("title", f"{data.get('destination', '未命名')}行程"),
            destination=data.get("destination", params.get("destination", "")),
            origin=data.get("origin", params.get("origin", "")),
            start_date=data.get("start_date", params.get("start_date", "")),
            end_date=data.get("end_date", params.get("end_date", "")),
            budget_total=float(data.get("budget_total", params.get("budget_total", 0)) or 0),
        )

        # travel_party
        for m in data.get("travel_party", []):
            trip.travel_party.append(TravelPartyMember(
                name=m.get("name", ""),
                role=m.get("role", "adult"),
                age=int(m.get("age", 0) or 0),
            ))

        # days / activities
        for day_data in data.get("days", []):
            day = TripDay(
                date=day_data.get("date", ""),
                theme=day_data.get("theme", ""),
            )
            for act_data in day_data.get("activities", []):
                loc_data = act_data.get("location", {}) or {}
                activity = Activity(
                    time_start=act_data.get("time_start", ""),
                    time_end=act_data.get("time_end", ""),
                    type=act_data.get("type", "other"),
                    title=act_data.get("title", ""),
                    location=Location(
                        name=loc_data.get("name", ""),
                        lat=float(loc_data.get("lat", 0) or 0),
                        lng=float(loc_data.get("lng", 0) or 0),
                        address=loc_data.get("address", ""),
                    ),
                    description=act_data.get("description", ""),
                    ticket_price=float(act_data.get("ticket_price", 0) or 0),
                    booking_required=bool(act_data.get("booking_required", False)),
                    booking_url=act_data.get("booking_url", ""),
                    tips=act_data.get("tips", ""),
                    estimated_cost=float(act_data.get("estimated_cost", 0) or 0),
                )
                day.activities.append(activity)
            trip.days.append(day)

        # checklist
        trip.checklist = data.get("checklist", [])
        trip.preferences = preferences

        return trip.to_dict()

    # ------------------------------------------------------------------
    # 演示降级模式
    # ------------------------------------------------------------------
    def _demo_generate(self, query: str, preferences: dict) -> dict:
        """无 LLM 时的示例行程模板 (基于 query 简单推断)。"""
        dest = self._guess_destination(query)
        today = datetime.now()
        start = today + timedelta(days=7 - today.weekday())  # 下周一
        days_count = self._guess_days(query)
        end = start + timedelta(days=days_count - 1)

        trip = Trip(
            title=f"{dest}{days_count}日游 (演示行程)",
            destination=dest,
            origin="北京",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            budget_total=days_count * 1200,
        )
        trip.travel_party.append(TravelPartyMember(name="出行人", role="adult", age=30))

        templates = self._demo_day_templates(dest)
        for i in range(days_count):
            date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            tmpl = templates[i % len(templates)]
            day = TripDay(date=date, theme=tmpl["theme"])
            for act in tmpl["activities"]:
                day.activities.append(Activity(
                    time_start=act["time_start"],
                    time_end=act["time_end"],
                    type=act["type"],
                    title=act["title"],
                    location=Location(name=act["location"]),
                    ticket_price=act.get("ticket_price", 0),
                    booking_required=act.get("booking_required", False),
                    tips=act.get("tips", ""),
                    estimated_cost=act.get("estimated_cost", 0),
                ))
            trip.days.append(day)

        trip.checklist = [
            "证件类: 身份证 (儿童带户口本)",
            "衣物类: 适合当季的换洗衣物、舒适步行鞋",
            "电子设备: 手机充电器、充电宝、数据线",
            "药品类: 常用感冒药、肠胃药、创可贴",
            "其他: 雨伞、水杯、少量现金",
        ]
        trip.preferences = preferences
        demo = trip.to_dict()
        # 演示模板本身是「旅游节奏」，显式标成 personal：否则 API 层拿不到 scene，
        # 会按企业差旅走政策预检（把「政策预检通过」这类术语漏进个人行程）
        demo.setdefault("scene", "personal")
        return demo

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_json_loads(text: str) -> Optional[dict]:
        """容错 JSON 解析（委托 shared.llm.json_repair 五层链路）。

        历史：早期只做「去围栏 + json.loads + 正则提取第一个大括号」两档，
        遇到大模型长输出被 max_tokens 截断（尾括号缺失）或值内部含未转义
        裸引号时必然失败，直接降级演示行程 —— 明明模型已生成 90% 正确内容。
        现改为五层容错：基础清理 → 区间切片 → 修复未转义引号 → 截断修复 →
        截断+引号修复，全失败才由调用方走 LLM 修补 / 演示降级。
        """
        data, _ = parse_json_tolerant(text)
        return data

    def _repair_json_with_llm(self, text: str) -> Optional[dict]:
        """兜底：五层容错全失败后，请模型把损坏的 JSON 修好。

        只发一次请求，避免在"模型就是输出不了合法 JSON"的情况下放大失败与耗时。
        截断文本（长输出常超 8192 token），避免修补请求本身又超限。
        """
        if not text or not self.llm.is_available():
            return None
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是 JSON 修复器。用户会给你一段不合法的 JSON（可能被截断、"
                        "含未转义引号或混入说明文字）。请补全并修复为合法 JSON，"
                        "只输出 JSON 本身，不要解释、不要用 markdown 代码围栏。"
                    ),
                },
                {"role": "user", "content": text[:6000]},
            ]
            data = self.llm.chat_json(messages, temperature=0.0, max_tokens=4096, model=self.model)
            if isinstance(data, dict) and data:
                logger.info("LLM 修补 JSON 成功")
                return data
        except Exception as e:
            logger.warning(f"LLM 修补 JSON 失败: {e}")
        return None

    @staticmethod
    def _describe_party(params: dict) -> str:
        parts = []
        if params.get("num_adults"):
            parts.append(f"成人 {params['num_adults']} 人")
        if params.get("num_children"):
            parts.append(f"儿童 {params['num_children']} 人")
        if params.get("num_elders"):
            parts.append(f"老人 {params['num_elders']} 人")
        return "、".join(parts) if parts else "成人 1 人"

    @staticmethod
    def _guess_destination(query: str) -> str:
        candidates = ["北京", "上海", "杭州", "成都", "西安", "厦门", "丽江",
                      "苏州", "南京", "重庆", "广州", "深圳", "三亚", "青岛"]
        for c in candidates:
            if c in query:
                return c
        return "杭州"

    @staticmethod
    def _guess_days(query: str) -> int:
        m = re.search(r"(\d+)\s*[天日]", query)
        if m:
            return max(1, min(int(m.group(1)), 10))
        if "两" in query or "2" in query:
            return 2
        if "一周" in query or "七天" in query or "7天" in query:
            return 7
        return 3

    @staticmethod
    def _demo_day_templates(dest: str) -> list:
        """演示行程的每日模板。"""
        return [
            {
                "theme": f"{dest}初探",
                "activities": [
                    {"time_start": "09:00", "time_end": "10:00", "type": "transport",
                     "title": "前往市中心", "location": f"{dest}市中心", "estimated_cost": 50},
                    {"time_start": "10:00", "time_end": "12:30", "type": "attraction",
                     "title": f"{dest}标志性景点", "location": f"{dest}景区",
                     "ticket_price": 80, "booking_required": False, "estimated_cost": 80,
                     "tips": "建议提前在线购票"},
                    {"time_start": "12:30", "time_end": "14:00", "type": "dining",
                     "title": "当地特色午餐", "location": "老字号餐厅", "estimated_cost": 120},
                    {"time_start": "14:30", "time_end": "17:00", "type": "attraction",
                     "title": "文化博物馆", "location": "博物馆",
                     "ticket_price": 50, "booking_required": True, "estimated_cost": 50,
                     "tips": "需提前预约"},
                    {"time_start": "18:00", "time_end": "20:00", "type": "dining",
                     "title": "晚餐", "location": "商业街区", "estimated_cost": 150},
                ],
            },
            {
                "theme": "深度体验",
                "activities": [
                    {"time_start": "09:30", "time_end": "12:00", "type": "attraction",
                     "title": "自然风光游览", "location": "国家公园",
                     "ticket_price": 60, "estimated_cost": 60, "tips": "穿舒适步行鞋"},
                    {"time_start": "12:00", "time_end": "13:30", "type": "dining",
                     "title": "午餐", "location": "景区餐厅", "estimated_cost": 100},
                    {"time_start": "14:00", "time_end": "16:00", "type": "rest",
                     "title": "茶歇休息", "location": "茶馆", "estimated_cost": 60},
                    {"time_start": "16:30", "time_end": "18:30", "type": "shopping",
                     "title": "特色街区购物", "location": "步行街", "estimated_cost": 200},
                    {"time_start": "19:00", "time_end": "21:00", "type": "dining",
                     "title": "晚餐", "location": "夜市", "estimated_cost": 100},
                ],
            },
            {
                "theme": "休闲返程",
                "activities": [
                    {"time_start": "09:00", "time_end": "11:30", "type": "attraction",
                     "title": "晨间漫步", "location": "湖滨公园",
                     "ticket_price": 0, "estimated_cost": 0},
                    {"time_start": "12:00", "time_end": "13:30", "type": "dining",
                     "title": "告别午餐", "location": "本地餐厅", "estimated_cost": 120},
                    {"time_start": "14:00", "time_end": "15:00", "type": "transport",
                     "title": "前往车站/机场", "location": "交通枢纽", "estimated_cost": 50},
                ],
            },
        ]
