"""企业智行 v3 · 审批闭环引擎测试（唯一业务主线：确认门禁 → 政策 → 审批 → 生效/作废）"""
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
    monkeypatch.setattr(settings, "trip_data_dir", str(tmp_path / "trips"))
    monkeypatch.setattr(settings, "profile_data_dir", str(tmp_path / "profiles"))
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_provider", "none")

    with TestClient(core_main.app) as c:
        c.headers.update({"X-API-Key": settings.dev_api_key})
        yield c


def _seed_employee(employee_id: str, name: str, level: str = "junior",
                   manager_id: str = "", salary_level: str = ""):
    core_deps.employee_store.save({
        "employee_id": employee_id,
        "name": name,
        "level": level,
        "manager_id": manager_id,
        "salary_level": salary_level,
    })


def _generate_draft(client, query: str, session_id: str, params: dict = None) -> dict:
    body = {"query": query, "session_id": session_id, "params": params or {}}
    r = client.post("/trips/generate", json=body)
    assert r.status_code == 200
    events = []
    for line in r.text.split("\n"):
        if line.startswith("data: ") and line.strip() != "data: [DONE]":
            import json
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return next(e for e in events if e.get("event") == "draft")["trip"]


def test_personal_scene_skips_policy_and_approval(client):
    """个人出游豁免：不触发政策检查与审批，行程直接生效"""
    trip = _generate_draft(client, "下周去杭州玩两天", "pe_user")
    assert trip["scene"] == "personal"

    rc = client.post("/trips/confirm", json={"trip": trip, "session_id": "pe_user"})
    assert rc.status_code == 200
    body = rc.json()
    assert body["events"] == [], "个人出游不应有政策/审批事件"
    assert body["trip"]["status"] != "pending_approval"


def test_confirm_with_employee_requires_approval_then_approve_effective(client):
    """完整审批闭环：员工确认 → 需审批行程挂起 → 主管通过 → 行程生效"""
    _seed_employee("emp_boss", "李明远", level="director")
    _seed_employee("emp_worker", "王晓", level="junior", manager_id="emp_boss")
    # 员工无个人场景（business 类草案），政策要求审批
    client.post("/policies", json={
        "name": "全员审批政策", "level": "junior",
        "requires_approval": True, "hotel_limit": 500,
    })

    trip = _generate_draft(client, "下周去北京出差两天", "emp_worker", params={"scene": "business"})
    rc = client.post("/trips/confirm", json={"trip": trip, "session_id": "emp_worker"})
    assert rc.status_code == 200
    body = rc.json()
    events = body["events"]
    trip_id = body["trip_id"]

    assert any(e.get("event") == "policy" for e in events), "员工行程应做政策检查"
    approval_events = [e for e in events if e.get("event") == "approval"]
    assert approval_events, "需要审批的政策应自动发起审批"
    approval_id = approval_events[0]["approval_id"]

    # 审批门禁：待审批行程不可修改、不可重排
    trip_now = client.get(f"/trips/{trip_id}").json()
    assert trip_now["status"] == "pending_approval"
    r_upd = client.put(f"/trips/{trip_id}", json={"data": {"title": "偷改"}})
    assert r_upd.status_code == 409

    # 主管通过 → 行程生效（审批接口要求声明身份，且须是该单的审批人）
    ra = client.post(f"/approvals/{approval_id}/approve",
                     json={"comment": "同意"}, params={"session_id": "emp_boss"})
    assert ra.status_code == 200
    assert client.get(f"/trips/{trip_id}").json()["status"] == "planned"

    # 审批列表可查（enrich 补齐姓名；已通过的按状态过滤）
    rl = client.get("/approvals",
                    params={"approver_id": "emp_boss", "status": "approved",
                            "session_id": "emp_boss"}).json()
    assert rl["count"] >= 1
    assert rl["approvals"][0]["approver"]["name"] == "李明远"


