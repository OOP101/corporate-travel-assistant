"""shared.llm.manager 测试：chat_json 解析与重试、流式错误不混入正文"""
import json
import types

import pytest
import requests

from shared.llm import LLMManager, LLMError


def make_manager():
    m = LLMManager()
    m.register("openai_compatible", api_key="sk-test", base_url="http://llm.test/v1", model="test-model")
    return m


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json; charset=utf-8"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_is_available_depends_on_key():
    m = make_manager()
    assert m.is_available() is True
    m2 = LLMManager()
    m2.register("openai_compatible", api_key="", base_url="http://x", model="x")
    assert m2.is_available() is False


def test_chat_json_parses_valid_output(monkeypatch):
    m = make_manager()
    content = json.dumps({"destination": "成都", "days": 3})
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **kw: FakeResp({"choices": [{"message": {"content": content}}], "usage": {}}),
    )
    assert m.chat_json([{"role": "user", "content": "q"}])["destination"] == "成都"


def test_chat_json_strips_markdown_fence(monkeypatch):
    m = make_manager()
    content = "```json\n{\"ok\": true}\n```"
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **kw: FakeResp({"choices": [{"message": {"content": content}}], "usage": {}}),
    )
    assert m.chat_json([{"role": "user", "content": "q"}])["ok"] is True


def test_chat_json_retries_once_then_raises_llm_error(monkeypatch):
    m = make_manager()
    calls = {"n": 0}
    bad = "这不是JSON输出"

    def fake_post(*a, **kw):
        calls["n"] += 1
        return FakeResp({"choices": [{"message": {"content": bad}}], "usage": {}})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(LLMError):
        m.chat_json([{"role": "user", "content": "q"}], timeout=3)
    assert calls["n"] == 2  # 首次 + 重试一次


def test_chat_stream_raises_llm_error_instead_of_error_text(monkeypatch):
    """网络异常必须抛 LLMError，不得把错误文本当正文 chunk yield（批次1 修复回归）"""
    m = make_manager()

    def fake_post(*a, **kw):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "post", fake_post)
    chunks = []
    with pytest.raises(LLMError):
        for chunk in m.chat_stream([{"role": "user", "content": "q"}], timeout=3):
            chunks.append(chunk)
    assert not any("[ERROR]" in c for c in chunks)  # 无错误文本混入正文
