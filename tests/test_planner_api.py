"""planner-core API 集成测试（FastAPI TestClient，隔离临时数据目录，LLM 走演示降级）"""
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


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_trip_generate_demo_and_full_lifecycle(client):
    # 生成（演示模式，SSE 完整响应）
    r = client.post("/trips/generate", json={"query": "下周去杭州玩两天", "session_id": "it_user"})
    assert r.status_code == 200
    assert "done" in r.text and "[DONE]" in r.text

    # 列表可见
    lst = client.get("/trips", params={"session_id": "it_user"}).json()
    assert lst["count"] == 1
    trip_id = lst["trips"][0]["trip_id"]
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


def test_trip_ownership_denied_for_other_session(client):
    client.post("/trips/generate", json={"query": "去北京出差", "session_id": "owner"})
    trip_id = client.get("/trips", params={"session_id": "owner"}).json()["trips"][0]["trip_id"]

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
    client.post("/trips/generate", json={"query": "去成都玩三天", "session_id": "pol_user"})
    trip_id = client.get("/trips", params={"session_id": "pol_user"}).json()["trips"][0]["trip_id"]

    r = client.post("/policies/check", params={"trip_id": trip_id, "policy_id": pol})
    assert r.status_code == 200
    body = r.json()
    assert body["trip_id"] == trip_id and "violations" in body


def test_approval_create_validates_references(client):
    # 行程不存在 → 404
    r = client.post("/approvals", json={"trip_id": "trip_x", "employee_id": "e", "approver_id": "a"})
    assert r.status_code == 404


def test_template_save_and_apply(client):
    client.post("/trips/generate", json={"query": "去西安玩四天", "session_id": "tpl_user"})
    trip_id = client.get("/trips", params={"session_id": "tpl_user"}).json()["trips"][0]["trip_id"]

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