def test_reject_cancels_trip(client):
    """主管拒绝 → 行程作废"""
    _seed_employee("emp_boss2", "赵主管", level="director")
    _seed_employee("emp_worker2", "钱晓", level="junior", manager_id="emp_boss2")
    client.post("/policies", json={
        "name": "审批政策B", "level": "junior", "requires_approval": True,
    })

    trip = _generate_draft(client, "下周去上海出差三天", "emp_worker2", params={"scene": "business"})
    rc = client.post("/trips/confirm", json={"trip": trip, "session_id": "emp_worker2"})
    approval_id = next(
        e["approval_id"] for e in rc.json()["events"] if e.get("event") == "approval"
    )
    trip_id = rc.json()["trip_id"]

    rr = client.post(f"/approvals/{approval_id}/reject",
                     json={"comment": "预算超标"}, params={"session_id": "emp_boss2"})
    assert rr.status_code == 200
    assert client.get(f"/trips/{trip_id}").json()["status"] == "cancelled"


def test_non_employee_no_auto_approval(client):
    """无员工档案：政策豁免，不发起审批（避免「说必须审批、实际无人审批」哑雷）"""
    trip = _generate_draft(client, "下周去广州出差两天", "plain_user")
    rc = client.post("/trips/confirm", json={"trip": trip, "session_id": "plain_user"})
    assert rc.status_code == 200
    assert rc.json()["events"] == []


def test_double_approve_rejected(client):
    """同一审批不能通过两次（状态机守卫）"""
    _seed_employee("emp_boss3", "孙主管", level="director")
    _seed_employee("emp_worker3", "周晓", level="junior", manager_id="emp_boss3")
    client.post("/policies", json={
        "name": "审批政策C", "level": "junior", "requires_approval": True,
    })

    trip = _generate_draft(client, "下周去深圳出差两天", "emp_worker3", params={"scene": "business"})
    rc = client.post("/trips/confirm", json={"trip": trip, "session_id": "emp_worker3"})
    approval_id = next(
        e["approval_id"] for e in rc.json()["events"] if e.get("event") == "approval"
    )

    ok = client.post(f"/approvals/{approval_id}/approve", json={}, params={"session_id": "emp_boss3"})
    assert ok.status_code == 200
    r2 = client.post(f"/approvals/{approval_id}/approve", json={}, params={"session_id": "emp_boss3"})
    assert r2.status_code == 400, "非待审批状态再审批必须 400"


# ---------------------------------------------------------------------------
# 鉴权加固（2026-09-25）：审批接口不得匿名可调
# ---------------------------------------------------------------------------
def _seed_approval_fixture(client):
    """建一套 员工+主管+需审批政策+待审批行程，返回 (trip_id, approval_id)。"""
    _seed_employee("apr_boss", "钱主管", level="director")
    _seed_employee("apr_worker", "吴晓", level="junior", manager_id="apr_boss")
    client.post("/policies", json={
        "name": "鉴权用审批政策", "level": "junior", "requires_approval": True,
    })
    trip = _generate_draft(client, "下周去成都出差两天", "apr_worker", params={"scene": "business"})
    rc = client.post("/trips/confirm", json={"trip": trip, "session_id": "apr_worker"})
    approval_id = next(
        e["approval_id"] for e in rc.json()["events"] if e.get("event") == "approval"
    )
    return rc.json()["trip_id"], approval_id


def test_approval_endpoints_reject_anonymous(client):
    """完全未声明身份时，审批四个接口一律 401（旧版放任任何人开单并当场批掉）"""
    trip_id, approval_id = _seed_approval_fixture(client)

    assert client.get("/approvals").status_code == 401
    assert client.get(f"/approvals/{approval_id}").status_code == 401
    assert client.post("/approvals", json={
        "trip_id": trip_id, "employee_id": "apr_worker", "approver_id": "apr_boss",
    }).status_code == 401
    assert client.post(f"/approvals/{approval_id}/approve", json={}).status_code == 401
    assert client.post(f"/approvals/{approval_id}/reject", json={}).status_code == 401
    assert client.post(f"/approvals/{approval_id}/cancel").status_code == 401


def test_approve_forbidden_for_bystander(client):
    """非审批人（同公司其他员工）不能审批：403，且行程状态不受影响"""
    trip_id, approval_id = _seed_approval_fixture(client)

    r = client.post(f"/approvals/{approval_id}/approve",
                    json={"comment": "我自己批"}, params={"session_id": "apr_worker"})
    assert r.status_code == 403, "申请人不能审批自己的单"
    assert client.get(f"/trips/{trip_id}").json()["status"] == "pending_approval"

    r2 = client.post(f"/approvals/{approval_id}/approve",
                     json={}, params={"session_id": "someone_else"})
    assert r2.status_code == 403


