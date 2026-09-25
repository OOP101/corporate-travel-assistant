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
    monkeypatch.setattr(settings, "template_data_dir", str(tmp_path / "templates"))
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

    # 主管通过 → 行程生效
    ra = client.post(f"/approvals/{approval_id}/approve", json={"comment": "同意"})
    assert ra.status_code == 200
    assert client.get(f"/trips/{trip_id}").json()["status"] == "planned"

    # 审批列表可查（enrich 补齐姓名；已通过的按状态过滤）
    rl = client.get("/approvals", params={"approver_id": "emp_boss", "status": "approved"}).json()
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

    rr = client.post(f"/approvals/{approval_id}/reject", json={"comment": "预算超标"})
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

    assert client.post(f"/approvals/{approval_id}/approve", json={}).status_code == 200
    r2 = client.post(f"/approvals/{approval_id}/approve", json={})
    assert r2.status_code == 400, "非待审批状态再审批必须 400"
