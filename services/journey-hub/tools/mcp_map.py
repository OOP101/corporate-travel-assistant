"""腾讯地图 MCP 客户端 —— 官方 MCP Server（SSE 传输）接入层（2026-09-21）。

通过官方 `mcp` Python SDK 连接腾讯位置服务 MCP Server
（默认 https://mcp.map.qq.com/sse ），把地图实时数据（地理编码 / POI /
路线 / 距离矩阵）注入问答上下文。服务端共 15 个工具（tools/list 实测），
当前按规则路由其中 6 个高频工具：

  geocoder / placeSuggestion /
  directionDriving / directionTransit / directionWalking / matrix

设计铁律（与 shared/geo 一致）：
  - 未配置 Key、规则抽不出参数、连接或调用失败 → 一律返回 None，
    不阻断对话（回退大模型自有知识回答）；
  - 动作路由为纯正则规则（确定性，不额外烧 LLM）；
  - 每次查询独立 SSE 会话（无状态、无跨请求泄漏；握手 ~1s 仅在
    地图类问题命中时发生）。

配置（.env）：
  TENCENT_MAP_MCP_KEY     MCP 专用 Key。注意：MCP 服务端只做裸 Key 调用、
                          无法使用 SK 签名，因此该 Key 的 WebServiceAPI
                          需设为「免鉴权」或「域名白名单」模式；为不影响
                          现网 SN 签名 Key，建议单独申请。空 → 功能关闭。
  TENCENT_MAP_MCP_URL     默认 https://mcp.map.qq.com/sse
  TENCENT_MAP_MCP_ENABLED 显式开关（=0 强制关闭，默认有 Key 即启用）
"""
import asyncio
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("journey-hub.mcp-map")

DEFAULT_MCP_URL = "https://mcp.map.qq.com/sse"
_CALL_TIMEOUT = 15  # 秒，含 SSE 握手


# ---------------------------------------------------------------------------
# 动作路由（纯正则，确定性）
# ---------------------------------------------------------------------------
_FROM_TO = re.compile(r"从?([\u4e00-\u9fa5A-Za-z0-9]{2,15}?)[到至]([\u4e00-\u9fa5A-Za-z0-9]{2,15}?)[，。？?！!\s]|"
                      r"从?([\u4e00-\u9fa5A-Za-z0-9]{2,15}?)[到至]([\u4e00-\u9fa5A-Za-z0-9]{2,15})$")
_TRANSIT = re.compile(r"公交|地铁|公共交通|坐车|乘车")
_WALK = re.compile(r"步行|走路")
_DISTANCE = re.compile(r"多远|多少公里|多久|多长时间|距离")
_NEARBY = re.compile(r"附近|周边|周围")
_PLACE = re.compile(r"酒店|餐厅|美食|景点|加油站|停车场|机场|高铁站|火车站|超市|银行|厕所")
_CITY = re.compile(r"在([\u4e00-\u9fa5]{2,8}?)[市县]?(附近|周边|周围)")
_KEYWORD = re.compile(r"(?:附近|周边|周围|找(?:一?下)?|搜(?:一?下)?|查(?:一?下)?|推荐)([\u4e00-\u9fa5A-Za-z0-9]{2,12})")
_GEOCODE = re.compile(r"经纬度|坐标|在哪|位置")
# 尾部疑问词/语气词剥离（from/to/address 通用）
_TAIL = re.compile(r"(怎么走|怎么去|如何去|怎么到|需要多久|大?概?多久|有?多远|多长时间|"
                   r"多少公里|的?路线|的?位置|的?经纬度|的?坐标|在哪(里|儿)?|什么位置|吗|呢|[？?！!。，,、\s])+$")
_STOP_PREFIX = re.compile(r"^(有什么|有哪些|哪些|可以|能|帮忙|帮我|推荐|找|搜|查)+")
_STOP_SUFFIX = re.compile(r"(有什么|好吃的|好玩的|推荐的|好玩|好吃)+$")


def _norm(s: str) -> str:
    s = s.strip().rstrip("的")
    while True:
        cleaned = _TAIL.sub("", s).strip()
        if cleaned == s:
            break
        s = cleaned
    return s


