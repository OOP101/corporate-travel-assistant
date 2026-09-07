"""
腾讯位置服务（腾讯地图）客户端 —— 地理编码 / 驾车路线规划 / POI 酒店候选搜索。

模式：
  - 真实模式：调用腾讯位置服务 WebService API（需配置 tencent_map_key + tencent_map_sk）
  - 降级模式：key 为空 / SK 缺失 / 调用失败 / status!=0 → 返回 None，由调用方兜底

所有方法对「无 key / 网络异常 / 解析失败 / 业务错误码」都返回 None，不抛异常，
保证规划主链路在任何外部依赖异常时都能继续。

签名（SN 校验，与高德的关键差异）：
  高德仅需 key；腾讯位置服务开启 SN 校验后还需 SecretKey(SK) 做签名：
      sig = md5(请求路径 + "?" + 按参数名升序拼接的原始参数 + SecretKey)
  sig 作为额外参数随请求传入。SK 缺失（未开启 SN 校验）时自动跳过签名。
"""
import hashlib
import logging
from typing import Dict, List, Optional

from shared.config import settings
from shared.http_client import ServiceClient

logger = logging.getLogger("shared.geo.tencent")

_TENCENT_BASE = "https://apis.map.qq.com"
_TENCENT_GEOCODE = "/ws/geocoder/v1"
_TENCENT_DRIVING = "/ws/direction/v1/driving"
_TENCENT_POI = "/ws/place/v1/search"


class TencentMapClient:
    """腾讯位置服务（地图）WebService 客户端。"""

    def __init__(self):
        self._key = settings.tencent_map_key
        self._sk = settings.tencent_map_sk
        self._client = ServiceClient(timeout=15)

    @property
    def is_available(self) -> bool:
        """是否已配置 key（供调用方判断是否走真实模式）。"""
        return bool(self._key)

    # ------------------------------------------------------------------
    # 签名：sig = md5(路径?排序参数 + SK)
    # ------------------------------------------------------------------
    def _signed_params(self, path: str, params: Dict[str, str]) -> Dict[str, str]:
        """按参数名升序拼接原始参数，追加 SK 做 md5 签名，返回带 sig 的完整参数。

        SK 缺失（未开启 SN 校验）时直接返回原参数，不签名。
        """
        if not self._sk:
            return params
        items = sorted(params.items(), key=lambda kv: kv[0])
        query = "&".join(f"{k}={v}" for k, v in items)
        raw = f"{path}?{query}{self._sk}"
        sig = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return {**params, "sig": sig}

    # ------------------------------------------------------------------
    # 地理编码：地址 → 经纬度（腾讯返回 lat/lng，注意与高德 lng,lat 相反）
    # ------------------------------------------------------------------
    def geocode(self, address: str) -> Optional[Dict[str, float]]:
        address = (address or "").strip()
        if not self._key or not address:
            return None
        try:
            params = self._signed_params(_TENCENT_GEOCODE, {
                "key": self._key,
                "address": address,
            })
            data = self._client.get(_TENCENT_BASE + _TENCENT_GEOCODE, params=params)
            if data.get("status") != 0:
                logger.warning(f"腾讯地图地理编码业务错误 status={data.get('status')}: {address}")
                return None
            loc = (data.get("result") or {}).get("location") or {}
            if "lat" not in loc or "lng" not in loc:
                return None
            return {
                "lng": float(loc["lng"]),
                "lat": float(loc["lat"]),
                "address": (data.get("result") or {}).get("title", address),
            }
        except Exception as e:
            logger.error(f"腾讯地图地理编码失败 ({address}): {e}")
            return None

    # ------------------------------------------------------------------
    # 驾车路线规划：出发地 → 目的地（from/to 格式为 lat,lng，与高德相反）
    # ------------------------------------------------------------------
    def driving_route(
        self, origin_geo: Dict[str, float], dest_geo: Dict[str, float]
    ) -> Optional[Dict]:
        if not self._key or not origin_geo or not dest_geo:
            return None
        try:
            frm = f"{origin_geo['lat']},{origin_geo['lng']}"
            to = f"{dest_geo['lat']},{dest_geo['lng']}"
            params = self._signed_params(_TENCENT_DRIVING, {
                "key": self._key,
                "from": frm,
                "to": to,
            })
            data = self._client.get(_TENCENT_BASE + _TENCENT_DRIVING, params=params)
            if data.get("status") != 0:
                logger.warning(f"腾讯地图路线规划业务错误 status={data.get('status')}")
                return None
            routes = (data.get("result") or {}).get("routes") or []
            if not routes:
                return None
            r = routes[0]
            return {
                "distance_km": round((int(r.get("distance", 0)) or 0) / 1000, 1),
                "duration_min": int((int(r.get("duration", 0)) or 0) / 60),
            }
        except Exception as e:
            logger.error(f"腾讯地图路线规划失败: {e}")
            return None

    # ------------------------------------------------------------------
    # POI 搜索：酒店结构化候选（boundary 用 nearby 优先，否则 region）
    # ------------------------------------------------------------------
    def poi_hotels(
        self,
        city: str = None,
        geo: Dict[str, float] = None,
        keyword: str = "酒店",
        limit: int = 6,
    ) -> Optional[List[Dict]]:
        if not self._key:
            return None
        if geo:
            boundary = f"nearby({geo['lat']},{geo['lng']},5000)"
        elif city:
            boundary = f"region({city},0)"
        else:
            return None
        params = self._signed_params(_TENCENT_POI, {
            "key": self._key,
            "keyword": keyword,
            "boundary": boundary,
            "page_size": str(limit),
            "page_index": "1",
        })
        try:
            data = self._client.get(_TENCENT_BASE + _TENCENT_POI, params=params)
            if data.get("status") != 0:
                logger.warning(f"腾讯地图 POI 搜索业务错误 status={data.get('status')}")
                return None
            pois = data.get("data") or []
            out = []
            for p in pois[:limit]:
                loc = p.get("location") or {}
                lng = loc.get("lng")
                lat = loc.get("lat")
                out.append({
                    "name": p.get("title", ""),
                    "address": p.get("address", ""),
                    "tel": p.get("tel", ""),
                    "type": p.get("category", ""),
                    "lng": float(lng) if lng is not None else None,
                    "lat": float(lat) if lat is not None else None,
                })
            return out or None
        except Exception as e:
            logger.error(f"腾讯地图 POI 搜索失败: {e}")
            return None
