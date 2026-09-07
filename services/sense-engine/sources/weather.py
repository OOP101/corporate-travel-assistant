"""
天气数据源 —— 目的地天气预报感知

模式：
  - 真实模式：调用和风天气 API（需配置 weather_api_key）
  - Mock 模式：生成模拟天气预报，保证无 API key 也能演示

感知规则：
  - 暴雨/大雪/台风 → critical
  - 大风/高温/雷电 → warning
  - 降温/降雨 → info
"""
import logging
import random
from typing import List

from shared.config import settings
from shared.http_client import ServiceClient
from shared.metrics import monitor_check_counter

from .base import BaseSource, SourceResult

logger = logging.getLogger("sense-engine.sources.weather")

# 天气状况文本 → 内部代码
_WEATHER_TEXT = {
    "clear": "晴",
    "cloudy": "多云",
    "overcast": "阴",
    "light_rain": "小雨",
    "moderate_rain": "中雨",
    "heavy_rain": "暴雨",
    "thunderstorm": "雷阵雨",
    "light_snow": "小雪",
    "heavy_snow": "大雪",
    "fog": "雾",
    "haze": "霾",
    "windy": "大风",
    "hot": "高温",
    "typhoon": "台风",
}

# 极端天气 → (type, severity)
_EXTREME_WEATHER = {
    "heavy_rain": ("weather_heavy_rain", "critical"),
    "heavy_snow": ("weather_heavy_snow", "critical"),
    "typhoon": ("weather_typhoon", "critical"),
    "thunderstorm": ("weather_thunderstorm", "warning"),
    "windy": ("weather_strong_wind", "warning"),
    "hot": ("weather_high_temp", "warning"),
}


