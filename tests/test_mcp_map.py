"""腾讯地图 MCP 客户端测试（2026-09-21）。

背景：接入腾讯位置服务官方 MCP Server（SSE）作为地图实时数据源，
地图类问答先实查再注入上下文，失败静默回退（与 shared/geo 铁律一致）。

覆盖：
  1. 动作路由：驾车/公交/步行路线、距离矩阵、地点搜索、地理编码
     → 正确的 MCP 工具名与参数（尾部疑问词剥离）
  2. 参数抽不出 → None（不硬调 MCP）
  3. from_env：无 Key → 功能关闭；ENABLED=0 → 强制关闭
  4. 同步门面：_acall 桩返回正常透传；异常 → None（绝不抛出）
  5. 上下文注入：_map_mcp_context 格式与静默回退

不依赖网络与真实 MCP Server（route_action 纯本地；query 用桩注入）。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB_DIR = os.path.join(ROOT, "services", "journey-hub")


@pytest.fixture()
def mcp_mod():
    if HUB_DIR in sys.path:
        sys.path.remove(HUB_DIR)
    sys.path.insert(0, HUB_DIR)
    for _m in [m for m in list(sys.modules) if m == "tools" or m.startswith("tools.")]:
        del sys.modules[_m]
    from tools.mcp_map import TencentMapMCP, route_action
    return TencentMapMCP, route_action


# ---------------------------------------------------------------------------
# 一、动作路由
# ---------------------------------------------------------------------------
def test_route_driving(mcp_mod):
    _, route = mcp_mod
    assert route("从西安北站到钟楼怎么走") == (
        "directionDriving", {"from": "西安北站", "to": "钟楼"})


def test_route_transit_and_walking(mcp_mod):
    _, route = mcp_mod
    assert route("从西安北站到钟楼坐地铁怎么走")[0] == "directionTransit"
    assert route("从钟楼到回民街步行怎么走")[0] == "directionWalking"


def test_distance_matrix(mcp_mod):
    _, route = mcp_mod
    tool, args = route("西安北站到钟楼有多远")
    assert tool == "matrix"
    assert args == {"from": "西安北站", "to": "钟楼", "mode": "driving"}


def test_place_suggestion(mcp_mod):
    _, route = mcp_mod
    tool, args = route("在西安附近找火锅")
    assert tool == "placeSuggestion"
    assert args["region"] == "西安"
    assert "火锅" in args["keyword"]


def test_geocoder(mcp_mod):
    _, route = mcp_mod
    tool, args = route("西安钟楼的经纬度是多少")
    assert tool == "geocoder"
    assert args["address"] == "西安钟楼"


def test_unroutable_returns_none(mcp_mod):
    _, route = mcp_mod
    # 无起终点、无搜索词 → 不硬调 MCP
    assert route("怎么去机场") is None
    assert route("今天天气怎么样") is None
    assert route("") is None


# ---------------------------------------------------------------------------
# 二、配置与可用性
# ---------------------------------------------------------------------------
def test_from_env_without_key_disabled(mcp_mod, monkeypatch):
    TencentMapMCP, _ = mcp_mod
    monkeypatch.delenv("TENCENT_MAP_MCP_KEY", raising=False)
    monkeypatch.delenv("TENCENT_MAP_KEY", raising=False)
    monkeypatch.delenv("TENCENT_MAP_MCP_ENABLED", raising=False)
    assert TencentMapMCP.from_env() is None


def test_from_env_kill_switch(mcp_mod, monkeypatch):
    TencentMapMCP, _ = mcp_mod
    monkeypatch.setenv("TENCENT_MAP_MCP_KEY", "TEST-KEY-1234")
    monkeypatch.setenv("TENCENT_MAP_MCP_ENABLED", "0")
    assert TencentMapMCP.from_env() is None


def test_from_env_with_key_enabled(mcp_mod, monkeypatch):
    TencentMapMCP, _ = mcp_mod
    monkeypatch.setenv("TENCENT_MAP_MCP_KEY", "TEST-KEY-1234")
    monkeypatch.delenv("TENCENT_MAP_MCP_ENABLED", raising=False)
    client = TencentMapMCP.from_env()
    assert client is not None and client.is_available()


# ---------------------------------------------------------------------------
# 三、同步门面（_acall 桩注入，不联网）
# ---------------------------------------------------------------------------
class _StubClient:
    """把 _acall 换成桩，验证 query 全流程（路由→调用→透传/静默）。"""

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = []

    async def _acall(self, tool, args):
        self.calls.append((tool, args))
        if self._error:
            raise self._error
        return self._result

    # 复用真实类的方法逻辑：query / is_available 从 TencentMapMCP 借用
    def __getattr__(self, name):
        raise AttributeError(name)


@pytest.fixture()
def stub_cls(mcp_mod):
    TencentMapMCP, _ = mcp_mod

    class StubTencentMapMCP(TencentMapMCP):
        def __init__(self, result=None, error=None):
            super().__init__(key="TEST-KEY")
            self._stub_result = result
            self._stub_error = error
            self.calls = []

        async def _acall(self, tool, args):
            self.calls.append((tool, args))
            if self._stub_error:
                raise self._stub_error
            return self._stub_result

    return StubTencentMapMCP


def test_query_returns_result(mcp_mod, stub_cls):
    stub = stub_cls(result={"tool": "matrix", "args": {}, "text": "距离 12 公里"})
    out = stub.query("西安北站到钟楼有多远")
    assert out is not None and out["tool"] == "matrix"
    assert "距离" in out["text"]


def test_query_error_silent(mcp_mod, stub_cls):
    stub = stub_cls(error=RuntimeError("boom"))
    assert stub.query("从西安北站到钟楼怎么走") is None


def test_query_unroutable_no_call(mcp_mod, stub_cls):
    stub = stub_cls(result={"tool": "x", "args": {}, "text": "y"})
    assert stub.query("今天心情怎么样") is None
    assert stub.calls == []


def test_query_unavailable_no_call(mcp_mod, stub_cls):
    stub = stub_cls(result={"tool": "x", "args": {}, "text": "y"})
    stub._key = ""
    assert stub.query("从A到B怎么走") is None
    assert stub.calls == []


# ---------------------------------------------------------------------------
# 四、上下文注入（ToolHandlers._map_mcp_context）
# ---------------------------------------------------------------------------
@pytest.fixture()
def handlers_mod():
    if HUB_DIR in sys.path:
        sys.path.remove(HUB_DIR)
    sys.path.insert(0, HUB_DIR)
    for _m in [m for m in list(sys.modules) if m == "tools" or m.startswith("tools.")]:
        del sys.modules[_m]
    from tools.handlers import ToolHandlers
    return ToolHandlers


def test_map_context_disabled_when_no_client(handlers_mod):
    ToolHandlers = handlers_mod
    h = ToolHandlers(llm_manager=None)
    assert h.mcp_map is None  # 测试环境无 Key → 功能静默关闭
    assert h._map_mcp_context("从西安北站到钟楼怎么走") == ""


def test_map_context_format(handlers_mod):
    ToolHandlers = handlers_mod
    h = ToolHandlers(llm_manager=None)

    class _Fake:
        def is_available(self):
            return True

        def query(self, q):
            return {"tool": "matrix", "text": "距离约 12 公里，驾车 25 分钟"}

    h.mcp_map = _Fake()
    ctx = h._map_mcp_context("西安北站到钟楼有多远")
    assert "腾讯位置服务 MCP" in ctx and "matrix" in ctx and "12 公里" in ctx


def test_map_context_error_silent(handlers_mod):
    ToolHandlers = handlers_mod
    h = ToolHandlers(llm_manager=None)

    class _Bad:
        def is_available(self):
            return True

        def query(self, q):
            raise RuntimeError("boom")

    h.mcp_map = _Bad()
    assert h._map_mcp_context("西安北站到钟楼有多远") == ""
