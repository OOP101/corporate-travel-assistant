"""launcher.reset_chat_history 测试：只清对话、保留业务数据，鉴权头正确。

背景：用户诉求是「启动后首页不要有上一次的对话记录，行程保留」。
这条链路分两半 ——
  前端：工作台 URL 带 ?fresh=1 → chatStore 丢 localStorage 快照并跳过服务端历史回放；
  服务端：launcher.reset_chat_history() 调 journey-hub 的
          GET /agent/sessions + POST /agent/session/{id}/clear。
本文件锁定服务端那一半的行为与鉴权。
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def _load_launcher():
    """按文件路径加载 launcher.py（它不在包内，且 import 时会探测环境）。"""
    spec = importlib.util.spec_from_file_location("cjh_launcher", ROOT / "launcher.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cjh_launcher"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# _dev_api_key：必须能拿到非空 key（否则请求会被中间件 401）
# ---------------------------------------------------------------------------
def test_dev_api_key_is_non_empty():
    launcher = _load_launcher()
    key = launcher._dev_api_key()
    assert isinstance(key, str) and key.strip(), "API Key 不能为空，否则清会话请求会被 401 拒绝"


def test_dev_api_key_prefers_env(monkeypatch):
    monkeypatch.setenv("DEV_API_KEY", "ak_from_env")
    launcher = _load_launcher()
    assert launcher._dev_api_key() == "ak_from_env"


def test_dev_api_key_falls_back_to_local_default(monkeypatch, tmp_path):
    """`.env` 读不到时回落开发后门默认值，保证永不因鉴权把启动卡住。"""
    monkeypatch.delenv("DEV_API_KEY", raising=False)
    launcher = _load_launcher()
    launcher.BASE_DIR = tmp_path  # 指向空目录，避开真实 .env
    assert launcher._dev_api_key() == "ak_dev_local"


# ---------------------------------------------------------------------------
# reset_chat_history：清对话 + 不动业务数据 + 服务不可用不抛异常
# ---------------------------------------------------------------------------
@pytest.fixture()
def journey_app():
    """加载 journey-hub app，返回 (app 模块, TestClient)。"""
    sys.path.insert(0, str(ROOT / "services" / "journey-hub"))
    import api.main as m  # noqa: E402

    with TestClient(m.app) as c:
        yield m, c


def test_clear_is_selective_and_keeps_other_sessions(journey_app):
    """清 alice 不能误伤 bob——证明是"按会话清对话"而非"清库"。"""
    m, c = journey_app
    H = {"X-API-Key": "ak_dev_local"}
    assert m.session_manager is not None
    m.session_manager.append("alice", "user", "我下周要去深圳")
    m.session_manager.append("alice", "assistant", "好的，收到。")
    m.session_manager.append("bob", "user", "帮我改一下行程")

    before = c.get("/agent/sessions", headers=H).json()
    assert {s["session_id"] for s in before["sessions"]} == {"alice", "bob"}

    assert c.post("/agent/session/alice/clear", headers=H).status_code == 200

    after = c.get("/agent/sessions", headers=H).json()
    assert {s["session_id"] for s in after["sessions"]} == {"bob"}


def test_sessions_endpoint_shape_matches_launcher_parsing(journey_app):
    """锁定 /agent/sessions 的响应结构 —— launcher 依赖 sessions[].session_id。"""
    m, c = journey_app
    H = {"X-API-Key": "ak_dev_local"}
    m.session_manager.append("carol", "user", "订个票")
    data = c.get("/agent/sessions", headers=H).json()
    assert "sessions" in data and "count" in data
    ids = [s.get("session_id") for s in data["sessions"]]
    assert "carol" in ids


def test_unauthorized_request_is_401(journey_app):
    """不带 key 必须 401 —— launcher 必须带 X-API-Key 才不会被静默挡掉。"""
    _m, c = journey_app
    assert c.get("/agent/sessions").status_code == 401


def test_reset_chat_history_noop_when_server_down(monkeypatch):
    """服务不可用（端口没人听）时静默返回，不抛异常、不阻断启动。"""
    launcher = _load_launcher()
    # 指向一个必然没人监听的端口
    monkeypatch.setattr(
        launcher, "backends_for", lambda mode: [("gateway", "gw", "services/gateway", 9, "x.log")]
    )
    launcher.reset_chat_history("single")  # 不应抛异常
