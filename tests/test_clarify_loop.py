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


@pytest.fixture(autouse=True)
def _clear_decision_cache():
    """语义判定带 LRU 缓存；测试间必须清空，否则同文本会互相串结论。"""
    from shared.decision import clear_cache

    clear_cache()
    yield
    clear_cache()


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


# ---------------------------------------------------------------------------
# 根因 1 加强：正则必漏的同义授权用语，交给类型化判定（shared/decision）兜底
# ---------------------------------------------------------------------------
class _StubDecision:
    """假决策客户端：按预设概率回一个 noul 答案，并记录调用次数（不碰网络）。"""

    def __init__(self, probability, available=True):
        self.probability = probability
        self.available = available
        self.calls = 0

    def is_available(self):
        return self.available

    def system_one(self, state, questions, model=None, timeout=None):
        from shared.decision import DecisionResponse, NoulAnswer

        self.calls += 1
        return DecisionResponse(
            model="stub", answers={next(iter(questions)): NoulAnswer(noul=self.probability)}
        )


PARAPHRASE = "不用问我了"  # 正则覆盖不到，但语义上就是授权


def test_semantic_fallback_catches_paraphrase(itin):
    """正则漏掉的同义授权用语：有决策客户端时能兜住，没有时行为与旧版一致。"""
    assert itin.is_autofill_authorized(PARAPHRASE) is False, "不传客户端必须保持纯正则行为"
    stub = _StubDecision(0.92)
    assert itin.is_autofill_authorized(PARAPHRASE, stub) is True
    assert stub.calls == 1
    # 正则命中的话连判定都不该发起（快路径零成本）
    assert itin.is_autofill_authorized("你看着办", stub) is True
    assert stub.calls == 1


def test_semantic_fallback_respects_uncertainty(itin):
    """模型没把握时不代填 —— 继续澄清，总好过擅自替用户定行程。"""
    assert itin.is_autofill_authorized(PARAPHRASE, _StubDecision(0.6)) is False
    assert itin.is_autofill_authorized(PARAPHRASE, _StubDecision(0.05)) is False


def test_semantic_fallback_survives_dead_client(itin):
    """决策层不可用/抛异常 ⇒ 退回纯正则，绝不能把主流程拖崩。"""
    class _Dead(_StubDecision):
        def system_one(self, *a, **kw):
            raise RuntimeError("decision backend down")

    assert itin.is_autofill_authorized(PARAPHRASE, _StubDecision(0.9, available=False)) is False
    assert itin.is_autofill_authorized(PARAPHRASE, _Dead(0.9)) is False


def test_generator_gates_semantic_check_to_short_clarify_replies(itin, monkeypatch):
    """三重门控：首轮（carry 空）与长句都不发起判定；澄清回合的短回答才发起。

    语义兜底默认关闭（单次判定实测 ~2.7s，见 scripts/probe_decision.py），
    这里显式打开开关来验证门控逻辑本身。
    """
    monkeypatch.setattr(itin, "_SEMANTIC_AUTOFILL_ENABLED", True)
    stub = _StubDecision(0.9)
    gen = itin.ItineraryGenerator(llm_manager=_NullLLM(), guide_store=None, decision=stub)

    # 首轮：carry 为空 → 不是澄清回合，不判定
    gen._extract_params(PARAPHRASE, {}, explicit={"scene": "personal"}, carry={})
    assert stub.calls == 0, "首轮完整需求不该付这次往返成本"

    # 长句：自带明确信息，不判定
    long_text = "我想下个月十号前后去一趟成都顺便看看熊猫基地安排三天时间"
    gen._extract_params(long_text, {}, explicit={"scene": "personal"}, carry={"scene": "personal"})
    assert stub.calls == 0, "长句不判定"

    # 澄清回合的短回答：判定，且命中后日期/天数按规则补上
    params, missing, defaulted = gen._extract_params(
        PARAPHRASE, {}, explicit={"scene": "personal"}, carry={"scene": "personal"}
    )
    assert stub.calls == 1
    assert params["start_date"] and params["days"] == itin.AUTH_DEFAULT_DAYS["personal"]
    assert {"start_date", "days"} <= {d["field"] for d in defaulted}
    assert missing == ["destination"], f"目的地无代填规则，仍应缺参；实际 {missing}"


def test_semantic_check_off_by_default(itin):
    """默认不给澄清路径加延迟：开关未打开时，即使有可用客户端也不发起判定。"""
    stub = _StubDecision(0.9)
    gen = itin.ItineraryGenerator(llm_manager=_NullLLM(), guide_store=None, decision=stub)
    assert itin._SEMANTIC_AUTOFILL_ENABLED is False
    gen._extract_params(PARAPHRASE, {}, explicit={"scene": "personal"}, carry={"scene": "personal"})
    assert stub.calls == 0


def test_generator_can_disable_semantic_check(itin):
    """显式 decision=None 即关闭语义判定（回到纯正则）。"""
    gen = itin.ItineraryGenerator(llm_manager=_NullLLM(), guide_store=None, decision=None)
    _, missing, defaulted = gen._extract_params(
        PARAPHRASE, {}, explicit={"scene": "personal"}, carry={"scene": "personal"}
    )
    # 备注里带「授权代填」的条目只能来自授权分支（人数/交通等属于另一套常量代填）
    assert not [d for d in defaulted if "授权代填" in d.get("note", "")], defaulted
    assert set(missing) == {"destination", "start_date", "days"}
