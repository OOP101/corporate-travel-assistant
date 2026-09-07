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

from shared.llm import LLMManager
from shared.config import settings
from shared.geo import TencentMapClient, QWeatherClient
from shared.models import (
    Trip, TripDay, Activity, ActivityType, TripStatus,
    Location, TravelPartyMember,
)

logger = logging.getLogger("planner-core.generators.itinerary")


# ---------------------------------------------------------------------------
# 行程规划规则 (系统提示词内嵌)
# ---------------------------------------------------------------------------
PLANNING_RULES = """\
你是「策程」AI 行程规划引擎，请严格遵循以下规划规则生成行程：

【节奏规则】
1. 单日景点 (attraction) 不超过 4 个，避免行程过载。
2. 相邻活动之间的通勤时间 (transport) 原则上 ≤ 30 分钟，超出需在 tips 中提示。
3. 每日用餐 (dining) 预留 1~1.5 小时；正餐安排在 11:30-13:00 与 17:30-19:00。
4. 每日首项活动建议 09:00 开始，末项不超过 22:00 结束。

【场景适配】
5. 亲子场景 (同行人含 child): 每日安排 1~2 个休息 (rest) 时段，活动节奏放缓。
6. 商务场景 (同行人含 role=business 或标题含「会议」): 保障 meeting 时段，预留缓冲。
7. 老人同行 (elder): 减少高强度步行，景点间优先短途交通。

【质量规则】
8. 时间段不得重叠，按时间升序排列。
9. location 必须含 name；能给出经纬度则填写 lat/lng (WGS84)，否则填 0。
10. booking_required=true 的活动 (如热门景点、演出) 须在 tips 中注明预约方式。
11. estimated_cost 为该项单人预估花费 (元)；ticket_price 为门票单价。
12. budget_total 应与各日合计大致吻合。

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


class ItineraryGenerator:
    """
    行程生成器

    用法:
        llm = LLMManager()
        llm.register("openai_compatible", api_key="...", base_url="...", model="...")
        gen = ItineraryGenerator(llm)
        trip_dict = gen.generate("下周末去杭州玩两天，两大一小")
    """

    def __init__(self, llm_manager: LLMManager):
        self.llm = llm_manager
        self.model: Optional[str] = None  # 前端选择的模型（可选，缺省用注册配置）
        # 埋点：每个阶段耗时 + LLM 调用统计，由 API 层在 SSE done 帧前发出 timing 帧
        self._phase_timings: dict = {}

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def generate(self, query: str, preferences: dict = None) -> dict:
        """
        生成完整行程 (非流式)。

        Args:
            query: 用户自然语言需求，如 "8月20日去成都三日游，亲子"
            preferences: 偏好补充 (budget、style、dietary 等)

        Returns:
            Trip.to_dict() —— 行程字典
        """
        preferences = preferences or {}
        self._phase_timings = {}

        if not self.llm.is_available():
            logger.info("LLM 不可用，使用演示模式生成行程")
            demo = self._demo_generate(query, preferences)
            return self._attach_external(demo, self._empty_ext())

        try:
            # 阶段一：提取参数（埋点：仅含 LLM 调用耗时 + token，不含 setdefault 兜底）
            t0 = time.monotonic()
            params = self._extract_params(query, preferences)
            llm_stats = self.llm.get_last_stats() or {}
            self._phase_timings["extract"] = {
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "llm": llm_stats,
            }
            logger.info(f"参数提取完成: {params}")

            # 阶段一·五：外部数据 enrichment（腾讯地图地理编码/路线、和风天气、酒店 POI）
            # 失败一律 None 兜底，绝不阻断生成
            ext = self._enrich_external(params)
            self._current_ext = ext

            # 阶段二：生成行程（chat_json 内含 chat 调用，stats 也已记录）
            t0 = time.monotonic()
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
        self, query: str, preferences: dict = None
    ) -> Generator[str, None, None]:
        """
        流式生成行程。

        先非流式提取参数，再流式输出行程 JSON 文本。
        每个文本块通过 yield 返回。流结束后内部解析完整文本为 Trip 对象，
        解析结果挂到 self._last_trip 供调用方 (API 层) 存入 TripStore。

        Args:
            query: 用户自然语言需求
            preferences: 偏好补充

        Yields:
            str —— 行程 JSON 的文本片段
        """
        preferences = preferences or {}
        self._last_trip: Optional[dict] = None
        self.last_error: Optional[str] = None
        self._phase_timings = {}
        gen_started_at = time.monotonic()

        if not self.llm.is_available():
            logger.info("LLM 不可用，流式演示模式")
            demo = self._demo_generate(query, preferences)
            demo = self._attach_external(demo, self._empty_ext())
            text = json.dumps(demo, ensure_ascii=False, indent=2)
            # 模拟分块输出
            chunk_size = 80
            for i in range(0, len(text), chunk_size):
                yield text[i:i + chunk_size]
            self._last_trip = demo
            return

        try:
            # 阶段一：提取参数 (非流式 + 埋点)
            t0 = time.monotonic()
            params = self._extract_params(query, preferences)
            llm_stats = self.llm.get_last_stats() or {}
            self._phase_timings["extract"] = {
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "llm": llm_stats,
            }
            logger.info(f"流式参数提取完成: {params}")

            # 阶段一·五：外部数据 enrichment（腾讯地图/和风），失败不阻断
            ext = self._enrich_external(params)
            self._current_ext = ext

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

    # ------------------------------------------------------------------
    # Prompt 构建
    # ------------------------------------------------------------------
    def _build_extraction_prompt(self, query: str, preferences: dict = None) -> list:
        """构建参数提取 prompt，用 LLM 提取目的地/日期/天数/人数/预算/偏好等。"""
        preferences = preferences or {}
        today = datetime.now().strftime("%Y-%m-%d")

        system = (
            "你是行程参数提取助手。从用户的自然语言需求中提取结构化行程参数。"
            f"今天是 {today}，请据此推断「下周末」「下个月」等相对日期为绝对日期 (YYYY-MM-DD)。"
            "只输出 JSON，不要解释。"
        )
        user = f"""请从以下需求中提取行程参数，输出 JSON:
{{
  "destination": "目的地城市 (未提及则为空)",
  "origin": "出发城市 (未提及则为空)",
  "start_date": "YYYY-MM-DD (未提及则推断近期)",
  "end_date": "YYYY-MM-DD (由天数推算)",
  "days": 3,
  "num_adults": 2,
  "num_children": 0,
  "num_elders": 0,
  "budget_total": 5000,
  "travel_style": "relaxed|compact|adventure|cultural|business (未提及则 cultural)",
  "dietary": ["素食", "无辣"],
  "interests": ["自然风光", "历史人文"],
  "notes": "其他备注"
}}

