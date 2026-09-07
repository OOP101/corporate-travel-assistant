# -*- coding: utf-8 -*-
"""探针：验证各服务商 key + 模型名是否真实可调通。

读取 .env 中的多模型 key，对每个 (base_url, model) 组合发一次最小 chat 请求，
记录 成功/失败/首响应延迟。不打印任何 key 明文。
"""
import os
import sys
import time
import json

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

import requests  # noqa: E402


def probe(name, base_url, api_key, model, timeout=30):
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "你好，请用一句话回复：测试。"}],
        "max_tokens": 32,
        "temperature": 0.1,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        dt = int((time.monotonic() - t0) * 1000)
        if r.status_code == 200:
            data = r.json()
            content = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
            usage = data.get("usage", {})
            return {"ok": True, "status": 200, "ms": dt, "content": content[:40],
                    "tokens": usage.get("total_tokens", "?")}
        else:
            return {"ok": False, "status": r.status_code, "ms": dt,
                    "error": r.text[:200]}
    except Exception as e:
        dt = int((time.monotonic() - t0) * 1000)
        return {"ok": False, "status": "ERR", "ms": dt, "error": str(e)[:200]}


def main():
    cases = []

    # ① 腾讯 TokenHub（新 key / 旧 key），三模型
    th_url = os.getenv("TENCENT_MAAS_BASE_URL")
    for tag, key in [("新key", os.getenv("TENCENT_MAAS_API_KEY")),
                     ("旧key", os.getenv("TENCENT_MAAS_API_KEY_BACKUP"))]:
        for m in ["hy-mt2-pro", "deepseek-v4-flash", "glm-5-turbo"]:
            cases.append((f"TokenHub({tag})", th_url, key, m))

    # ② Kimi / Moonshot
    kimi_url = os.getenv("KIMI_BASE_URL")
    for m in ["kimi-k3", "kimi-k2.6", "moonshot-v1-8k"]:
        cases.append((f"Kimi", kimi_url, os.getenv("KIMI_API_KEY"), m))

    # ③ 阿里云百炼 / 通义千问
    ali_url = os.getenv("ALIBABA_BASE_URL")
    for m in ["qwen-plus", "qwen-max", "qwen-turbo"]:
        cases.append((f"Alibaba", ali_url, os.getenv("ALIBABA_API_KEY"), m))

    results = []
    for name, url, key, model in cases:
        if not key:
            print(f"[SKIP] {name} {model}: 无 key")
            continue
        res = probe(name, url, key, model)
        results.append((name, model, res))
        status = "OK " if res["ok"] else "FAIL"
        detail = f"({res.get('status')}) {res.get('ms')}ms"
        if res["ok"]:
            detail += f" tokens={res.get('tokens')} content='{res.get('content')}'"
        else:
            detail += f" err={res.get('error','')[:120]}"
        print(f"[{status}] {name:<16} {model:<20} {detail}")

    # 汇总可用组合
    print("\n=== 可用模型 (ok=True) ===")
    ok_models = [(n, m) for n, m, r in results if r["ok"]]
    for n, m in ok_models:
        print(f"  {n} -> {m}")
    if not ok_models:
        print("  (无)")


if __name__ == "__main__":
    main()