"""企业智行 v3 · Agent 层测试：工具总线 / 进程内工具 / 流式澄清契约"""
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
from core.agent.intent import IntentRouter, Intent  # noqa: E402
from core.agent.registry import ToolRegistry, ToolResult  # noqa: E402
from core.agent.handlers import ToolHandlers  # noqa: E402
from shared.config import settings  # noqa: E402


@pytest.fixture()
def client_llm_stub(tmp_path, monkeypatch):
    """LLM「可用但 chat_json 返回空」——走真实管线，不打网络"""
    monkeypatch.setattr(settings, "trip_data_dir", str(tmp_path / "trips"))
    monkeypatch.setattr(settings, "profile_data_dir", str(tmp_path / "profiles"))
    monkeypatch.setattr(settings, "template_data_dir", str(tmp_path / "templates"))
    monkeypatch.setattr(settings, "embedding_provider", "none")

    with TestClient(core_main.app) as c:
        c.headers.update({"X-API-Key": settings.dev_api_key})
        llm = core_deps.llm_manager
        monkeypatch.setattr(llm, "is_available", lambda: True)
        monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {})
        yield c


def _parse_sse(text: str) -> list:
    events = []
    for line in text.split("\n"):
        if line.startswith("data: ") and line.strip() != "data: [DONE]":
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


# ---------------------------------------------------------------------------
# 意图路由
# ---------------------------------------------------------------------------
def test_intent_router_classification():
    assert IntentRouter().classify("帮我规划北京三日游") == Intent.PLAN
    assert IntentRouter().classify("查看我的行程") == Intent.MANAGE
    assert IntentRouter().classify("护照丢了怎么办") == Intent.EMERGENCY
    assert IntentRouter().classify("当地有什么好吃的") == Intent.CHAT


# ---------------------------------------------------------------------------
# 工具总线
# ---------------------------------------------------------------------------
def test_tool_registry_unknown_tool():
    reg = ToolRegistry()
    res = reg.execute("no_such_tool")
    assert res["success"] is False
    assert "未知工具" in res["data"]


def test_tool_registry_exception_captured():
    reg = ToolRegistry()

    def boom(**kwargs):
        raise RuntimeError("炸了")

    reg.register("boom", boom, "会炸的工具")
    res = reg.execute("boom")
    assert res["success"] is False
    assert "炸了" in res["data"]


def test_tool_result_passthrough():
    reg = ToolRegistry()
    reg.register("ok", lambda **kw: ToolResult(data="一切正常"), "正常工具")
    assert reg.execute("ok")["data"] == "一切正常"


# ---------------------------------------------------------------------------
# 进程内管理工具（v3：不再经 HTTP 回调）
# ---------------------------------------------------------------------------
def test_manage_trip_lists_and_deletes_in_process(client_llm_stub):
    # 先造一条已落库行程（显式给场景 + 绝对日期，走模板直出）
    r = client_llm_stub.post("/trips/generate", json={
        "query": "9月28号去杭州玩两天", "session_id": "mgr_user",
        "params": {"scene": "personal"},
    })
    draft = next(e for e in _parse_sse(r.text) if e.get("event") == "draft")
    client_llm_stub.post("/trips/confirm", json={"trip": draft["trip"], "session_id": "mgr_user"})

    # 与 Agent 同一实例的进程内工具
    handlers = ToolHandlers(
        llm_manager=core_deps.llm_manager,
        trip_store=core_deps.trip_store,
        approval_engine=core_deps.approval_engine,
        policy_service=core_deps.policy_service,
    )
    res = handlers.manage_trip("查看行程", session_id="mgr_user", state={"user_id": "mgr_user"})
    assert res.success and "杭州" in res.data

    res2 = handlers.manage_trip("删除这个行程", session_id="mgr_user", state={"user_id": "mgr_user"})
    assert res2.success and "已删除" in res2.data
    assert core_deps.trip_store.list_by_user("mgr_user") == []


# ---------------------------------------------------------------------------
# 流式 Agent 对话：澄清帧契约（SSE）
# ---------------------------------------------------------------------------
def test_agent_stream_clarify_contract(client_llm_stub):
    """缺参时 Agent 流必须发 clarify 帧（带缺参清单），而非硬造行程"""
    r = client_llm_stub.post("/agent/chat/stream", json={
        "query": "规划一次去杭州的个人出游", "session_id": "agent_v3",
    })
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [e.get("event") for e in events]
    assert "intent" in kinds
    assert "clarify" in kinds, f"缺参应发 clarify 帧，实际帧序列: {kinds}"
    clarify = next(e for e in events if e.get("event") == "clarify")
    # v3：规则部分命中会补位进参数——目的地已抽出，澄清只问剩下三项
    assert set(clarify["missing"]) == {"scene", "start_date", "days"}
    assert clarify["params"].get("destination") == "杭州", "目的地已抽出，澄清不得重问"
    assert "respond" in kinds


def test_agent_stream_confirm_flow(client_llm_stub):
    """Agent 流内完成 生成→确认→落库 全链路（v3 进程内，无 HTTP 回调）"""
    sid = "agent_confirm_v3"
    # 规则抽取全覆盖的句式（场景/日期/天数/目的地齐全）→ 直出草案
    r1 = client_llm_stub.post("/agent/chat/stream", json={
        "query": "9月28号去西安出差2天", "session_id": sid,
    })
    events1 = _parse_sse(r1.text)
    confirm = next((e for e in events1 if e.get("event") == "confirm"), None)
    assert confirm is not None, "信息齐备后应出确认卡帧"
    assert confirm["trip"]["destination"] == "西安"

    # 用户回复「确认」→ confirm 阶段分流 → trip_saved
    r2 = client_llm_stub.post("/agent/chat/stream", json={
        "query": "确认", "session_id": sid,
    })
    events2 = _parse_sse(r2.text)
    saved = next((e for e in events2 if e.get("event") == "trip_saved"), None)
    assert saved is not None, "确认后应发 trip_saved 帧"
    assert saved.get("trip_id")

    # 落库可见
    lst = client_llm_stub.get("/trips", params={"session_id": sid}).json()
    assert lst["count"] == 1