def route_action(query: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """把地图类问题路由为 (mcp_tool, args)；抽不出参数返回 None。"""
    q = str(query or "").strip()
    if not q:
        return None

    m = _FROM_TO.search(q)
    if m:
        frm = _norm(m.group(1) or m.group(3))
        to = _norm(m.group(2) or m.group(4))
        if frm and to and frm != to:
            if _DISTANCE.search(q):
                mode = "transit" if _TRANSIT.search(q) else ("walking" if _WALK.search(q) else "driving")
                return ("matrix", {"from": frm, "to": to, "mode": mode})
            if _TRANSIT.search(q):
                return ("directionTransit", {"from": frm, "to": to})
            if _WALK.search(q):
                return ("directionWalking", {"from": frm, "to": to})
            return ("directionDriving", {"from": frm, "to": to})

    if _GEOCODE.search(q):
        addr = _KEYWORD.search(q)
        if addr:
            address = _norm(addr.group(1))
        else:
            # 无明确搜索触发词 → 全句去问题词（「西安钟楼的经纬度是多少」→「西安钟楼」）
            address = re.sub(r"(的?经纬度|的?坐标|在哪(里|儿)?|什么位置|的位置|是多少|是什么|帮我|帮忙|请问)", "", q)
            address = _norm(address)
        return ("geocoder", {"address": address[:30]}) if address else None

    if (_NEARBY.search(q) or _PLACE.search(q)) and not _FROM_TO.search(q):
        kw = _KEYWORD.search(q)
        if kw:
            keyword = _STOP_SUFFIX.sub("", _STOP_PREFIX.sub("", _norm(kw.group(1))))
            if len(keyword) < 2:
                return None
            city = _CITY.search(q)
            region = _norm(city.group(1)) if city else ""
            # placeSearchNearby 需要经纬度（规则抽不出），统一走名称级 suggestion
            return ("placeSuggestion", {"keyword": keyword, "region": region})
    return None


# ---------------------------------------------------------------------------
# MCP 客户端
# ---------------------------------------------------------------------------
class TencentMapMCP:
    """腾讯位置服务 MCP 客户端（每次查询独立 SSE 会话，失败静默回退）。"""

    def __init__(self, key: str, url: str = DEFAULT_MCP_URL, fmt: int = 0):
        self._key = (key or "").strip()
        self._url = url.rstrip("/")
        self._fmt = fmt

    @classmethod
    def from_env(cls) -> Optional["TencentMapMCP"]:
        """按 .env 构建；未配置/显式关闭/mcp SDK 缺失 → None（功能关闭）。"""
        if os.environ.get("TENCENT_MAP_MCP_ENABLED", "").strip() == "0":
            return None
        key = (os.environ.get("TENCENT_MAP_MCP_KEY")
               or os.environ.get("TENCENT_MAP_KEY") or "").strip()
        if not key:
            return None
        url = os.environ.get("TENCENT_MAP_MCP_URL", DEFAULT_MCP_URL).strip() or DEFAULT_MCP_URL
        try:
            import mcp.client.sse  # noqa: F401  SDK 缺失 → 关闭功能而非炸服务
        except ImportError:
            logger.warning("mcp SDK 未安装（pip install mcp），腾讯地图 MCP 功能关闭")
            return None
        return cls(key, url)

    def is_available(self) -> bool:
        return bool(self._key)

    async def _acall(self, tool: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        url = f"{self._url}?key={self._key}&format={self._fmt}"
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
                text = res.content[0].text if res.content else ""
                return {"tool": tool, "args": args, "text": text}

    def query(self, query_text: str) -> Optional[Dict[str, Any]]:
        """同步门面：路由动作 → MCP 实查。任何失败返回 None，绝不抛出。"""
        if not self.is_available():
            return None
        plan = route_action(query_text)
        if not plan:
            return None
        tool, args = plan
        try:
            return asyncio.run(asyncio.wait_for(self._acall(tool, args),
                                                timeout=_CALL_TIMEOUT))
        except Exception as e:  # 网络/协议/事件循环占用 → 一律静默
            logger.warning(f"腾讯地图 MCP 调用失败（tool={tool}）: {e}")
            return None
