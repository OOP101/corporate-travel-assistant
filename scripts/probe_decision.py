# -*- coding: utf-8 -*-
"""探针：用真实 LLM 跑一遍 shared/decision 类型化决策层。

目的（对应项目「实测优先」的约定）：
  1. 验证 DecisionClient 在真实网关（TokenHub）上跑得通 —— 三种原语各打一发，
     打印答案、置信度、耗时与纠正重试次数；
  2. 验证接入点真实有效：对一批「语义上是授权、但关键词正则漏掉」的说法，
     看类型化判定能否兜住，以及会不会误伤正常需求；
  3. 顺带给出真实延迟量级，便于判断语义兜底该不该默认开启。

用法：
    ./.venv/Scripts/python.exe scripts/probe_decision.py
不打印任何 key 明文。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_dotenv(path=os.path.join(ROOT, ".env")):
    """最小 .env 解析器：仅注入尚未存在的环境变量，避免覆盖已设值。"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


load_dotenv()

from shared.config import settings  # noqa: E402
from shared.llm import LLMManager  # noqa: E402
from shared.decision import Choice, DecisionClient, Noul, NoulCriteria, Score, clear_cache  # noqa: E402

PLANNER_DIR = os.path.join(ROOT, "services", "planner-core")
sys.path.insert(0, PLANNER_DIR)
from generators import itinerary  # noqa: E402


def build_llm():
    llm = LLMManager()
    llm.register(
        "openai_compatible",
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    if settings.tencent_maas_api_key and settings.tencent_maas_base_url:
        llm.register(
            "tencent_maas",
            api_key=settings.tencent_maas_api_key,
            base_url=settings.tencent_maas_base_url,
            model="deepseek-v4-flash",
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        for m in ("deepseek-v4-flash", "kimi-k3", "hy-mt2-pro", "hy-mt2-lite"):
            llm.register_model_route(m, "tencent_maas")
    if settings.llm_default_model:
        llm.default_model = settings.llm_default_model
    return llm


def hr(title):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def case_primitives(client):
    hr("① 三种原语各打一发（真实 LLM）")
    t0 = time.monotonic()
    resp = client.system_one(
        state="用户说：你看着办吧，别问我了，按常见差旅补全就行",
        questions={
            "authorized": Noul(
                instructions="用户是否授权由助手自行决定、无需再澄清？",
                criteria=NoulCriteria(true="明确把决定权交给助手", false="只是随口一说"),
            ),
            "scene": Choice(
                instructions="这句话属于哪类出行场景？",
                criteria={
                    "business": "商务出差",
                    "meeting": "会议/活动",
                    "visit": "拜访客户",
                    "team": "团队建设",
                    "personal": "个人出游",
                },
            ),
            "clarity": Score(
                instructions="这句话提供的信息完整度如何？",
                criteria=["几乎没给信息", "给了少量信息", "信息较完整", "信息非常完整"],
            ),
        },
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    a = resp.noul("authorized")
    c = resp.choice("scene")
    s = resp.score("clarity")
    print(f"模型            : {resp.model}")
    print(f"① Noul  authorized = {a.answer}   (P(是)={a.noul:.3f}, 置信度={a.confidence:.2f})")
    print(f"② Choice scene     = {c.choice}  (置信度={c.confidence:.3f}, 分布={ {k: round(v, 3) for k, v in c.probabilities.items()} })")
    print(f"③ Score clarity    = {s.score}  ({s.legend.get(s.score, '')}, 置信度={s.confidence:.2f})")
    print(f"用量            : in={resp.usage.input_tokens} out={resp.usage.output_tokens} "
          f"重试={resp.usage.n_retries}")
    print(f"实测耗时        : {elapsed} ms（客户端计时 {resp.usage.latency_ms} ms）")
    return elapsed


CASES = [
    # (文本, 期望是否授权)
    ("你看着办，按常见差旅默认补全", True),   # 正则命中
    ("不用问我了", True),                     # 正则漏
    ("你帮我定就行", True),                   # 正则漏
    ("这些你拿主意吧", True),                 # 正则漏
    ("按你说的来", True),                     # 正则漏
    ("下周三去深圳出差 3 天", False),          # 补充了日期+天数+目的地
    ("下周去上海", False),                     # 补充了目的地
    ("3 天", False),                           # 补充了天数
    ("帮我看看北京的住宿标准", False),
    ("为什么一定要填日期？", False),
]


def run_matrix(client, label):
    """跑一遍「正则 vs 正则+语义兜底」，返回 (命中数, 误判数, 平均耗时 ms)。"""
    print(f"\n--- {label}（llm_answer_mode={client.llm_answer_mode}）")
    print(f"{'文本':<26}{'正则':<8}{'+语义':<8}{'期望':<8}")
    print("-" * 74)
    regex_hits = semantic_hits = wrong = 0
    total_ms = 0
    for text, expected in CASES:
        clear_cache()
        only_regex = itinerary.is_autofill_authorized(text)
        t0 = time.monotonic()
        with_semantic = itinerary.is_autofill_authorized(text, client)
        total_ms += int((time.monotonic() - t0) * 1000)
        regex_hits += int(only_regex == expected)
        semantic_hits += int(with_semantic == expected)
        wrong += int(with_semantic != expected)
        print(f"{text:<24}{str(only_regex):<8}{str(with_semantic):<8}{str(expected):<8}"
              f"{'' if with_semantic == expected else '  <== 误判'}")
    n = len(CASES)
    print("-" * 74)
    print(f"命中期望：纯正则 {regex_hits}/{n} → 加语义兜底 {semantic_hits}/{n}（误判 {wrong}）"
          f"｜ 语义判定平均 {total_ms / n:.0f} ms/次")
    return semantic_hits, wrong, total_ms / n


def case_integration(client):
    hr("② 接入点实测：is_autofill_authorized（正则 vs 正则+语义兜底）")
    run_matrix(client, "probabilities 模式（默认）")
    discrete = DecisionClient(
        client.llm, model=client.model, llm_answer_mode="discrete",
        n_retry_malformed_structure=client.n_retry_malformed_structure,
    )
    run_matrix(discrete, "discrete 模式（对照：只要取值，输出更短）")


def main():
    llm = build_llm()
    client = DecisionClient(llm, model=settings.llm_default_model or None)
    print(f"网关: {settings.llm_base_url} | 默认模型: {settings.llm_default_model or settings.llm_model} "
          f"| LLM 可用: {llm.is_available()}")
    if not llm.is_available():
        print("!! 未配置可用 key，探针终止")
        return 1
    case_primitives(client)
    case_integration(client)
    print("\n探针结束。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
