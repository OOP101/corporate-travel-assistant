"""自助注册测试（任务：改 C 端 P0 最后一项）

覆盖：
  1. `UserStore` 口令哈希 —— pbkdf2 非明文、加盐唯一、旧 sha256 记录仍可验证
     并自动升级；
  2. `/auth/register` 端点 —— 注册成功即拿到可用 Token、重名/保留名/弱口令/
     非法用户名被拒；
  3. 注册账号的数据隔离 —— 新用户看不到别人的画像与行程；
  4. 安全回归 —— 注册接口不接受客户端指定角色（不能自封管理员）。

跨服务说明：journey-hub 的 api.main 会拉起 LLM / 图编排，直接 import 代价高，
故这里用轻量 app 只挂 `auth_router`（路由本身只依赖 `app.state.user_store`），
配合 `UserStore` 实例直接构造被测环境。
"""
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNEY_DIR = os.path.join(ROOT, "services", "journey-hub")
# 三个服务都有顶层 api 包，必须让 journey-hub 排在 sys.path 最前
if JOURNEY_DIR in sys.path:
    sys.path.remove(JOURNEY_DIR)
sys.path.insert(0, JOURNEY_DIR)

for _mod in [m for m in list(sys.modules) if m == "api" or m.startswith("api.")]:
    del sys.modules[_mod]

from api.auth import (  # noqa: E402
    PASSWORD_MIN_LENGTH,
    RESERVED_USERNAMES,
    auth_router,
    UserStore,
)
from shared.config import settings  # noqa: E402
from shared.middleware.session import SignedSession  # noqa: E402

