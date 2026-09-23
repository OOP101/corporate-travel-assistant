"""身份 / 鉴权测试

覆盖三件事：
  1. `SignedSession` 无状态签名 token 的往返与各类伪造（换 payload 保签名、
     改签名、错密钥、过期、垃圾串）；
  2. planner-core 的 `resolve_user_id` 取值优先级（登录态 > 显式 session_id >
     API Key 的 workspace），以及「带了 Bearer 但验不过」直接 401 的第三种状态；
  3. 多用户数据隔离 —— 两个用户各自的画像与行程不互相可见。
"""
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

PLANNER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "planner-core"
)
# 三个服务都有顶层 api 包，必须保证 planner-core 在 sys.path 最前，
# 否则 api.main 会解析到其他服务的同名包（其他服务测试会把自己的目录插到 [0]）
if PLANNER_DIR in sys.path:
    sys.path.remove(PLANNER_DIR)
sys.path.insert(0, PLANNER_DIR)

for _mod in [m for m in list(sys.modules) if m == "api" or m.startswith("api.")]:
    del sys.modules[_mod]

import api.main as planner_main  # noqa: E402
from shared.config import settings  # noqa: E402
from shared.middleware.session import SignedSession  # noqa: E402

assert "planner-core" in planner_main.__file__.replace("\\", "/").lower(), (
    f"api.main 解析到了错误的服务: {planner_main.__file__}"
)

SECRET = "test-session-secret"
TTL = 3600


def _token(username: str, ttl: int = TTL, secret: str = SECRET) -> str:
    return SignedSession.encode({"username": username, "role": "user"}, secret, ttl)


def _auth(username: str) -> dict:
    return {"Authorization": f"Bearer {_token(username)}"}


# ---------------------------------------------------------------------------
# 一、SignedSession 签名原语
# ---------------------------------------------------------------------------
class TestSignedSession:
    def test_roundtrip(self):
        body = SignedSession.decode(_token("alice"), SECRET)
        assert body["username"] == "alice"
        assert body["exp"] > time.time()

    def test_rejects_swapped_payload_with_stolen_signature(self):
        """换 payload 保签名 —— 提权最直接的一种伪造，必须挡下。"""
        _, _, stolen_sig = _token("alice").partition(".")
        forged_payload = _token("admin").partition(".")[0]
        assert SignedSession.decode(f"{forged_payload}.{stolen_sig}", SECRET) is None

    def test_rejects_tampered_signature(self):
        payload, _, sig = _token("alice").partition(".")
        flipped = ("a" if sig[0] != "a" else "b") + sig[1:]
        assert SignedSession.decode(f"{payload}.{flipped}", SECRET) is None

    def test_rejects_wrong_secret(self):
        assert SignedSession.decode(_token("alice"), "another-secret") is None

    def test_rejects_expired(self):
        assert SignedSession.decode(_token("alice", ttl=-1), SECRET) is None

    @pytest.mark.parametrize("garbage", ["", "abc", "a.b", "...", "!!.??", "no-dot-here"])
    def test_rejects_garbage(self, garbage):
        assert SignedSession.decode(garbage, SECRET) is None


# ---------------------------------------------------------------------------
# 二、resolve_user_id 优先级 + 多用户隔离（走 FastAPI 端点）
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "trip_data_dir", str(tmp_path / "trips"))
    monkeypatch.setattr(settings, "profile_data_dir", str(tmp_path / "profiles"))
    monkeypatch.setattr(settings, "template_data_dir", str(tmp_path / "templates"))
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_provider", "none")
    # 本测试自己签发 token，故把密钥固定住（生产由 .env 的 SESSION_SECRET 提供）
    monkeypatch.setattr(settings, "session_secret", SECRET)

    with TestClient(planner_main.app) as c:
        c.headers.update({"X-API-Key": settings.dev_api_key})
        yield c


def test_bearer_identity_wins(client):
    r = client.get("/users/me/profile", headers=_auth("alice"))
    assert r.status_code == 200
    assert r.json()["user_id"] == "alice"


def test_without_bearer_falls_back_to_workspace(client):
    assert client.get("/users/me/profile").json()["user_id"] == "default"


def test_invalid_bearer_is_rejected(client):
    """带了 Bearer 却验不过 —— 必须拒绝，不能落 workspace 桶。

    落桶会把「登录态失效」伪装成「查无数据」：/trips 按归属过滤会返回
    200 + 空数组，前端渲染成「还没有行程」，用户查不到任何原因。
    """
    r = client.get("/users/me/profile", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_expired_bearer_is_rejected(client):
    """过期 token 同理 —— 明确告知重新登录，而不是静默清空用户视野。"""
    r = client.get("/users/me/profile", headers={"Authorization": f"Bearer {_token('alice', ttl=-1)}"})
    assert r.status_code == 401


def test_profiles_are_isolated_per_user(client):
    client.put("/users/me/profile", json={"travel_style": "relaxed"}, headers=_auth("alice"))
    client.put("/users/me/profile", json={"travel_style": "compact"}, headers=_auth("bob"))

    assert client.get("/users/me/profile", headers=_auth("alice")).json()["profile"]["travel_style"] == "relaxed"
    assert client.get("/users/me/profile", headers=_auth("bob")).json()["profile"]["travel_style"] == "compact"
    # 未登录者落 workspace 桶，拿到的只是默认骨架，看不到任何人的画像值
    anon = client.get("/users/me/profile").json()["profile"]["travel_style"]
    assert anon not in ("relaxed", "compact")


def test_trip_list_is_isolated_per_user(client):
    # 用 planner_main.deps 而非 `from api import deps`：多个测试文件都在改 sys.path，
    # 运行时 `api` 可能已解析到别的服务，走 main 的命名空间才稳。
    deps = planner_main.deps

    deps.trip_store.save({"title": "alice 的行程", "user_id": "alice"})
    deps.trip_store.save({"title": "bob 的行程", "user_id": "bob"})

    alice = client.get("/trips", headers=_auth("alice")).json()
    assert [t["title"] for t in alice["trips"]] == ["alice 的行程"]

    bob = client.get("/trips", headers=_auth("bob")).json()
    assert [t["title"] for t in bob["trips"]] == ["bob 的行程"]

    # 未登录只看到 workspace 桶（上面两条都不属于它）
    assert client.get("/trips").json()["trips"] == []


def test_trip_ownership_denied_across_users(client):
    deps = planner_main.deps

    trip_id = deps.trip_store.save({"title": "alice 的行程", "user_id": "alice"})
    # 属主可读
    assert client.get(f"/trips/{trip_id}", headers=_auth("alice")).status_code == 200
    # 他人按 404 拒绝（不暴露行程存在性）
    assert client.get(f"/trips/{trip_id}", headers=_auth("bob")).status_code == 404
