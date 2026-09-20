"""商务场景行程模板直出（固定框架 + 抽取参数填充）回归测试（2026-09-18）。

背景：商务差旅行程结构固定（去程→入住→拜访/会议→返程），此前每次都让
大模型从零推理整份行程 JSON（实测生成阶段 17.2s）。模板直出后生成阶段
0 次 LLM 调用，毫秒级完成；大模型只负责阶段一参数抽取（~2s）。

覆盖：
  1. 骨架完整性：3 天商务行程含去程/入住/拜访/返程，事由落位
  2. 禁景点铁律：商务类场景任何活动不得是 attraction
  3. 时间质量：时段不重叠、不越 23:59（对应规划规则【质量规则】）
  4. 形态覆盖：1 天压缩 / 2 天 / ≥3 天 / 下午出发 / 上午返程 / 高铁 / 多人
  5. 预算估算：未提及预算按固定口径估算并标记 budget_estimated；
     用户给了预算则原样使用
  6. personal 场景不走模板（返回 None，回退大模型生成路径）
  7. ItineraryGenerator 流式链路接入：business 走模板（生成阶段不调 LLM），
     personal 仍调 LLM

不依赖网络与真实 LLM，抽取用 FakeLLM 固定返回。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANNER_DIR = os.path.join(ROOT, "services", "planner-core")


@pytest.fixture(scope="module")
def template_mod():
    if PLANNER_DIR in sys.path:
        sys.path.remove(PLANNER_DIR)
    sys.path.insert(0, PLANNER_DIR)
    for _m in [m for m in list(sys.modules) if m == "generators" or m.startswith("generators.")]:
        del sys.modules[_m]
    from generators.template import build_trip_from_template, TEMPLATE_SCENES
    return build_trip_from_template, TEMPLATE_SCENES


BASE_PARAMS = {
    "scene": "business", "destination": "北京", "origin": "广州",
    "transport": "airplane", "start_date": "2026-09-15", "end_date": "2026-09-17",
    "days": 3, "purpose": "拜访国贸客户", "num_adults": 1, "budget_total": None,
    "dietary": [], "notes": "",
}

USER_QUERY = "9月15号广州飞北京出差，16号上午拜访国贸客户，17号下午返程"


def _all_acts(trip):
    return [a for d in trip["days"] for a in d["activities"]]


def _assert_no_overlap(trip):
    """时段不重叠、不越界 —— 与提示词【质量规则】同一口径。"""
    for d in trip["days"]:
        acts = sorted(d["activities"], key=lambda a: a["time_start"])
        for a, b in zip(acts, acts[1:]):
            assert a["time_end"] <= b["time_start"], (
                f"{d['date']} 活动重叠: {a['title']}({a['time_start']}~{a['time_end']}) vs "
                f"{b['title']}({b['time_start']}~{b['time_end']})"
            )
        for a in acts:
            assert a["time_end"] <= "23:59", f"{d['date']} 活动越界: {a['title']}"


# ---------------------------------------------------------------------------
# 一、骨架完整性
# ---------------------------------------------------------------------------
def test_three_day_skeleton(template_mod):
    build, _ = template_mod
    trip = build(dict(BASE_PARAMS), {}, USER_QUERY)
    assert trip is not None
    assert trip["title"] == "2026年9月北京拜访国贸客户之行"
    assert trip["destination"] == "北京" and trip["origin"] == "广州"
    assert trip["start_date"] == "2026-09-15" and trip["end_date"] == "2026-09-17"
    assert len(trip["days"]) == 3
    assert trip["days"][0]["theme"].startswith("赴北京")
    assert trip["days"][1]["theme"] == "拜访国贸客户"
    assert trip["days"][2]["theme"] == "返程"

    acts = _all_acts(trip)
    types = {a["type"] for a in acts}
    # 去程/返程大交通 + 入住/退房 + 事由会议槽位
    assert "transport" in types and "accommodation" in types and "meeting" in types
    # 铁律：商务场景禁景点
    assert "attraction" not in types
    # 事由落位到业务槽位
    assert any("拜访国贸客户" in a["title"] for a in acts)
    # 不编造航班号/车次
    assert all("CA" not in a["title"] and "G1" not in a["title"] for a in acts)
    # 标记模板直出
    assert trip["generation_mode"] == "template"


def test_time_no_overlap_all_shapes(template_mod):
    build, _ = template_mod
    cases = [
        (dict(BASE_PARAMS), USER_QUERY),
        ({**BASE_PARAMS, "days": 2, "end_date": "2026-09-16"}, "9月15号广州飞北京出差，16号返程"),
        ({**BASE_PARAMS, "days": 1, "end_date": "2026-09-15"}, "9月15号广州飞北京出差当天往返"),
        (dict(BASE_PARAMS), "9月15号下午飞北京出差，17号返程"),
        (dict(BASE_PARAMS), "9月15号广州飞北京出差，17号上午返程"),
        ({**BASE_PARAMS, "scene": "team", "days": 5, "end_date": "2026-09-19"}, "15号飞北京团建5天"),
        ({**BASE_PARAMS, "transport": "train", "num_adults": 2}, "9月15号高铁去北京出差3天，2人"),
    ]
    for params, query in cases:
        trip = build(params, {}, query)
        assert trip is not None
        _assert_no_overlap(trip)


def test_shape_day_counts(template_mod):
    build, _ = template_mod
    end_dates = {1: "2026-09-15", 2: "2026-09-16", 3: "2026-09-17", 5: "2026-09-19"}
    for days, end in end_dates.items():
        p = {**BASE_PARAMS, "days": days, "end_date": end}
        trip = build(p, {}, USER_QUERY)
        assert len(trip["days"]) == days, f"days={days} 应生成 {days} 天"


def test_time_preference_shifts(template_mod):
    build, _ = template_mod
    # 「上午返程」→ 末日活动整体前移，返程大交通在 12:00 前出发
    trip = build(dict(BASE_PARAMS), {}, "9月15号广州飞北京出差，17号上午返程")
    last_day = trip["days"][-1]["activities"]
    ride_back = [a for a in last_day if a["type"] == "transport" and a["location"]["name"] == "广州"]
    assert ride_back and ride_back[0]["time_start"] < "12:00"
    # 默认（下午返程）→ 14:00 档
    trip2 = build(dict(BASE_PARAMS), {}, USER_QUERY)
    last_day2 = trip2["days"][-1]["activities"]
    ride_back2 = [a for a in last_day2 if a["type"] == "transport" and a["location"]["name"] == "广州"]
    assert ride_back2 and ride_back2[0]["time_start"] >= "13:00"


# ---------------------------------------------------------------------------
# 二、预算估算
# ---------------------------------------------------------------------------
def test_budget_estimated_when_missing(template_mod):
    build, _ = template_mod
    trip = build(dict(BASE_PARAMS), {}, USER_QUERY)
    # 明细加总(人均)：首日 50+800+450(住宿)+100=1400；中间天 30+60+80+450=620；
    # 末日 60+50+800=910 → 2930（大交通按往返估价一半分摊进明细）
    assert trip["budget_total"] == 2930
    assert trip["budget_estimated"] is True


def test_budget_respected_when_given(template_mod):
    build, _ = template_mod
    trip = build({**BASE_PARAMS, "budget_total": 8000}, {}, USER_QUERY)
    assert trip["budget_total"] == 8000
    assert trip["budget_estimated"] is False


def test_budget_scales_with_party_and_mode(template_mod):
    build, _ = template_mod
    # 2 人高铁：明细人均 50+550+450+100=1150 / 620 / 660 → 2430 × 2
    trip = build({**BASE_PARAMS, "transport": "train", "num_adults": 2}, {}, USER_QUERY)
    assert trip["budget_total"] == 4860


def test_budget_equals_itemized_sum_all_shapes(template_mod):
    """2026-09-20 用户反馈回归：预算必须与明细条目加总精确一致（人均×人数）。"""
    build, _ = template_mod
    cases = [
        (dict(BASE_PARAMS), USER_QUERY),
        ({**BASE_PARAMS, "days": 2, "end_date": "2026-09-16"}, "9月15号广州飞北京出差，16号返程"),
        ({**BASE_PARAMS, "days": 1, "end_date": "2026-09-15"}, "9月15号广州飞北京出差当天往返"),
        ({**BASE_PARAMS, "transport": "train", "num_adults": 2}, "9月15号高铁去北京出差3天，2人"),
    ]
    for params, query in cases:
        trip = build(params, {}, query)
        party = max(1, len(trip["travel_party"]))
        itemized = sum(a.get("estimated_cost", 0)
                       for d in trip["days"] for a in d["activities"])
        assert trip["budget_total"] == itemized * party, (
            f"{params.get('days')}天/{params.get('transport')}: "
            f"预算 {trip['budget_total']} ≠ 明细加总 {itemized}×{party}"
        )


def test_hotel_nights_match_trip_length(template_mod):
    """2026-09-20 用户反馈回归：多日行程每晚都有带金额的住宿条目。"""
    build, _ = template_mod
    for days, end in [(2, "2026-09-16"), (3, "2026-09-17"), (5, "2026-09-19")]:
        trip = build({**BASE_PARAMS, "days": days, "end_date": end}, {}, USER_QUERY)
        # 末日的「酒店退房」也是 accommodation 但 0 元，付费住宿晚数应为 days-1
        stays = [a for d in trip["days"] for a in d["activities"]
                 if a["type"] == "accommodation" and a["estimated_cost"] > 0]
        assert len(stays) == days - 1, f"{days} 天行程应有 {days - 1} 晚住宿条目"


# ---------------------------------------------------------------------------
# 三、不适用场景 → 回退大模型
# ---------------------------------------------------------------------------
def test_personal_scene_returns_none(template_mod):
    build, _ = template_mod
    assert build({**BASE_PARAMS, "scene": "personal"}, {}, USER_QUERY) is None


def test_incomplete_params_return_none(template_mod):
    build, _ = template_mod
    assert build({**BASE_PARAMS, "destination": ""}, {}, USER_QUERY) is None
    assert build({**BASE_PARAMS, "days": None}, {}, USER_QUERY) is None
    assert build({**BASE_PARAMS, "start_date": "9月15号"}, {}, USER_QUERY) is None


def test_unknown_transport_falls_back_to_airplane(template_mod):
    build, _ = template_mod
    trip = build({**BASE_PARAMS, "transport": "rocket"}, {}, USER_QUERY)
    assert any("乘机" in a["title"] for a in _all_acts(trip))


# ---------------------------------------------------------------------------
# 四、ItineraryGenerator 流式链路接入
# ---------------------------------------------------------------------------
class _FakeLLM:
    """只实现模板链路用到的接口：抽取固定返回，其余调用全部计数。

    business 场景生成阶段应 0 次 LLM 调用（chat/chat_stream 不被触达）。
    """

    def __init__(self, extract: dict):
        self._extract = extract
        self.chat_calls = 0
        self.stream_calls = 0

    def is_available(self):
        return True

    def chat_json(self, messages, **kw):
        return self._extract

    def chat(self, messages, **kw):
        self.chat_calls += 1
        return ""

    def chat_stream(self, messages, **kw):
        self.stream_calls += 1
        yield ""

    def get_last_stats(self):
        return {}


@pytest.fixture()
def gen_mod():
    if PLANNER_DIR in sys.path:
        sys.path.remove(PLANNER_DIR)
    sys.path.insert(0, PLANNER_DIR)
    for _m in [m for m in list(sys.modules) if m == "generators" or m.startswith("generators.")]:
        del sys.modules[_m]
    from generators.itinerary import ItineraryGenerator
    return ItineraryGenerator


def test_generate_stream_business_uses_template(gen_mod):
    ItineraryGenerator = gen_mod
    fake = _FakeLLM(dict(BASE_PARAMS))
    gen = ItineraryGenerator(fake)
    chunks = list(gen.generate_stream(USER_QUERY, {}, {}, {}))
    assert chunks, "模板路径也应产出 JSON 文本块（保持前端流式契约）"
    trip = gen._last_trip
    assert trip is not None and trip["generation_mode"] == "template"
    assert fake.stream_calls == 0 and fake.chat_calls == 0, "生成阶段不应有 LLM 调用"
    assert gen._phase_timings["generate"]["llm"]["mode"] == "template"
    # 预算代填记录同步为模板口径
    budget_entry = next(d for d in gen.last_defaulted if d["field"] == "budget_total")
    assert "模板标准估算" in budget_entry["note"]
    assert budget_entry["value"] == trip["budget_total"]


def test_generate_stream_personal_still_uses_llm(gen_mod):
    ItineraryGenerator = gen_mod
    # 查询用规则抽取覆盖不了的形态（无绝对日期）→ 回退 LLM 抽取 → personal 生成
    fake = _FakeLLM({"scene": "personal", "destination": "北京", "origin": "广州",
                     "start_date": "2026-09-15", "end_date": "2026-09-17", "days": 3,
                     "num_adults": 2, "budget_total": None, "transport": "airplane"})
    gen = ItineraryGenerator(fake)
    _chunks = list(gen.generate_stream("我想去北京玩三天，两个人", {}, {}, {}))
    assert fake.stream_calls == 1, "personal 场景仍走大模型流式生成"


def test_generate_nonstream_business_uses_template(gen_mod):
    ItineraryGenerator = gen_mod
    fake = _FakeLLM(dict(BASE_PARAMS))
    gen = ItineraryGenerator(fake)
    trip = gen.generate(USER_QUERY, {}, {}, {})
    assert trip is not None and trip["generation_mode"] == "template"
    assert fake.chat_calls == 0, "非流式生成阶段也不应有 LLM 调用"
