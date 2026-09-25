"""企业智行 v3 · Agent 内核 API 集成测试（TestClient + 临时数据目录 + 演示/降级 LLM）"""
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICES_DIR = os.path.join(ROOT, "services")
for p in (ROOT, SERVICES_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import core.main as core_main  # noqa: E402
from core import deps as core_deps  # noqa: E402
from shared.config import settings  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """数据目录指向临时路径，与真实 data/ 隔离；LLM/Embedding 关闭走降级路径"""
    monkeypatch.setattr(settings, "trip_data_dir", str(tmp_path / "trips"))
    monkeypatch.setattr(settings, "profile_data_dir", str(tmp_path / "profiles"))
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_provider", "none")

    with TestClient(core_main.app) as c:
        c.headers.update({"X-API-Key": settings.dev_api_key})
        yield c


def _parse_sse_events(text: str) -> list:
    """把 SSE 响应文本解析为事件帧列表（clarify/draft/policy/timing 等契约）。"""
    events = []
    for line in text.split("\n"):
        if line.startswith("data: ") and line.strip() != "data: [DONE]":
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _generate_and_confirm(client, query: str, session_id: str) -> str:
    """v3 流程辅助：生成草案（未落库）→ 确认落库 → 返回 trip_id。"""
    r = client.post("/trips/generate", json={"query": query, "session_id": session_id})
    assert r.status_code == 200
    draft = next(e for e in _parse_sse_events(r.text) if e.get("event") == "draft")
    rc = client.post("/trips/confirm", json={"trip": draft["trip"], "session_id": session_id})
    assert rc.status_code == 200
    return rc.json()["trip_id"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_tool_bus_lists_core_and_service_tools(client):
    """工具总线：内核工具 + 外接服务工具全部注册（v3 架构自检）"""
    body = client.get("/agent/tools").json()
    names = {t["name"] for t in body["tools"]}
    assert {"plan_trip", "plan_trip_stream", "confirm_trip", "chat_query",
            "manage_trip", "emergency_assist"} <= names
    # 外接服务工具
    assert "policy_check" in names and "policy_docs_search" in names
    assert "guide_search" in names


def test_trip_generate_demo_and_full_lifecycle(client):
    # 生成草案（演示模式，SSE 完整响应）——草案阶段不落库（PRD v2 S3/S4）
    r = client.post("/trips/generate", json={"query": "下周去杭州玩两天", "session_id": "it_user"})
    assert r.status_code == 200
    assert "[DONE]" in r.text
    events = _parse_sse_events(r.text)
    draft = next(e for e in events if e.get("event") == "draft")
    trip = draft["trip"]
    assert trip["destination"] == "杭州"

    # 草案未落库：列表为空
    lst = client.get("/trips", params={"session_id": "it_user"}).json()
    assert lst["count"] == 0

    # 确认（S4 → S5）→ 落库
    rc = client.post("/trips/confirm", json={"trip": trip, "session_id": "it_user"})
    assert rc.status_code == 200
    trip_id = rc.json()["trip_id"]

    # 列表可见
    lst = client.get("/trips", params={"session_id": "it_user"}).json()
    assert lst["count"] == 1
    assert lst["trips"][0]["trip_id"] == trip_id
    assert lst["trips"][0]["user_id"] == "it_user"

    # 详情 / 更新
    detail = client.get(f"/trips/{trip_id}").json()
    assert detail["destination"] == "杭州"
    upd = client.put(f"/trips/{trip_id}", json={"data": {"title": "杭州新标题"}})
    assert upd.status_code == 200 and upd.json()["title"] == "杭州新标题"

    # 白名单外字段拒绝
    bad = client.put(f"/trips/{trip_id}", json={"data": {"user_id": "hacked"}})
    assert bad.status_code == 400

    # 删除
    assert client.delete(f"/trips/{trip_id}").status_code == 200
    assert client.get(f"/trips/{trip_id}").status_code == 404


def test_confirm_rejects_invalid_draft(client):
    """确认接口拒绝无效草案（缺目的地/标题）。"""
    r = client.post("/trips/confirm", json={"trip": {}, "session_id": "x"})
    assert r.status_code == 400


def test_trip_ownership_denied_for_other_session(client):
    trip_id = _generate_and_confirm(client, "去北京出差", "owner")

    r = client.get(f"/trips/{trip_id}", params={"session_id": "intruder"})
    assert r.status_code == 404  # 他人访问按 404 拒绝
    r2 = client.delete(f"/trips/{trip_id}", params={"session_id": "intruder"})
    assert r2.status_code == 404


def test_policies_crud_and_match_reachable(client):
    """政策外接服务：/policies/match 不能被 /policies/{policy_id} 吞掉（历史回归）"""
    created = client.post("/policies", json={"name": "集成测试政策", "level": "junior", "hotel_limit": 500}).json()
    policy_id = created["policy_id"]

    matched = client.get("/policies/match", params={"level": "junior"})
    assert matched.status_code == 200
    assert matched.json()["policy"]["policy_id"] == policy_id

    assert client.delete(f"/policies/{policy_id}").status_code == 200


def test_cross_service_policy_check(client):
    """跨服务桥：/policies/check（行程数据在核心，政策能力在外接服务）"""
    pol = client.post("/policies", json={"name": "限额政策", "hotel_limit": 100}).json()["policy_id"]
    trip_id = _generate_and_confirm(client, "去成都玩三天", "pol_user")

    r = client.post("/policies/check", params={"trip_id": trip_id, "policy_id": pol})
    assert r.status_code == 200
    body = r.json()
    assert body["trip_id"] == trip_id and "violations" in body


def test_policy_docs_crud_and_keyword_search(client):
    """政策文档 RAG：embedding 关闭时降级关键词检索，保留原文摘录"""
    created = client.post("/policy-docs", json={
        "title": "差旅住宿标准", "content": "普通员工住宿上限每晚 400 元，须提供发票。",
        "category": "policy",
    }).json()
    assert created["status"] == "ok"

    r = client.post("/policy-docs/search", json={"query": "住宿 上限", "top_k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "keyword"
    assert body["count"] >= 1
    assert "住宿" in (body["documents"][0].get("content") or "")


def test_guide_service_crud_and_search(client):
    """攻略外接服务：CRUD + 关键词降级检索"""
    created = client.post("/guides", json={
        "title": "杭州西湖攻略", "content": "西湖免门票，断桥残雪需早去，建议游玩 3 小时。",
        "category": "attraction", "tags": ["杭州"],
    }).json()
    assert created["status"] == "ok"
    guide_id = created["guide_id"]

    r = client.post("/guides/search", json={"query": "杭州 西湖", "top_k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["documents"][0]["guide_id"] == guide_id

    assert client.delete(f"/guides/{guide_id}").status_code == 200


def test_missing_api_key_rejected(client):
    r = client.get("/trips", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 澄清链路的 SSE 契约：授权代填必须真的把必填项补上（死循环回归，v3 管线版）
# ---------------------------------------------------------------------------
@pytest.fixture()
def client_llm_stub(tmp_path, monkeypatch):
    """LLM「可用但 chat_json 返回空」——走真实抽参链路，不打网络。

    LLM 不可用时 generate_stream 直接走 _demo_generate 演示分支，
    根本不经过 _extract_params，澄清帧无从产生。
    """
    monkeypatch.setattr(settings, "trip_data_dir", str(tmp_path / "trips"))
    monkeypatch.setattr(settings, "profile_data_dir", str(tmp_path / "profiles"))
    monkeypatch.setattr(settings, "embedding_provider", "none")

    with TestClient(core_main.app) as c:
        c.headers.update({"X-API-Key": settings.dev_api_key})
        llm = core_deps.llm_manager
        assert llm is not None, "lifespan 未装配 llm_manager"
        monkeypatch.setattr(llm, "is_available", lambda: True)
        monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {})
        yield c


def _clarify_of(client, query, session_id, carry=None, params=None):
    body = {"query": query, "session_id": session_id}
    if carry:
        body["carry"] = carry
    if params:
        body["params"] = params
    r = client.post("/trips/generate", json=body)
    assert r.status_code == 200
    events = _parse_sse_events(r.text)
    return next((e for e in events if e.get("event") == "clarify"), None)


def test_authorized_autofill_shrinks_missing_over_sse(client_llm_stub):
    """用户点「你看着办」后缺参必须变少 —— 原样重现即死循环回归。"""
    first = _clarify_of(
        client_llm_stub, "个人出游", "loop_v3", params={"scene": "personal"}
    )
    assert first is not None, "缺参时应发 clarify 帧"
    assert set(first["missing"]) == {"destination", "start_date", "days"}

    # 用户点授权入口（带上轮已抽参数 = carry 续用）
    second = _clarify_of(
        client_llm_stub, "你看着办，按常见差旅默认补全", "loop_v3", carry=first["params"]
    )
    assert set(second["missing"]) == {"destination"}, (
        f"授权后日期天数应被代填、缺参只剩目的地；实际 {second['missing']}"
    )
    assert second["params"]["start_date"], "授权后应代填出发日期"
    assert second["params"]["days"] == 3, "personal 授权代填默认 3 天"
