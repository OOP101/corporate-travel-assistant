"""shared.middleware.auth 测试：后门 key 环境收窄、workspace 注册校验"""
import os

from shared.middleware.auth import APIKeyAuth


def test_registered_key_validates():
    auth = APIKeyAuth()
    key = auth.register_workspace("default", "ak_real")
    assert key == "ak_real"
    assert auth.validate("ak_real") == "default"


def test_unknown_key_rejected():
    auth = APIKeyAuth()
    assert auth.validate("ak_unknown_123") is None
    assert auth.validate("") is None


def test_dev_backdoor_enabled_by_default():
    os.environ.pop("APP_ENV", None)
    auth = APIKeyAuth()
    assert auth.validate("ak_dev_local") == "default"
    assert auth.validate("ak_test_whatever") == "default"


def test_dev_backdoor_disabled_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    auth = APIKeyAuth()
    assert auth.validate("ak_dev_local") is None
    assert auth.validate("ak_test_whatever") is None


def test_registered_key_still_works_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    auth = APIKeyAuth()
    auth.register_workspace("default", "ak_prod_key")
    assert auth.validate("ak_prod_key") == "default"
