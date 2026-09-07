# -*- coding: utf-8 -*-
"""5 模型行程规划耗时基准。

对同一查询分别用 5 个模型调用 /trips/generate (planner-core 8002)，
每个模型跑 N 次取中位数。统计每个阶段耗时 + LLM token 用量。

使用方法:
    .venv/Scripts/python.exe scripts/bench_trip_models.py
    .venv/Scripts/python.exe scripts/bench_trip_models.py --trials 3 --query "..."
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# 确保可导入 venv/site-packages 并连到 services/ 的 import 路径
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


import requests  # noqa: E402


MODELS = [
    ("mimo-v2.5",         "MiMo 快速"),
    ("mimo-v2.5-pro",     "MiMo Pro 深度"),
    ("hy-mt2-pro",        "混元 Pro"),
    ("deepseek-v4-flash", "DeepSeek V4"),
    ("glm-5-turbo",       "GLM Turbo"),
]

DEFAULT_QUERY = "安排我到成都分公司做例行巡检，周二晚上团队聚餐"
PLANNER_URL = "http://127.0.0.1:8002/trips/generate"
API_KEY = "ak_dev_local"


def parse_sse(raw: str) -> dict:
    """解析 SSE 流，返回 events 列表与 timing dict。

    timing 帧单独提出；其他帧保留 event/content 以便调试。
    events: [{type: str, content: str, ...}, ...]
    """
    events = []
    timing = None
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        events.append(evt)
        if evt.get("event") == "timing":
            timing = evt
    return {"events": events, "timing": timing}


def fmt_ms(v, unit="s", default="0.0"):
    """把 ms 数值格式化为秒（默认）或原样输出。None 时给兜底。"""
    if v is None:
        return f"{'-':>{len(default)}}"
    if unit == "s":
        return f"{v/1000:.1f}s"
    return f"{v}{unit}"


def run_one(model_id: str, query: str, timeout: int = 480) -> dict:
    """跑一次 POST /trips/generate，记录各阶段 + 总耗时。"""
    body = {"query": query, "session_id": f"bench_{model_id}", "model": model_id}
    headers = {"Content-Type": "application/json", "X-API-Key": API_KEY}

    t0 = time.monotonic()
    t_first_chunk = None
    try:
        with requests.post(PLANNER_URL, json=body, headers=headers,
                            stream=True, timeout=timeout) as r:
            r.raise_for_status()
            # 关键：手头逐行读，立即捕获首 chunk 时间
            ensure_utf8(r)
            buf = []
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                buf.append(line)
                if line.startswith("data: ") and '"chunk"' in line and t_first_chunk is None:
                    t_first_chunk = int((time.monotonic() - t0) * 1000)
                if line.strip() == "data: [DONE]":
                    break
            t_done = int((time.monotonic() - t0) * 1000)
            raw = "\n".join(buf)
    except requests.RequestException as e:
        return {"ok": False, "model": model_id, "error": str(e)}

    parsed_sse = parse_sse(raw)
    timing = parsed_sse["timing"] or {}
    phases = timing.get("phases", {})
    extract = phases.get("extract", {}) or {}
    generate = phases.get("generate", {}) or {}
    save = phases.get("save", {}) or {}
    policy = phases.get("policy", {}) or {}
    api_total = phases.get("api_total", {}) or {}

    return {
        "ok": True,
        "model": model_id,
        "wall_total_ms": t_done,
        "first_chunk_ms": t_first_chunk,
        "extract_ms": extract.get("duration_ms"),
        "extract_llm_ms": (extract.get("llm") or {}).get("duration_ms"),
        "extract_prompt_tokens": (extract.get("llm") or {}).get("prompt_tokens"),
        "extract_completion_tokens": (extract.get("llm") or {}).get("completion_tokens"),
        "generate_ms": generate.get("duration_ms"),
        "generate_llm_ms": (generate.get("llm") or {}).get("duration_ms"),
        "generate_first_chunk_ms": (generate.get("llm") or {}).get("first_chunk_ms"),
        "generate_chunks": (generate.get("llm") or {}).get("chunks"),
        "generate_prompt_tokens": (generate.get("llm") or {}).get("prompt_tokens"),
        "generate_completion_tokens": (generate.get("llm") or {}).get("completion_tokens"),
        "parse_ms": (phases.get("parse", {}) or {}).get("duration_ms"),
        "save_ms": save.get("duration_ms"),
        "policy_ms": policy.get("duration_ms"),
        "api_total_ms": api_total.get("duration_ms"),
    }


def ensure_utf8(resp):
    """requests 对 text/event-stream 未声明 charset 时回退 ISO-8859-1，
    显式强制 UTF-8 避免中文乱码。"""
    ct = (resp.headers.get("Content-Type") or "").lower()
    if "charset" not in ct:
        resp.encoding = "utf-8"


def median(values: list) -> float:
    if not values:
        return 0
    return statistics.median(values)


def main():
    parser = argparse.ArgumentParser(description="行程规划 5 模型耗时基准")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="用户查询语句")
    parser.add_argument("--trials", type=int, default=2, help="每模型运行次数（取中位数）")
    parser.add_argument("--out", default="benchmark_results.json", help="结果 JSON 输出文件")
    args = parser.parse_args()

    print(f"查询: {args.query}\n每模型 {args.trials} 次\n")
    all_results = {}
    summary = []

    for model_id, label in MODELS:
        print(f"--- {label} ({model_id}) ---")
        runs = []
        for trial in range(args.trials):
            print(f"  trial {trial + 1}/{args.trials} ... ", end="", flush=True)
            res = run_one(model_id, args.query)
            if not res["ok"]:
                print(f"FAIL: {res.get('error')}")
                continue
            print(
                f"total={fmt_ms(res['wall_total_ms'])} "
                f"extract={fmt_ms(res['extract_ms'])} "
                f"generate={fmt_ms(res['generate_ms'])} "
                f"first_chunk={fmt_ms(res.get('first_chunk_ms'),default='-')}"
            )
            runs.append(res)
        all_results[model_id] = runs

        if not runs:
            print(f"  !! {label} 所有 trial 失败\n")
            continue
        summary.append({
            "model_id": model_id,
            "label": label,
            "n_trials": len(runs),
            "wall_total_s": median([r["wall_total_ms"] for r in runs]) / 1000,
            "first_chunk_s": median([r["first_chunk_ms"] or 0 for r in runs]) / 1000,
            "extract_s": median([r["extract_ms"] or 0 for r in runs]) / 1000,
            "extract_llm_s": median([r["extract_llm_ms"] or 0 for r in runs]) / 1000,
            "extract_prompt_tokens": median([r["extract_prompt_tokens"] or 0 for r in runs]),
            "extract_completion_tokens": median([r["extract_completion_tokens"] or 0 for r in runs]),
            "generate_s": median([r["generate_ms"] or 0 for r in runs]) / 1000,
            "generate_llm_s": median([r["generate_llm_ms"] or 0 for r in runs]) / 1000,
            "generate_first_chunk_s": median([r["generate_first_chunk_ms"] or 0 for r in runs]) / 1000,
            "generate_chunks": median([r["generate_chunks"] or 0 for r in runs]),
            "generate_prompt_tokens": median([r["generate_prompt_tokens"] or 0 for r in runs]),
            "generate_completion_tokens": median([r["generate_completion_tokens"] or 0 for r in runs]),
            "parse_ms": median([r["parse_ms"] or 0 for r in runs]),
            "save_ms": median([r["save_ms"] or 0 for r in runs]),
            "policy_ms": median([r["policy_ms"] or 0 for r in runs]),
            "api_total_s": median([r["api_total_ms"] or 0 for r in runs]) / 1000,
        })
        print()

    # 表格
    if summary:
        print("\n" + "=" * 110)
        print(f"{'模型':<14} {'总耗时':>8} {'首字':>8} {'提取':>8} {'生成':>8} {'生成首字':>10} "
              f"{'提取tok':>8} {'生成tok':>9} {'块':>4} {'解析ms':>8} {'保存ms':>8}")
        print("-" * 110)
        for s in sorted(summary, key=lambda x: x["wall_total_s"]):
            def safe_get(k, default=0):
                v = s.get(k, default)
                return default if v is None else v
            print(
                f"{s['label']:<14} "
                f"{safe_get('wall_total_s'):>7.2f}s "
                f"{safe_get('first_chunk_s'):>7.2f}s "
                f"{safe_get('extract_s'):>7.2f}s "
                f"{safe_get('generate_s'):>7.2f}s "
                f"{safe_get('generate_first_chunk_s'):>9.2f}s "
                f"{safe_get('extract_prompt_tokens')+safe_get('extract_completion_tokens'):>7.0f} "
                f"{safe_get('generate_prompt_tokens')+safe_get('generate_completion_tokens'):>8.0f} "
                f"{int(safe_get('generate_chunks')):>4} "
                f"{safe_get('parse_ms'):>7.0f} "
                f"{safe_get('save_ms'):>7.0f}"
            )
        print("=" * 110)

    # 保存 JSON
    out_path = ROOT / args.out
    out_path.write_text(
        json.dumps({"query": args.query, "trials": args.trials,
                     "summary": summary, "runs": all_results},
                    ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n详细数据写入 {out_path}")


if __name__ == "__main__":
    main()