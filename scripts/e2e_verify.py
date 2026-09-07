"""批次1修复的端到端验证脚本（可重复运行，用后即删级别，不进测试套件）。

验证项:
  1. SSE 行程生成正常出帧且保存 user_id
  2. 属主校验: 本人 200 / 他人 404 / 未声明身份兼容放行
  3. journey-hub 阻塞修复: /agent/chat 执行期间 /health 保持响应
  4. 并发生成不串单: 两个并发 SSE 各自 destination/user_id 正确
"""
import json
import threading
import time

import requests

BASE = "http://127.0.0.1"
HEADERS = {"Content-Type": "application/json", "X-API-Key": "ak_dev_local"}


def sse_generate(port, query, session_id, timeout=180):
    """POST /trips/generate，收集事件帧，返回 (events, trip_id)。"""
    url = f"{BASE}:{port}/trips/generate"
    events = []
    trip_id = None
    resp = requests.post(url, headers=HEADERS, stream=True, timeout=timeout,
                         json={"query": query, "session_id": session_id})
    resp.raise_for_status()
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            break
        try:
            frame = json.loads(payload)
        except json.JSONDecodeError:
            continue
        events.append(frame.get("event"))
        if frame.get("event") == "done" and frame.get("trip_id"):
            trip_id = frame["trip_id"]
    return events, trip_id


def main():
    ok = lambda name: print(f"  PASS  {name}")

    # --- 1. 生成 + 保存归属 ---
    print("[1] SSE 行程生成")
    t0 = time.time()
    events, trip_id = sse_generate(8002, "9月10号上海去北京出差两天，拜访国贸客户", "user_A")
    assert "status" in events and "chunk" in events and "done" in events, f"事件帧异常: {events}"
    assert trip_id, f"未返回 trip_id: {events}"
    ok(f"事件序列 {sorted(set(events))}，trip_id={trip_id}，耗时 {time.time()-t0:.1f}s")

    # --- 2. 属主校验 ---
    print("[2] 属主校验 (IDOR)")
    r_self = requests.get(f"{BASE}:8002/trips/{trip_id}",
                          params={"session_id": "user_A"}, headers=HEADERS)
    r_other = requests.get(f"{BASE}:8002/trips/{trip_id}",
                           params={"session_id": "user_B"}, headers=HEADERS)
    r_anon = requests.get(f"{BASE}:8002/trips/{trip_id}", headers=HEADERS)
    assert r_self.status_code == 200 and r_self.json().get("user_id") == "user_A"
    assert r_other.status_code == 404, f"他人访问应 404，实际 {r_other.status_code}"
    assert r_anon.status_code == 200, f"未声明身份应兼容放行，实际 {r_anon.status_code}"
    ok(f"本人 200 / 他人 {r_other.status_code} / 匿名 {r_anon.status_code}")

    # --- 3. journey-hub 阻塞修复 ---
    print("[3] journey-hub 事件循环")
    health_latencies = []
    stop = threading.Event()

    def poll_health():
        while not stop.is_set():
            t = time.time()
            try:
                requests.get(f"{BASE}:8001/health", timeout=5).raise_for_status()
                health_latencies.append(time.time() - t)
            except Exception as e:
                health_latencies.append(999)
            time.sleep(0.3)

    poller = threading.Thread(target=poll_health)
    poller.start()
    r = requests.post(f"{BASE}:8001/agent/chat", headers=HEADERS, timeout=180,
                      json={"query": "公司差旅的火车坐席标准是什么？简答", "session_id": "e2e"})
    stop.set()
    poller.join()
    assert r.status_code == 200, f"agent/chat 失败: {r.status_code} {r.text[:200]}"
    worst = max(health_latencies)
    assert worst < 3, f"/health 在对话期间被阻塞 {worst:.2f}s"
    ok(f"对话期间 /health 最慢 {worst*1000:.0f}ms（阈值 3s），响应 {len(r.json()['response'])} 字")

    # --- 4. 并发生成不串单 ---
    print("[4] 并发生成竞态")
    results = {}

    def worker(name, query, sid):
        try:
            _, tid = sse_generate(8002, query, sid)
            trip = requests.get(f"{BASE}:8002/trips/{tid}",
                                params={"session_id": sid}, headers=HEADERS).json()
            results[name] = (sid, trip.get("destination", ""), trip.get("user_id"))
        except Exception as e:
            results[name] = ("ERROR", str(e), "")

    w1 = threading.Thread(target=worker, args=("A", "9月20号去深圳参加三天展会", "conc_A"))
    w2 = threading.Thread(target=worker, args=("B", "9月20号去成都玩五天亲子游", "conc_B"))
    w1.start(); w2.start(); w1.join(); w2.join()

    for name, (sid, dest, owner) in results.items():
        assert "深圳" in dest or "成都" in dest, f"{name} 目的地异常: {dest}"
        assert owner == sid, f"{name} 归属串单: owner={owner} 应为 {sid}"
        ok(f"{name}: destination={dest}, owner={owner} 正确")

    # --- 5. 生成后政策检查 + 审批自动发起（web-user 为种子员工，junior，须审批）---
    print("[5] 政策/审批自动链路")
    events, trip_id = sse_generate(8002, "10月1号北京去上海出差三天开年会", "web-user")
    assert "done" in events, f"生成失败: {events}"
    assert "policy" in events, f"缺少政策检查帧: {events}"
    r_apr = requests.get(f"{BASE}:8002/approvals", params={"employee_id": "web-user"}, headers=HEADERS)
    pending = [a for a in r_apr.json().get("approvals", []) if a.get("trip_id") == trip_id]
    assert "approval" in events or pending, f"应自动发起审批: events={events}, pending={len(pending)}"
    ok(f"policy 帧已发出，自动审批单 {len(pending)} 条关联本次行程")

    # --- 6. journey-hub 真流式：chat 意图应产生多个 chunk 帧 ---
    print("[6] journey-hub 真流式")
    t0 = time.time()
    first_chunk_at = None
    chunk_count = 0
    with requests.post(f"{BASE}:8001/agent/chat/stream", headers=HEADERS, stream=True,
                       timeout=180, json={"query": "日本的签证材料一般需要哪些证件？", "session_id": "e2e-stream"}) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            try:
                frame = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if frame.get("event") == "chunk":
                chunk_count += 1
                if first_chunk_at is None:
                    first_chunk_at = time.time() - t0
    assert chunk_count >= 3, f"chunk 帧不足（{chunk_count}），疑似仍是假流式"
    assert first_chunk_at < 15, f"首 chunk 延迟 {first_chunk_at:.1f}s 过高"
    ok(f"{chunk_count} 个 chunk 帧，首个 chunk {first_chunk_at:.1f}s 到达")

    print("\nALL E2E CHECKS PASSED")


if __name__ == "__main__":
    main()