class WeatherSource(BaseSource):
    """天气数据源"""

    name = "weather"

    def __init__(self):
        self._client = ServiceClient(timeout=15)
        self._api_key = settings.weather_api_key
        self._base_url = settings.weather_base_url

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def check(self, subscription: dict) -> List[SourceResult]:
        """
        检查目的地天气

        subscription 字段:
            destination: 目的地城市名
        """
        destination = subscription.get("destination", "").strip()
        results: List[SourceResult] = []

        if not destination:
            logger.warning("天气检查缺少 destination 参数")
            return results

        try:
            if self._api_key:
                weather_info = self._fetch_real(destination)
            else:
                weather_info = self._fetch_mock(destination)

            monitor_check_counter.labels(source="weather", status="ok").inc()

        except Exception as e:
            logger.error(f"天气数据源检查失败 ({destination}): {e}")
            monitor_check_counter.labels(source="weather", status="error").inc()
            return results

        # --- 感知规则 ---
        condition = weather_info.get("condition", "clear")
        temp = weather_info.get("temp", 25)

        # 极端天气
        if condition in _EXTREME_WEATHER:
            wtype, severity = _EXTREME_WEATHER[condition]
            text = _WEATHER_TEXT.get(condition, condition)
            results.append(self._make_result(
                type=wtype,
                severity=severity,
                title=f"{destination} 天气预警：{text}",
                message=_build_weather_message(destination, weather_info),
                suggested_action=_weather_action(condition),
                raw_data=weather_info,
            ))

        # 高温补充（温度 >= 37 即使 condition 不是 hot）
        elif temp >= 37 and condition != "hot":
            results.append(self._make_result(
                type="weather_high_temp",
                severity="warning",
                title=f"{destination} 高温预警：{temp}°C",
                message=f"{destination} 当前气温 {temp}°C，请注意防暑降温。",
                suggested_action="出行请做好防晒，携带饮用水，避免长时间户外活动。",
                raw_data=weather_info,
            ))

        if not results:
            text = _WEATHER_TEXT.get(condition, "晴")
            results.append(self._make_result(
                type="weather_normal",
                severity="info",
                title=f"{destination} 天气正常：{text} {temp}°C",
                message=(
                    f"{destination} 当前天气 {text}，气温 {temp}°C，"
                    f"体感温度 {weather_info.get('feels_like', temp)}°C，"
                    f"适宜出行。"
                ),
                raw_data=weather_info,
            ))

        return results

    # ------------------------------------------------------------------
    # 按需直查（问答路径调用，不等监控订阅）
    # ------------------------------------------------------------------
    def query(self, city: str) -> dict:
        """
        按需查询某地实时天气（直查工具，复用于监控同一套采集逻辑）。

        Args:
            city: 城市名（如 "北京"）
        Returns:
            天气信息 dict（含 source / mock / degraded 标记）
        """
        city = (city or "").strip()
        if not city:
            return {"source": "weather", "error": "缺少城市参数", "mock": False}
        try:
            info = self._fetch_real(city) if self._api_key else self._fetch_mock(city)
            info["source"] = "weather"
            return info
        except Exception as e:
            logger.error(f"天气直查失败 ({city})，降级 Mock: {e}")
            info = self._fetch_mock(city)
            info["source"] = "weather"
            info["degraded"] = True
            return info

    # ------------------------------------------------------------------
    # 真实 API（和风天气）
    # ------------------------------------------------------------------
    def _fetch_real(self, location: str) -> dict:
        """调用和风天气 API 获取实时天气"""
        # 先通过 Geo API 查询城市 ID
        geo_url = f"{self._base_url}/geo/v2/city/lookup"
        geo_params = {"location": location, "key": self._api_key}
        geo_data = self._client.get(geo_url, params=geo_params)
        locations = geo_data.get("location", [])
        if not locations:
            logger.warning(f"和风天气未找到城市: {location}")
            return self._fetch_mock(location)

        city_id = locations[0]["id"]

        # 查询实时天气
        weather_url = f"{self._base_url}/v7/weather/now"
        params = {"location": city_id, "key": self._api_key}
        data = self._client.get(weather_url, params=params)
        now = data.get("now", {})

        return {
            "city": location,
            "condition": _qweather_to_code(now.get("text", "")),
            "temp": int(now.get("temp", 25)),
            "feels_like": int(now.get("feels_like", now.get("temp", 25))),
            "humidity": int(now.get("humidity", 50)),
            "wind_speed": now.get("wind_speed", ""),
            "wind_dir": now.get("wind_dir", ""),
            "text": now.get("text", ""),
            "mock": False,
        }

    # ------------------------------------------------------------------
    # Mock 模式
    # ------------------------------------------------------------------
    def _fetch_mock(self, location: str) -> dict:
        """生成模拟天气数据"""
        # 按季节/城市简单模拟，加入随机扰动
        import datetime as _dt
        month = _dt.datetime.now().month

        if month in (6, 7, 8):
            # 夏季：高温/雷阵雨/台风概率高
            conditions = ["clear", "cloudy", "hot", "thunderstorm", "heavy_rain", "typhoon", "haze"]
            temp_base = random.randint(30, 39)
        elif month in (12, 1, 2):
            # 冬季：大雪/大风
            conditions = ["clear", "cloudy", "overcast", "light_snow", "heavy_snow", "windy", "fog"]
            temp_base = random.randint(-5, 8)
        else:
            # 春秋：降雨为主
            conditions = ["clear", "cloudy", "overcast", "light_rain", "moderate_rain", "fog", "windy"]
            temp_base = random.randint(15, 28)

        condition = random.choice(conditions)
        temp = temp_base + random.randint(-3, 3)

        return {
            "city": location,
            "condition": condition,
            "temp": temp,
            "feels_like": temp + random.randint(-2, 3),
            "humidity": random.randint(30, 90),
            "wind_speed": f"{random.randint(5, 40)}km/h",
            "wind_dir": random.choice(["东风", "南风", "西风", "北风", "东南风", "西北风"]),
            "text": _WEATHER_TEXT.get(condition, "晴"),
            "mock": True,
        }


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------
def _qweather_to_code(text: str) -> str:
    """将和风天气文本映射为内部 condition 代码"""
    text = text or ""
    mapping = [
        ("暴雨", "heavy_rain"), ("大雨", "moderate_rain"), ("中雨", "moderate_rain"),
        ("小雨", "light_rain"), ("雷阵雨", "thunderstorm"), ("大雪", "heavy_snow"),
        ("小雪", "light_snow"), ("雾", "fog"), ("霾", "haze"),
        ("晴", "clear"), ("多云", "cloudy"), ("阴", "overcast"),
    ]
    for keyword, code in mapping:
        if keyword in text:
            return code
    return "clear"


def _build_weather_message(city: str, info: dict) -> str:
    """构造天气提醒文案"""
    text = info.get("text", _WEATHER_TEXT.get(info.get("condition", ""), ""))
    return (
        f"{city} 出现{text}天气，当前气温 {info.get('temp', '?')}°C，"
        f"湿度 {info.get('humidity', '?')}%，"
        f"风向 {info.get('wind_dir', '未知')} {info.get('wind_speed', '')}。"
    )


def _weather_action(condition: str) -> str:
    """根据天气状况给出建议"""
    actions = {
        "heavy_rain": "请携带雨具，注意防范城市内涝，避免前往低洼地带。",
        "heavy_snow": "请注意保暖防滑，关注交通管制信息，预留充足出行时间。",
        "typhoon": "请尽量减少外出，关好门窗，关注气象台最新预警。",
        "thunderstorm": "请远离空旷地带和高大物体，避免在户外使用手机。",
        "windy": "请注意防风，远离广告牌和临时搭建物。",
        "hot": "出行请做好防晒，携带饮用水，避免长时间户外活动。",
    }
    return actions.get(condition, "请关注天气变化，合理安排行程。")
