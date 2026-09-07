"""
和风天气客户端 —— 目的地逐日天气预报。

模式：
  - 真实模式：调用和风天气 API（需配置 weather_api_key）
  - 降级模式：weather_api_key 为空或调用失败 → 返回 None，由调用方兜底

所有方法对「无 key / 网络异常 / 解析失败」都返回 None，不抛异常。
"""
import logging
from typing import Dict, List, Optional

from shared.config import settings
from shared.http_client import ServiceClient

logger = logging.getLogger("shared.geo.qweather")

_QWEATHER_GEO = "https://devapi.qweather.com/geo/v2/city/lookup"
_QWEATHER_7D = "https://devapi.qweather.com/v7/weather/7d"


class QWeatherClient:
    """和风天气客户端。"""

    def __init__(self):
        self._key = settings.weather_api_key
        self._base = settings.weather_base_url or "https://devapi.qweather.com"
        self._client = ServiceClient(timeout=15)

    # ------------------------------------------------------------------
    # 逐日天气预报（未来 7 天）
    # ------------------------------------------------------------------
    def forecast_7d(self, location: str) -> Optional[List[Dict]]:
        location = (location or "").strip()
        if not self._key or not location:
            return None
        try:
            # 步骤1：城市 ID 查询
            geo = self._client.get(
                _QWEATHER_GEO, params={"location": location, "key": self._key}
            )
            locs = geo.get("location") or []
            if not locs:
                logger.warning(f"和风天气城市查找失败: {location}")
                return None
            city_id = locs[0]["id"]

            # 步骤2：逐日预报
            data = self._client.get(
                _QWEATHER_7D, params={"location": city_id, "key": self._key}
            )
            daily = data.get("daily") or []
            out = []
            for d in daily:
                out.append({
                    "date": d.get("fxDate", ""),
                    "cond_day": d.get("textDay", ""),
                    "cond_night": d.get("textNight", ""),
                    "temp_max": int(d.get("tempMax", 0) or 0),
                    "temp_min": int(d.get("tempMin", 0) or 0),
                    "precip": d.get("precip", ""),
                    "wind_day": d.get("windDirDay", ""),
                })
            return out or None
        except Exception as e:
            logger.error(f"和风天气查询失败 ({location}): {e}")
            return None
