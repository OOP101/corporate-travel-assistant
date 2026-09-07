"""
路况数据源 —— 出行路线实时路况感知

模式：
  - 真实模式：调用腾讯位置服务 API（需配置 tencent_map_key + tencent_map_sk）
  - Mock 模式：生成模拟路况，保证无 API key 也能演示

感知规则：
  - 严重拥堵（指数 >= 4）→ warning
  - 道路封路 → critical
  - 轻度拥堵 → info
"""
import logging
import random
from typing import List

from shared.config import settings
from shared.http_client import ServiceClient
from shared.geo import TencentMapClient
from shared.metrics import monitor_check_counter

from .base import BaseSource, SourceResult

logger = logging.getLogger("sense-engine.sources.traffic")

# 拥堵等级文本
_CONGESTION_TEXT = {
    1: "畅通",
    2: "基本畅通",
    3: "轻度拥堵",
    4: "中度拥堵",
    5: "严重拥堵",
}


class TrafficSource(BaseSource):
    """路况数据源"""

    name = "traffic"

    def __init__(self):
        self._client = ServiceClient(timeout=15)
        self._tm = TencentMapClient()
        self._real_available = self._tm.is_available

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def check(self, subscription: dict) -> List[SourceResult]:
        """
        检查路况

        subscription 字段:
            origin: 出发地（地址或城市名）
            destination: 目的地（地址或城市名）
        """
        origin = subscription.get("origin", "").strip()
        destination = subscription.get("destination", "").strip()
        results: List[SourceResult] = []

        if not origin or not destination:
            logger.warning("路况检查缺少 origin/destination 参数")
            return results

        try:
            if self._real_available:
                traffic_info = self._fetch_real(origin, destination)
            else:
                traffic_info = self._fetch_mock(origin, destination)

            monitor_check_counter.labels(source="traffic", status="ok").inc()

        except Exception as e:
            logger.error(f"路况数据源检查失败 ({origin}→{destination}): {e}")
            monitor_check_counter.labels(source="traffic", status="error").inc()
            return results

        # --- 感知规则 ---
        congestion = traffic_info.get("congestion_level", 1)
        road_closed = traffic_info.get("road_closed", False)

        if road_closed:
            results.append(self._make_result(
                type="road_closed",
                severity="critical",
                title=f"路线封路提醒：{origin} → {destination}",
                message=(
                    f"您关注的路线 {origin} → {destination} "
                    f"出现道路封闭（{traffic_info.get('closure_reason', '原因未知')}），"
                    f"建议立即更换出行路线。"
                ),
                suggested_action="请使用导航 App 重新规划路线，或选择公共交通出行。",
                raw_data=traffic_info,
            ))

        elif congestion >= 5:
            results.append(self._make_result(
                type="severe_traffic_jam",
                severity="warning",
                title=f"严重拥堵：{origin} → {destination}",
                message=(
                    f"路线 {origin} → {destination} 当前严重拥堵，"
                    f"预计通行时间 {traffic_info.get('duration_min', '?')} 分钟"
                    f"（平时约 {traffic_info.get('normal_duration_min', '?')} 分钟）。"
                ),
                suggested_action="建议提前出发或绕行，考虑乘坐地铁等公共交通。",
                raw_data=traffic_info,
            ))

        elif congestion == 4:
            results.append(self._make_result(
                type="traffic_jam",
                severity="warning",
                title=f"中度拥堵：{origin} → {destination}",
                message=(
                    f"路线 {origin} → {destination} 当前中度拥堵，"
                    f"预计通行时间 {traffic_info.get('duration_min', '?')} 分钟。"
                ),
                suggested_action="请预留额外出行时间，关注实时路况变化。",
                raw_data=traffic_info,
            ))

        elif congestion == 3:
            results.append(self._make_result(
                type="light_traffic",
                severity="info",
                title=f"轻度拥堵：{origin} → {destination}",
                message=(
                    f"路线 {origin} → {destination} 当前轻度拥堵，"
                    f"预计通行时间 {traffic_info.get('duration_min', '?')} 分钟。"
                ),
                raw_data=traffic_info,
            ))

        else:
            results.append(self._make_result(
                type="traffic_smooth",
                severity="info",
                title=f"路况畅通：{origin} → {destination}",
                message=(
                    f"路线 {origin} → {destination} 当前路况畅通，"
                    f"预计通行时间 {traffic_info.get('duration_min', '?')} 分钟。"
                ),
                raw_data=traffic_info,
            ))

        return results

    # ------------------------------------------------------------------
    # 真实 API（腾讯位置服务）
    # ------------------------------------------------------------------
    def _fetch_real(self, origin: str, destination: str) -> dict:
        """调用腾讯位置服务获取驾车路线，并估算拥堵等级。

        腾讯驾车路线基础接口（/ws/direction/v1/driving）返回距离/时长，
        不直接给逐段实时拥堵指数，故拥堵等级由「实际时长 / 自由流时长」启发式估算：
          自由流 ≈ 40km/h；ratio<=1.15 畅通 → 5 级严重拥堵逐步递增。
        若地理编码或路线失败，回退 mock 保证不中断监控。
        """
        origin_geo = self._tm.geocode(origin)
        dest_geo = self._tm.geocode(destination)
        if not origin_geo or not dest_geo:
            logger.warning(f"腾讯地图地理编码失败: {origin} 或 {destination}")
            return self._fetch_mock(origin, destination)

        route = self._tm.driving_route(origin_geo, dest_geo)
        if not route:
            return self._fetch_mock(origin, destination)

        distance_km = route["distance_km"]
        duration_min = route["duration_min"]

        # 拥堵等级启发式
        free_flow_min = max(1.0, distance_km * 1.5)  # 约 40km/h
        ratio = duration_min / free_flow_min
        if ratio <= 1.15:
            congestion = 1
        elif ratio <= 1.4:
            congestion = 2
        elif ratio <= 1.8:
            congestion = 3
        elif ratio <= 2.4:
            congestion = 4
        else:
            congestion = 5

        return {
            "origin": origin,
            "destination": destination,
            "duration_min": duration_min,
            "distance_km": distance_km,
            "congestion_level": min(congestion, 5),
            "normal_duration_min": int(free_flow_min),
            "road_closed": False,
            "mock": False,
        }

    # ------------------------------------------------------------------
    # Mock 模式
    # ------------------------------------------------------------------
    def _fetch_mock(self, origin: str, destination: str) -> dict:
        """生成模拟路况数据"""
        # 距离基线（随机 5~60 km）
        distance_km = round(random.uniform(5, 60), 1)
        # 正常通行时间（按 40km/h 估算）
        normal_duration = int(distance_km / 40 * 60)

        # 拥堵等级分布：50% 畅通, 25% 轻度, 15% 中度, 7% 严重, 3% 封路
        roll = random.random()
        if roll < 0.50:
            congestion = random.choice([1, 2])
            road_closed = False
        elif roll < 0.75:
            congestion = 3
            road_closed = False
        elif roll < 0.90:
            congestion = 4
            road_closed = False
        elif roll < 0.97:
            congestion = 5
            road_closed = False
        else:
            congestion = 5
            road_closed = True

        # 拥堵系数
        factor_map = {1: 1.0, 2: 1.15, 3: 1.5, 4: 2.0, 5: 2.8}
        factor = factor_map.get(congestion, 1.0)
        duration_min = int(normal_duration * factor)

        closure_reason = ""
        if road_closed:
            closure_reason = random.choice([
                "道路施工",
                "交通事故封路",
                "交通管制",
                "积水严重",
            ])

        return {
            "origin": origin,
            "destination": destination,
            "duration_min": duration_min,
            "distance_km": distance_km,
            "congestion_level": congestion,
            "congestion_text": _CONGESTION_TEXT.get(congestion, "未知"),
            "normal_duration_min": normal_duration,
            "road_closed": road_closed,
            "closure_reason": closure_reason,
            "mock": True,
        }
