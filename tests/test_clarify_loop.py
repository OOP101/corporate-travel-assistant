"""澄清回合死循环回归测试（2026-09-23 用户实测复现）。

现象：助手问「目的地是哪里 / 计划哪几天去」，用户点「你看着办，按常见差旅
默认补全」后，助手原样重问同一句 —— 连点 5 次得 5 遍相同反问，永远出不来。

两处根因，各锁一组用例：
  1. planner-core 从未实现「随便 / 你看着办 = 授权代填」（PRD §6.3）——
     日期天数没被规则补上，缺参清单原样重现，于是每次点击都重新命中同一批缺参；
  2. journey-hub 的 clarify_count 只被塞进 clarify 帧当 round 展示、从不拦截 ——
     PRD §6.3 的「同一行程最多 2 轮反问」上限形同虚设。

约定：目的地没有可用的代填规则（不能臆造城市），所以缺目的地时必须
「终止反问 + 引导手动创建」，而不是继续问。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANNER_DIR = os.path.join(ROOT, "services", "planner-core")
JOURNEY_DIR = os.path.join(ROOT, "services", "journey-hub")

CHIP_TEXT = "你看着办，按常见差旅默认补全"


class _NullLLM:
    """LLM 不可用：抽取完全走显式参数 / carry / 规则，确定性可断言（不打网络）。"""

    def is_available(self):
        return False


@pytest.fixture(scope="module")
def itin():
    """加载 planner-core 的 generators.itinerary（不触碰同名 api 包）。"""
    if PLANNER_DIR in sys.path:
        sys.path.remove(PLANNER_DIR)
    sys.path.insert(0, PLANNER_DIR)
    for _m in [m for m in list(sys.modules) if m == "generators" or m.startswith("generators.")]:
        del sys.modules[_m]
    from generators import itinerary
    return itinerary


@pytest.fixture(scope="module")
def graph_mod():
    """加载 journey-hub 的 state.graph（该服务的顶层包与 planner 无同名冲突）。"""
    if JOURNEY_DIR in sys.path:
        sys.path.remove(JOURNEY_DIR)
    sys.path.insert(0, JOURNEY_DIR)
    from state import graph
    return graph


# ---------------------------------------------------------------------------
# 根因 1：授权代填识别与规则补全
# ---------------------------------------------------------------------------
def test_chip_text_is_recognized_as_authorization(itin):
    """前端那枚按钮的原话必须被识别为授权（否则点了等于没说）。"""
    assert itin.is_autofill_authorized(CHIP_TEXT) is True
    for text in ("你看着办", "随便", "都行", "都可以", "按默认补全", "你决定", "听你的"):
        assert itin.is_autofill_authorized(text) is True, text


def test_normal_query_is_not_authorization(itin):
    """正常需求不能被误判成授权，否则会越过澄清直接代填。"""
    for text in ("下周一去深圳出差 3 天", "帮我看下北京的住宿标准", "9/15 到 9/17", ""):
        assert itin.is_autofill_authorized(text) is False, text


def test_authorized_chip_fills_date_and_days(itin):
    """授权后日期/天数被规则补全并记入 defaulted；缺参只剩目的地。"""
    gen = itin.ItineraryGenerator(llm_manager=_NullLLM(), guide_store=None)
    params, missing, defaulted = gen._extract_params(
        CHIP_TEXT, {}, explicit={"scene": "personal"}, carry={}
    )

    assert params["start_date"], "授权后应代填出发日期"
    assert params["days"] == itin.AUTH_DEFAULT_DAYS["personal"], "personal 授权代填默认 3 天"
    assert missing == ["destination"], f"目的地无规则可代填，仍应缺参；实际 {missing}"

    fields = {d["field"] for d in defaulted}
    assert {"start_date", "days"} <= fields, f"代填项须记账供确认页展示；实际 {fields}"


def test_business_scene_authorization_uses_two_days(itin):
    """商务场景按 PRD §6.2 兜底话术取 2 天（与 personal 区分）。"""
    gen = itin.ItineraryGenerator(llm_manager=_NullLLM(), guide_store=None)
    params, missing, _ = gen._extract_params(
        "随便", {}, explicit={"scene": "business", "destination": "深圳"}, carry={}
    )
    assert params["days"] == 2
    assert missing == [], f"场景+目的地已给、日期天数已代填 → 应可生成；实际 {missing}"


def test_without_authorization_keeps_all_missing(itin):
    """未授权时行为不变：缺参照旧全部上报，不做任何静默代填。"""
    gen = itin.ItineraryGenerator(llm_manager=_NullLLM(), guide_store=None)
    _, missing, _ = gen._extract_params("我要出去一趟", {}, explicit=None, carry=None)
    assert set(missing) == {"scene", "destination", "start_date", "days"}


# ---------------------------------------------------------------------------
# 根因 2：澄清轮次上限
# ---------------------------------------------------------------------------
class _StubTools:
    """只回放固定 clarify 帧的假规划器：模拟「必填始终缺目的地」。"""

    def __init__(self, frames):
        self._frames = frames

    def get_handler(self, name):
        if name != "plan_trip_stream":
            return None

        def _stream(query, session_id="default", state=None):
            yield {"kind": "progress", "content": "正在分析您的出行需求..."}
            yield from self._frames

        return _stream


def _clarify_frame():
    return {
        "kind": "clarify",
        "content": "为了帮你排出合适的行程，请补充几个信息：\n1. 请问目的地是哪里？",
        "missing": ["destination"],
        "params": {"scene": "personal"},
    }


def test_clarify_round_cap_stops_the_loop(graph_mod):
    """连点授权入口：前 2 轮照常反问，第 3 轮起必须终止反问并给手动入口。"""
    hub = graph_mod.JourneyHubGraph(
        llm_manager=None, tool_registry=_StubTools([_clarify_frame()])
    )
    assert graph_mod.MAX_CLARIFY_ROUNDS == 2

    def run_once():
        # 澄清阶段的用户输入按规划意图处理（与真实调用一致）
        hub.sessions.set_metadata("loop-session", "plan_stage", "clarify")
        return list(hub.invoke_stream(session_id="loop-session", user_input=CHIP_TEXT))

    rounds = [run_once() for _ in range(4)]

    for i in (0, 1):
        assert any(e["event"] == "clarify" for e in rounds[i]), f"第 {i + 1} 轮应照常反问"

    for i in (2, 3):
        assert not any(e["event"] == "clarify" for e in rounds[i]), (
            f"第 {i + 1} 轮仍在反问 → 死循环未修"
        )
        text = "".join(
            e.get("content", "") for e in rounds[i] if e["event"] in ("chunk", "respond")
        )
        assert "行程还差" in text and "差旅行程" in text, f"应给出缺项提示与手动入口；实际 {text!r}"


def test_cap_hit_keeps_carry_for_recovery(graph_mod):
    """触顶终止也要把已抽参数存进 carry —— 用户补上目的地后可直接出草案。"""
    hub = graph_mod.JourneyHubGraph(
        llm_manager=None, tool_registry=_StubTools([_clarify_frame()])
    )

    def run_once():
        hub.sessions.set_metadata("carry-session", "plan_stage", "clarify")
        return list(hub.invoke_stream(session_id="carry-session", user_input=CHIP_TEXT))

    run_once()
    run_once()
    terminal_round = run_once()  # 第 3 轮触顶
    assert not any(e["event"] == "clarify" for e in terminal_round)

    carry = hub.sessions.get_metadata("carry-session", "plan_carry") or {}
    assert carry.get("scene") == "personal", f"已抽到的场景须保留在 carry；实际 {carry}"