def test_non_admin_list_scoped_to_self(client):
    """非管理员的审批列表被强制收敛到「与我相关」，改 query 参数读不到别人的单"""
    _, approval_id = _seed_approval_fixture(client)
    r = client.get("/approvals", params={"session_id": "outsider"})
    assert r.status_code == 200
    assert all(
        a.get("employee_id") == "outsider" or a.get("approver_id") == "outsider"
        for a in r.json()["approvals"]
    ), "非管理员不应看到与自己无关的审批单"


def test_manual_approval_flips_trip_then_approve_is_effective(client):
    """手工建单必须同步把行程置为待审批，否则审批通过后行程状态永远不会变

    注意：Agent 生成的草案自带 status=planned，无审批时确认后即为「已规划」；
    所以这里刻意用手工构造的无状态行程（真实数据里 9/11 条正是这种形态），
    它对「建单不置位」的缺陷最敏感。
    """
    _seed_employee("man_boss", "郑主管", level="director")
    _seed_employee("man_worker", "冯晓", level="junior", manager_id="man_boss")

    trip = {"title": "西安客户拜访", "destination": "西安", "scene": "business",
            "start_date": "2026-10-01", "end_date": "2026-10-02", "budget_total": 5000}
    rc = client.post("/trips/confirm", json={"trip": trip, "session_id": "man_worker"})
    assert rc.status_code == 200
    trip_id = rc.json()["trip_id"]
    assert rc.json()["events"] == [], "无政策命中时不应自动发起审批"
    assert client.get(f"/trips/{trip_id}").json().get("status") in (None, ""), \
        "手工构造的行程确认后应无状态"

    r = client.post("/approvals", json={
        "trip_id": trip_id, "approver_id": "man_boss", "remark": "手工发起",
    }, params={"session_id": "man_worker"})
    assert r.status_code == 200, r.text
    approval_id = r.json()["approval_id"]
    assert r.json()["approval"]["employee_id"] == "man_worker", "申请人应取登录态"
    assert client.get(f"/trips/{trip_id}").json()["status"] == "pending_approval"

    ra = client.post(f"/approvals/{approval_id}/approve", json={},
                     params={"session_id": "man_boss"})
    assert ra.status_code == 200
    assert client.get(f"/trips/{trip_id}").json()["status"] == "planned"


def test_create_approval_cannot_impersonate(client):
    """普通用户不能在请求体里替别人开审批单"""
    _seed_employee("imp_boss", "许主管", level="director")
    _seed_employee("imp_worker", "何晓", level="junior", manager_id="imp_boss")
    r = client.post("/approvals", json={
        "trip_id": "trip_不存在", "employee_id": "imp_worker", "approver_id": "imp_boss",
    }, params={"session_id": "attacker"})
    assert r.status_code == 403, "冒名发起审批必须被拒"


# ---------------------------------------------------------------------------
# 「我的档案」：v3 切型漏掉的路由（ProfileStore 一直存在，前端整页 404）
# ---------------------------------------------------------------------------
def test_profile_roundtrip(client):
    """档案读写 + 常用同行人（响应形状须与前端 api/planner.js 契约一致）"""
    r = client.get("/users/me/profile", params={"session_id": "prof_user"})
    assert r.status_code == 200
    assert r.json()["profile"]["user_id"] == "prof_user"

    r = client.put("/users/me/profile", json={"travel_style": "relaxed"},
                   params={"session_id": "prof_user"})
    assert r.status_code == 200
    assert r.json()["profile"]["travel_style"] == "relaxed"

    assert client.put("/users/me/profile", json={},
                      params={"session_id": "prof_user"}).status_code == 400

    r = client.post("/users/me/companions",
                    json={"name": "张小美", "role": "child", "age": 9},
                    params={"session_id": "prof_user"})
    assert r.status_code == 200
    assert r.json()["companions"][0]["name"] == "张小美"

    r = client.get("/users/me/companions", params={"session_id": "prof_user"})
    assert r.status_code == 200
    assert len(r.json()["companions"]) == 1