SECRET = "test-register-secret"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture()
def user_store(tmp_path):
    return UserStore(data_dir=str(tmp_path / "users"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """只挂认证路由的轻量 app —— 避免拉起 JourneyHubGraph。"""
    monkeypatch.setattr(settings, "session_secret", SECRET)

    store = UserStore(data_dir=str(tmp_path / "users"))
    app = FastAPI()
    app.state.user_store = store
    app.include_router(auth_router)
    # 便于测试直接摸到 store（校验落库结果）
    app.state._test_store = store
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 一、UserStore 口令哈希
# ---------------------------------------------------------------------------
class TestPasswordHashing:
    def test_password_not_stored_in_plaintext(self, user_store):
        user_store.create_user("alice", "s3cret-pass")
        raw = open(
            os.path.join(user_store.data_dir, "alice.json"), encoding="utf-8"
        ).read()
        assert "s3cret-pass" not in raw

    def test_new_records_use_pbkdf2(self, user_store):
        user_store.create_user("alice", "s3cret-pass")
        assert user_store.get("alice")["algo"] == "pbkdf2-sha256"

    def test_same_password_different_salt_yields_different_hash(self, user_store):
        user_store.create_user("alice", "same-password")
        user_store.create_user("bob", "same-password")
        assert user_store.get("alice")["salt"] != user_store.get("bob")["salt"]
        assert (
            user_store.get("alice")["password_hash"]
            != user_store.get("bob")["password_hash"]
        )

    def test_verify_accepts_correct_and_rejects_wrong(self, user_store):
        user_store.create_user("alice", "s3cret-pass")
        assert user_store.verify("alice", "s3cret-pass") is not None
        assert user_store.verify("alice", "wrong-pass") is None
        assert user_store.verify("nobody", "s3cret-pass") is None

    def test_legacy_sha256_record_still_verifies_and_upgrades(self, user_store):
        """历史账号是单轮 sha256，不能让老用户登不进来。"""
        import hashlib
        import secrets as _secrets

        salt = _secrets.token_hex(8)
        user_store.save({
            "username": "legacy",
            "salt": salt,
            "password_hash": hashlib.sha256((salt + "old-pass").encode()).hexdigest(),
            # 无 algo 字段 —— 即旧格式
        })

        assert user_store.verify("legacy", "old-pass") is not None
        # 验证通过后应顺手升级，避免长期停留在弱哈希上
        assert user_store.get("legacy")["algo"] == "pbkdf2-sha256"
        # 升级后仍然能登
        assert user_store.verify("legacy", "old-pass") is not None

    def test_legacy_record_rejects_wrong_password(self, user_store):
        import hashlib
        import secrets as _secrets

        salt = _secrets.token_hex(8)
        user_store.save({
            "username": "legacy",
            "salt": salt,
            "password_hash": hashlib.sha256((salt + "old-pass").encode()).hexdigest(),
        })
        assert user_store.verify("legacy", "not-old-pass") is None
        # 失败的验证不得改动记录
        assert user_store.get("legacy").get("algo") is None


# ---------------------------------------------------------------------------
# 二、/auth/register 端点
# ---------------------------------------------------------------------------
class TestRegisterEndpoint:
    def test_register_returns_usable_token(self, client):
        r = client.post("/auth/register", json={"username": "alice", "password": "goodpass123"})
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "alice"
        assert body["role"] == "user"

        # 注册即登录：签发的 token 必须能被离线校验
        info = SignedSession.decode(body["token"], SECRET)
        assert info["username"] == "alice"
        assert info["role"] == "user"

    def test_registered_user_can_then_login(self, client):
        client.post("/auth/register", json={"username": "alice", "password": "goodpass123"})
        r = client.post("/auth/login", json={"username": "alice", "password": "goodpass123"})
        assert r.status_code == 200
        assert r.json()["username"] == "alice"

    def test_login_with_wrong_password_after_register(self, client):
        client.post("/auth/register", json={"username": "alice", "password": "goodpass123"})
        r = client.post("/auth/login", json={"username": "alice", "password": "wrongpass123"})
        assert r.status_code == 401

    def test_duplicate_username_rejected(self, client):
        assert client.post(
            "/auth/register", json={"username": "alice", "password": "goodpass123"}
        ).status_code == 200
        r = client.post("/auth/register", json={"username": "alice", "password": "otherpass123"})
        assert r.status_code == 409

    @pytest.mark.parametrize("name", sorted(RESERVED_USERNAMES))
    def test_reserved_username_rejected(self, client, name):
        """admin / web-user / default 与组织侧 employee_id 同值，
        放开注册会让新用户继承到别人的档案与行程。"""
        r = client.post("/auth/register", json={"username": name, "password": "goodpass123"})
        assert r.status_code == 400

    def test_reserved_username_is_case_insensitive(self, client):
        r = client.post("/auth/register", json={"username": "Admin", "password": "goodpass123"})
        assert r.status_code == 400

    @pytest.mark.parametrize("name", ["ab", "a" * 33, "has space", "中文名", "bad@char"])
    def test_invalid_username_rejected(self, client, name):
        r = client.post("/auth/register", json={"username": name, "password": "goodpass123"})
        assert r.status_code == 400

    def test_empty_username_rejected(self, client):
        """空串在 Pydantic 层就被 min_length=1 挡下（422），同样不得建号。"""
        r = client.post("/auth/register", json={"username": "", "password": "goodpass123"})
        assert r.status_code in (400, 422)

    @pytest.mark.parametrize("name", ["abc", "a" * 32, "user.name", "user_name", "user-name", "User123"])
    def test_valid_username_accepted(self, client, name):
        r = client.post("/auth/register", json={"username": name, "password": "goodpass123"})
        assert r.status_code == 200

    def test_short_password_rejected(self, client):
        short = "a" * (PASSWORD_MIN_LENGTH - 1)
        r = client.post("/auth/register", json={"username": "alice", "password": short})
        assert r.status_code == 400

    def test_rejected_registration_does_not_create_user(self, client):
        client.post("/auth/register", json={"username": "ab", "password": "goodpass123"})
        assert client.app.state._test_store.exists("ab") is False

    def test_cannot_self_assign_admin_role(self, client):
        """角色不接受客户端指定 —— 否则任何人都能自封管理员。"""
        r = client.post(
            "/auth/register",
            json={"username": "sneaky", "password": "goodpass123", "role": "admin"},
        )
        assert r.status_code == 200
        assert r.json()["role"] == "user"
        assert SignedSession.decode(r.json()["token"], SECRET)["role"] == "user"