用户需求: {query}
补充偏好: {json.dumps(preferences, ensure_ascii=False)}
"""
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _build_generation_prompt(
        self, params: dict, query: str, preferences: dict = None, ext: dict = None
    ) -> list:
        """构建行程生成 prompt，让 LLM 生成结构化行程 JSON。"""
        preferences = preferences or {}

        party_desc = self._describe_party(params)
        user = f"""请根据以下参数生成完整行程。

【用户原始需求】
{query}

【提取参数】
目的地: {params.get('destination', '未指定')}
出发地: {params.get('origin', '未指定')}
日期: {params.get('start_date', '?')} ~ {params.get('end_date', '?')}
天数: {params.get('days', 3)} 天
同行人: {party_desc}
预算: ¥{params.get('budget_total', 5000)}
旅行风格: {params.get('travel_style', 'cultural')}
饮食偏好: {', '.join(params.get('dietary', [])) or '无特殊'}
兴趣偏好: {', '.join(params.get('interests', [])) or '无特殊'}
备注: {params.get('notes', '')}

【补充偏好】
{json.dumps(preferences, ensure_ascii=False)}
"""
        # 外部实时数据注入（有 key 且调用成功才注入，否则仅附注未接入）
        if ext:
            user += self._external_prompt_block(ext, params)

        user += "\n请严格按规则与输出格式生成行程 JSON。\\"
        return [
            {"role": "system", "content": PLANNING_RULES},
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
        return trip_dict

    # ------------------------------------------------------------------
    # 内部: 提取与生成
    # ------------------------------------------------------------------
    def _extract_params(self, query: str, preferences: dict) -> dict:
        """非流式提取行程参数。"""
        messages = self._build_extraction_prompt(query, preferences)
        params = self.llm.chat_json(messages, temperature=0.1, max_tokens=1024, model=self.model)

        # 兜底默认值
        params.setdefault("destination", "")
        params.setdefault("origin", "")
        params.setdefault("start_date", datetime.now().strftime("%Y-%m-%d"))
        params.setdefault("days", 3)
        params.setdefault("num_adults", 1)
        params.setdefault("num_children", 0)
        params.setdefault("num_elders", 0)
        params.setdefault("budget_total", 5000)
        params.setdefault("travel_style", "cultural")
        params.setdefault("dietary", [])
        params.setdefault("interests", [])

        # 推算 end_date
        if not params.get("end_date"):
            try:
                start = datetime.strptime(params["start_date"], "%Y-%m-%d")
                params["end_date"] = (start + timedelta(days=params["days"] - 1)).strftime("%Y-%m-%d")
            except Exception:
                params["end_date"] = params["start_date"]

        return params

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
        return self._attach_external(trip_dict, ext or self._empty_ext())

    def _parse_trip_text(
        self, text: str, params: dict, preferences: dict
    ) -> dict:
        """将 LLM 输出文本解析为 Trip.to_dict()。"""
        data = self._safe_json_loads(text)
        if data is None:
            logger.warning("LLM 输出 JSON 解析失败，降级到演示模式")
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
        return trip.to_dict()

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_json_loads(text: str) -> Optional[dict]:
        """容错 JSON 解析: 去除 markdown 代码块包裹后解析。"""
        if not text:
            return None
        text = text.strip()
        # 去除 ```json ... ``` 包裹
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取第一个 {...} 块
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None
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
