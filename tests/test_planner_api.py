"""planner-core API 集成测试（FastAPI TestClient，隔离临时数据目录，LLM 走演示降级）"""
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

PLANNER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "planner-core")
# 三个服务都有顶层 api 包，必须保证 planner-core 在 sys.path 最前，
# 否则 api.main 会解析到其他服务的同名包（其他服务测试会把自己的目录插到 [0]）
if PLANNER_DIR in sys.path:
    sys.path.remove(PLANNER_DIR)
sys.path.insert(0, PLANNER_DIR)

# 三个服务都有顶层 api 包，其他服务的测试可能已把同名包导入 sys.modules；
# 驱逐后确保 api.main 解析到 planner-core 的入口
for _mod in [m for m in list(sys.modules) if m == "api" or m.startswith("api.")]:
    del sys.modules[_mod]

import api.main as planner_main  # noqa: E402
from api import deps as planner_deps  # noqa: E402
from shared.config import settings  # noqa: E402

assert "planner-core" in planner_main.__file__.replace("\\", "/").lower(), (
    f"api.main 解析到了错误的服务: {planner_main.__file__}"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 数据目录指向临时路径，与真实 data/ 隔离（org 目录由 trip_data_dir 推导）
    monkeypatch.setattr(settings, "trip_data_dir", str(tmp_path / "trips"))
    monkeypatch.setattr(settings, "profile_data_dir", str(tmp_path / "profiles"))
    monkeypatch.setattr(settings, "template_data_dir", str(tmp_path / "templates"))
    # 关闭 LLM 与 embedding，走演示/关键词降级路径
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_provider", "none")

    with TestClient(planner_main.app) as c:
        c.headers.update({"X-API-Key": settings.dev_api_key})
        yield c


def _parse_sse_events(text: str) -> list:
    """把 SSE 响应文本解析为事件帧列表（v2 契约：clarify/draft/policy/timing 等）。"""
    events = []
    for line in text.split("\n"):
        if line.startswith("data: ") and line.strip() != "data: [DONE]":
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _generate_and_confirm(client, query: str, session_id: str) -> str:
    """v2 流程辅助：生成草案（未落库）→ 确认落库 → 返回 trip_id。"""
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


def test_trip_not_found(client):
    assert client.get("/trips/trip_missing").status_code == 404


def test_policies_crud_and_match_reachable(client):
    """回归：/policies/match 不能被 /policies/{policy_id} 吞掉（批次2 修复）"""
    created = client.post("/policies", json={"name": "集成测试政策", "level": "junior", "hotel_limit": 500}).json()
    policy_id = created["policy_id"]

    matched = client.get("/policies/match", params={"level": "junior"})
    assert matched.status_code == 200
    assert matched.json()["policy"]["policy_id"] == policy_id

    assert client.delete(f"/policies/{policy_id}").status_code == 200
    assert client.get("/policies/match", params={"level": "nonexistent_level"}) .status_code in (200, 404)


def test_check_policy_violations(client):
    pol = client.post("/policies", json={"name": "限额政策", "hotel_limit": 100}).json()["policy_id"]
    trip_id = _generate_and_confirm(client, "去成都玩三天", "pol_user")

    r = client.post("/policies/check", params={"trip_id": trip_id, "policy_id": pol})
    assert r.status_code == 200
    body = r.json()
    assert body["trip_id"] == trip_id and "violations" in body


def test_approval_create_validates_references(client):
    # 行程不存在 → 404
    r = client.post("/approvals", json={"trip_id": "trip_x", "employee_id": "e", "approver_id": "a"})
    assert r.status_code == 404


def test_template_save_and_apply(client):
    trip_id = _generate_and_confirm(client, "去西安玩四天", "tpl_user")

    saved = client.post(f"/trips/{trip_id}/template", json={"template_name": "西安四日", "tags": ["西安"]}).json()
    assert saved["status"] == "ok"

    applied = client.post(
        f"/templates/{saved['template_id']}/apply",
        json={"user_id": "tpl_user2", "overrides": {"title": "西安复用"}},
    ).json()
    assert applied["trip"]["title"] == "西安复用"
    assert applied["trip"]["user_id"] == "tpl_user2"


def test_missing_api_key_rejected(client):
    import requests
    r = client.get("/trips", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 澄清链路的 SSE 契约：授权代填必须真的把必填项补上（2026-09-23 死循环回归）
# ---------------------------------------------------------------------------
@pytest.fixture()
def client_llm_stub(tmp_path, monkeypatch):
    """LLM「可用但 chat_json 返回空」——走真实 SSE 抽参链路，不打网络。

    不能用上面的 client fixture：LLM 不可用时 generate_stream 直接走
    _demo_generate 演示分支，根本不经过 _extract_params，澄清帧无从产生。
    """
    monkeypatch.setattr(settings, "trip_data_dir", str(tmp_path / "trips"))
    monkeypatch.setattr(settings, "profile_data_dir", str(tmp_path / "profiles"))
    monkeypatch.setattr(settings, "template_data_dir", str(tmp_path / "templates"))
    monkeypatch.setattr(settings, "embedding_provider", "none")

    with TestClient(planner_main.app) as c:
        c.headers.update({"X-API-Key": settings.dev_api_key})
        llm = planner_deps.llm_manager
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
    """用户点「你看着办」后缺参必须变少 —— 之前原样重现 → 同一句反问无限循环。"""
    # 场景已在上一轮由用户点选 → 走 explicit（等价界面上的场景 chip）
    first = _clarify_of(
        client_llm_stub, "个人出游", "loop_sse", params={"scene": "personal"}
    )
    assert first is not None, "缺参时应发 clarify 帧"
    assert set(first["missing"]) == {"destination", "start_date", "days"}

    # 用户点授权入口（带上轮已抽参数，等价 journey-hub 的 carry 续用）
    second = _clarify_of(
        client_llm_stub, "你看着办，按常见差旅默认补全", "loop_sse", carry=first["params"]
    )
    assert set(second["missing"]) == {"destination"}, (
        f"授权后日期天数应被代填、缺参只剩目的地；实际 {second['missing']}"
    )
    # 代填必须有据可查：日期已落到 params，确认页据此渲染 [代填]
    assert second["params"]["start_date"], "授权后应代填出发日期"
    assert second["params"]["days"] == 3, "personal 授权代填默认 3 天"
