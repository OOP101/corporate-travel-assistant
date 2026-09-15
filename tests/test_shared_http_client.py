"""shared.http_client 测试：JSON 解析、鉴权头、SSE 流解析"""
import json

import pytest

from shared.http_client import ServiceClient


class FakeHTTPResp:
    """模拟 requests.Response（非流式）"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    """模拟 requests.Session。

    ServiceClient 重构后不再持有长驻 self.session，而是每次请求 `_new_session()`
    新建（规避 keep-alive 半关连接复用导致的偶发 404），故测试改为 patch
    `_new_session`，返回一个记录调用参数的假 Session。
    """

    def __init__(self, resp, captured=None):
        self._resp = resp
        self._captured = captured if captured is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, method, url, params=None, headers=None, timeout=None, **kw):
        self._captured.update(method=method, url=url, params=params, headers=headers)
        return self._resp

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self._captured.update(url=url, headers=headers)
        return self._resp


class FakeSSEResp:
    """模拟 requests.Response（SSE 流式，支持 with 上下文）"""

    def __init__(self, lines):
        self._lines = lines
        self.status_code = 200
        self.headers = {"Content-Type": "text/event-stream"}  # 无 charset

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


def test_get_parses_json_and_sends_api_key(monkeypatch):
    client = ServiceClient(api_key="ak_test_key")
    captured = {}
    monkeypatch.setattr(
        client, "_new_session",
        lambda: FakeSession(FakeHTTPResp({"trips": [], "count": 0}), captured),
    )
    data = client.get("http://planner.test/trips", params={"session_id": "u1"})
    assert data["count"] == 0
    assert captured["method"] == "GET"
    assert captured["url"] == "http://planner.test/trips"
    assert captured["headers"]["X-API-Key"] == "ak_test_key"


def test_http_error_raises(monkeypatch):
    client = ServiceClient(api_key="ak_x")
    monkeypatch.setattr(
        client, "_new_session",
        lambda: FakeSession(FakeHTTPResp({"detail": "no"}, status_code=404)),
    )
    with pytest.raises(Exception):
        client.get("http://planner.test/missing")


def test_post_stream_parses_sse_frames(monkeypatch):
    """SSE 帧解析：data: JSON / [DONE] 终止 / 非法行跳过"""
    client = ServiceClient(api_key="ak_x")
    lines = [
        'data: {"event": "status", "content": "ok"}',
        "",
        "data: not-json-garbage",
        'data: {"event": "done", "trip_id": "trip_1"}',
        "data: [DONE]",
        'data: {"event": "never", "content": "unreachable"}',
    ]
    monkeypatch.setattr(client, "_new_session", lambda: FakeSession(FakeSSEResp(lines)))

    events = list(client.post_stream("http://planner.test/trips/generate", json={}))
    assert [e["event"] for e in events] == ["status", "done"]


def test_default_api_key_header_present():
    client = ServiceClient()
    assert client.default_headers.get("X-API-Key")
