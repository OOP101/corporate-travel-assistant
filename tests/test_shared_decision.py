"""shared.decision（System One 类型化决策层）测试 —— 全程注入 LLM 桩，不碰网络。

覆盖三块：
  1. 类型原语（Noul / Choice / Score 的问题与答案模型）语义正确；
  2. DecisionClient 的提示词契约、结构校验、概率归一、畸形纠正重试与错误收敛；
  3. guard 守卫的降级契约（不可用 / 异常 / 不确定带一律回 default，绝不抛出）+ 缓存。
"""
import json

import pytest

from shared.decision import (
    Choice,
    DecisionClient,
    DecisionError,
    Noul,
    NoulAnswer,
    NoulCriteria,
    Score,
    ask_choice,
    ask_noul,
    ask_score,
    build_messages,
    cache_info,
    clear_cache,
    coerce_answers,
)


# ---------------------------------------------------------------------------
# 桩
# ---------------------------------------------------------------------------
class FakeLLM:
    """最小 LLM 桩：按队列回放 chat_json 结果，记录调用参数。"""

    def __init__(self, *payloads, available=True):
        self.payloads = list(payloads)
        self.available = available
        self.calls = []

    def is_available(self):
        return self.available

    def chat_json(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if not self.payloads:
            raise AssertionError("FakeLLM 没有更多可回放的 payload")
        return self.payloads.pop(0)

    def get_last_stats(self):
        return {"prompt_tokens": 111, "completion_tokens": 22, "duration_ms": 345}


def noul_payload(name, probability):
    return {"answers": {name: {"type": "noul", "noul": probability}}}


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# 1. 类型原语
# ---------------------------------------------------------------------------
def test_noul_answer_carries_yes_probability():
    """Noul 的答案就是「是」的概率（官方模型没有单独 confidence 字段）。"""
    a = NoulAnswer(noul=0.98)
    assert a.answer is True
    assert bool(a) is True
    assert a.confidence == pytest.approx(0.96)

    assert NoulAnswer(noul=0.02).answer is False
    assert NoulAnswer(noul=0.5).confidence == pytest.approx(0.0), "0.5 = 完全不确定"


def test_choice_answer_str_and_score_answer_argmax():
    from shared.decision import ChoiceAnswer, ScoreAnswer

    c = ChoiceAnswer(choice="business", confidence=0.8, probabilities={"business": 0.8, "personal": 0.2})
    assert str(c) == "business"

    s = ScoreAnswer(legend={0: "差", 1: "中", 2: "好"}, probabilities={0: 0.1, 1: 0.2, 2: 0.7})
    assert s.score == 2
    assert int(s) == 2
    assert s.confidence == pytest.approx(0.7)
    assert ScoreAnswer(probabilities={}).score is None


def test_decision_response_typed_views_and_boolean():
    from shared.decision import DecisionResponse

    resp = DecisionResponse(
        model="stub",
        answers={
            "authorized": NoulAnswer(noul=0.91),
            "scene": __import__("shared.decision", fromlist=["ChoiceAnswer"]).ChoiceAnswer(choice="business"),
        },
    )
    assert set(resp.nouls) == {"authorized"}
    assert set(resp.choices) == {"scene"}
    assert resp.boolean("authorized") is True
    assert resp.boolean("missing", default=True) is True
    assert resp.noul("scene") is None, "类型不符时按缺失处理"
    assert resp.choice("authorized") is None


def test_question_models_reject_unknown_fields():
    with pytest.raises(Exception):
        Noul(instructions="x", bogus=1)


def test_questions_accept_plain_dicts_too():
    """官方 API 允许 question 是对象或 dict；这里同样支持（TypeAdapter 归一）。"""
    client = DecisionClient(FakeLLM(noul_payload("ok", 0.9)))
    resp = client.system_one("s", {"ok": {"type": "noul", "instructions": "是不是？"}})
    assert resp.noul("ok").noul == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 2. 提示词契约
# ---------------------------------------------------------------------------
def test_build_messages_renders_state_questions_and_template():
    msgs = build_messages(
        "用户说：帮我看看周末去哪",
        {
            "authorized": Noul(
                instructions="是否授权跳过澄清？",
                criteria=NoulCriteria(true="明确表示不用问", false="只是随口一说"),
            ),
            "scene": Choice(instructions="判定场景", criteria={"business": "出差", "personal": "出游"}),
        },
    )
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "JSON" in system and "不要输出任何解释" in system

    assert "用户说：帮我看看周末去哪" in user
    assert "### authorized（noul）" in user and "判为「是」的情形：明确表示不用问" in user
    assert "### scene（choice）" in user and "- business：出差" in user

    template = json.loads(user.split("## 输出 JSON 模板（照抄结构，替换数值 / 选项 / 概率）\n")[1])
    assert set(template["answers"]) == {"authorized", "scene"}
    assert template["answers"]["authorized"]["type"] == "noul"
    assert set(template["answers"]["scene"]["probabilities"]) == {"business", "personal"}


# ---------------------------------------------------------------------------
# 3. DecisionClient 主链路
# ---------------------------------------------------------------------------
def test_system_one_parses_valid_payload_and_usage():
    llm = FakeLLM(noul_payload("authorized", 0.93))
    client = DecisionClient(llm, model="deepseek-v4-flash")
    resp = client.system_one("你看着办", {"authorized": Noul(instructions="是否授权？")})

    assert resp.noul("authorized").answer is True
    assert resp.model == "deepseek-v4-flash"
    assert resp.usage.input_tokens == 111 and resp.usage.output_tokens == 22
    assert resp.usage.latency_ms == 345 and resp.usage.n_retries == 0
    # 判定类任务温度固定 0，避免同输入两次得到不同结论
    assert llm.calls[0]["temperature"] == 0.0
    assert llm.calls[0]["model"] == "deepseek-v4-flash"


def test_system_one_normalizes_probabilities():
    """模型给的分布不合法（和≠1）时按开关等比缩放修正。"""
    from shared.decision import ChoiceAnswer

    payload = {"answers": {"scene": {
        "type": "choice", "choice": "business",
        "confidence": 0.9, "probabilities": {"business": 2.0, "personal": 1.0},
    }}}
    client = DecisionClient(FakeLLM(payload), normalize_probabilities=True)
    ans = client.system_one("s", {"scene": Choice(criteria={"business": "出差", "personal": "出游"})}).choice("scene")
    assert sum(ans.probabilities.values()) == pytest.approx(1.0)
    assert ans.probabilities["business"] == pytest.approx(2 / 3)


def test_choice_rejects_label_outside_criteria():
    """选中项不在可选项内 = 结构不合规（否则下游会拿到一个不存在的枚举值）。"""
    from shared.decision.client import _Malformed

    with pytest.raises(_Malformed):
        coerce_answers(
            {"scene": Choice(criteria={"business": "出差", "personal": "出游"})},
            {"answers": {"scene": {"type": "choice", "choice": "unknown"}}},
        )


def test_score_requires_probabilities():
    from shared.decision.client import _Malformed

    with pytest.raises(_Malformed):
        coerce_answers(
            {"quality": Score(criteria=["差", "中", "好"])},
            {"answers": {"quality": {"type": "score"}}},
        )


def test_discrete_mode_snaps_noul_to_certainty():
    client = DecisionClient(FakeLLM(noul_payload("q", 0.62)), llm_answer_mode="discrete")
    assert client.system_one("s", {"q": Noul()}).noul("q").noul == 1.0

    payload = {"answers": {"scene": {"type": "choice", "choice": "personal"}}}
    c2 = DecisionClient(FakeLLM(payload), llm_answer_mode="discrete")
    ans = c2.system_one("s", {"scene": Choice(criteria={"business": "出差", "personal": "出游"})}).choice("scene")
    assert ans.probabilities == {"personal": 1.0}, "离散模式没给分布时退化为 one-hot"


def test_system_one_retries_malformed_then_succeeds():
    llm = FakeLLM(
        {"answers": {"q": {"type": "noul", "noul": "说不清"}}},  # 首次畸形
        noul_payload("q", 0.88),  # 纠正后成功
    )
    client = DecisionClient(llm, n_retry_malformed_structure=1)
    resp = client.system_one("s", {"q": Noul(instructions="i")})
    assert resp.noul("q").noul == pytest.approx(0.88)
    assert resp.usage.n_retries == 1
    assert len(llm.calls) == 2
    # 纠正重试必须把失败原因回灌，否则模型无法自我修正
    assert "上一次输出不合规" in llm.calls[1]["messages"][-1]["content"]


def test_system_one_raises_after_retries_exhausted():
    bad = {"answers": {"q": {"type": "noul"}}}
    client = DecisionClient(FakeLLM(bad, bad), n_retry_malformed_structure=1)
    with pytest.raises(DecisionError):
        client.system_one("s", {"q": Noul()})


def test_system_one_raises_when_llm_unavailable():
    client = DecisionClient(FakeLLM(available=False))
    with pytest.raises(DecisionError):
        client.system_one("s", {"q": Noul()})


def test_system_one_raises_on_llm_exception():
    class Boom(FakeLLM):
        def chat_json(self, messages, **kwargs):
            raise RuntimeError("connection reset")

    with pytest.raises(DecisionError):
        DecisionClient(Boom()).system_one("s", {"q": Noul()})


def test_system_one_rejects_bad_question_definition():
    client = DecisionClient(FakeLLM(noul_payload("q", 0.9)))
    with pytest.raises(DecisionError):
        client.system_one("s", {"q": {"type": "not-a-real-primitive"}})


def test_system_one_rejects_empty_questions():
    with pytest.raises(DecisionError):
        DecisionClient(FakeLLM()).system_one("s", {})


def test_invalid_answer_mode_rejected_early():
    with pytest.raises(ValueError):
        DecisionClient(FakeLLM(), llm_answer_mode="magic")


# ---------------------------------------------------------------------------
# 4. guard 守卫：降级契约
# ---------------------------------------------------------------------------
def test_ask_noul_yes_no_and_uncertain_band():
    assert ask_noul(DecisionClient(FakeLLM(noul_payload("q", 0.95))), "s", "i", default=None) is True
    clear_cache()
    assert ask_noul(DecisionClient(FakeLLM(noul_payload("q", 0.02))), "s", "i", default=None) is False
    clear_cache()
    # 0.6 落在不确定带（1-0.75 ~ 0.75）→ 交回调用方默认逻辑，不硬猜
    assert ask_noul(DecisionClient(FakeLLM(noul_payload("q", 0.6))), "s", "i", default=None) is None
    clear_cache()
    assert ask_noul(DecisionClient(FakeLLM(noul_payload("q", 0.6))), "s", "i", default=False) is False


def test_ask_noul_degrades_silently():
    from shared.decision import DecisionClient as DC

    assert ask_noul(None, "s", "i", default=False) is False, "没客户端就是没能力，不是报错"
    assert ask_noul(DC(FakeLLM(available=False)), "s", "i", default=False) is False

    class Boom(FakeLLM):
        def chat_json(self, messages, **kwargs):
            raise RuntimeError("boom")

    assert ask_noul(DC(Boom()), "s", "i", default=False) is False, "决策层异常不得打断主流程"


def test_ask_noul_caches_by_state_so_repeat_is_free():
    """同文本重复判定零成本 —— 这正是「用户连点同一个按钮」的场景。"""
    llm = FakeLLM(noul_payload("q", 0.95), noul_payload("q", 0.95))
    client = DecisionClient(llm)
    assert ask_noul(client, "你看着办", "i", default=None) is True
    assert ask_noul(client, "你看着办", "i", default=None) is True
    assert len(llm.calls) == 1, "第二次应命中缓存"
    assert cache_info()["size"] == 1

    # 不同 state 不共享缓存
    assert ask_noul(client, "换个说法", "i", default=None) is True
    assert len(llm.calls) == 2


def test_ask_choice_and_score_and_confidence_gates():
    from shared.decision import ChoiceAnswer, DecisionResponse, ScoreAnswer

    class StubClient:
        def __init__(self, answer):
            self.answer, self.calls = answer, 0

        def is_available(self):
            return True

        def system_one(self, state, questions, model=None, timeout=None):
            self.calls += 1
            return DecisionResponse(model="stub", answers={next(iter(questions)): self.answer})

    low = StubClient(ChoiceAnswer(choice="business", confidence=0.3, probabilities={"business": 0.3, "personal": 0.7}))
    assert ask_choice(low, "s", "i", {"business": "出差", "personal": "出游"}, default=None) is None
    assert ask_choice(low, "s", "i", {"business": "出差", "personal": "出游"}, default=None,
                      min_confidence=0.2) == "business"

    clear_cache()
    good = StubClient(ScoreAnswer(legend={0: "差", 1: "中", 2: "好"}, probabilities={0: 0.1, 1: 0.2, 2: 0.7}))
    assert ask_score(good, "s", "i", ["差", "中", "好"], default=None) == 2

    clear_cache()
    assert ask_choice(good, "s", "i", {}, default=None) is None, "空选项直接回 default，不发起调用"
    assert ask_score(good, "s", "i", [], default=None) is None
