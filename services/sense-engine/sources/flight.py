"""
航班数据源 —— 航班状态实时感知

模式：
  - 真实模式：通过航班 API 查询最新状态（需配置 flight_api_key）
  - Mock 模式：生成模拟航班状态，保证无 API key 也能演示

感知规则：
  - 延误 > 15 分钟 → warning
  - 取消 → critical
  - 登机口变更 → info
"""
import logging
import random
from typing import List

from shared.config import settings
from shared.http_client import ServiceClient
from shared.metrics import monitor_check_counter

from .base import BaseSource, SourceResult

logger = logging.getLogger("sense-engine.sources.flight")

# 航空公司 IATA 代码（Mock 用）
_AIRLINES = ["CA", "MU", "CZ", "HU", "ZH", "MF", "FM", "3U"]
# 常见城市三字码（Mock 用）
_CITY_CODES = {
    "北京": "PEK", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
    "成都": "CTU", "杭州": "HGH", "西安": "XIY", "重庆": "CKG",
    "昆明": "KMG", "厦门": "XMN", "南京": "NKG", "武汉": "WUH",
}
_CITY_NAMES = {v: k for k, v in _CITY_CODES.items()}


class FlightSource(BaseSource):
    """航班数据源"""

    name = "flight"

    def __init__(self):
        self._client = ServiceClient(timeout=15)
        self._api_key = settings.flight_api_key

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def check(self, subscription: dict) -> List[SourceResult]:
        """
        检查航班状态

        subscription 字段:
            flight_number: 航班号（如 "CA1234"），可选
            origin: 出发城市，可选
            destination: 目的城市，可选
        """
        flight_number = subscription.get("flight_number", "").strip()
        results: List[SourceResult] = []

        try:
            if self._api_key:
                flight_info = self._fetch_real(flight_number)
            else:
                flight_info = self._fetch_mock(flight_number, subscription)

            monitor_check_counter.labels(source="flight", status="ok").inc()

        except Exception as e:
            logger.error(f"航班数据源检查失败 ({flight_number}): {e}")
            monitor_check_counter.labels(source="flight", status="error").inc()
            return results

        # --- 感知规则 ---
        status = flight_info.get("status", "scheduled")

        if status == "cancelled":
            results.append(self._make_result(
                type="flight_cancelled",
                severity="critical",
                title=f"航班 {flight_info['flight_number']} 已取消",
                message=(
                    f"您关注的航班 {flight_info['flight_number']} "
                    f"（{flight_info['origin']} → {flight_info['destination']}）已取消，"
                    f"请尽快联系航空公司改签或退票。"
                ),
                suggested_action="请立即联系航空公司或通过 App 办理改签/退票。",
                raw_data=flight_info,
            ))

        elif status == "delayed":
            delay_min = flight_info.get("delay_minutes", 0)
            if delay_min > 15:
                results.append(self._make_result(
                    type="flight_delay",
                    severity="warning",
                    title=f"航班 {flight_info['flight_number']} 延误 {delay_min} 分钟",
                    message=(
                        f"航班 {flight_info['flight_number']} "
                        f"（{flight_info['origin']} → {flight_info['destination']}）"
                        f"预计延误 {delay_min} 分钟，原定起飞 {flight_info.get('scheduled_departure', '未知')}。"
                    ),
                    suggested_action="请关注航司通知，合理安排到达机场时间。",
                    raw_data=flight_info,
                ))

        # 登机口变更
        gate = flight_info.get("gate", "")
        prev_gate = flight_info.get("previous_gate", "")
        if gate and prev_gate and gate != prev_gate:
            results.append(self._make_result(
                type="gate_change",
                severity="info",
                title=f"航班 {flight_info['flight_number']} 登机口变更",
                message=(
                    f"航班 {flight_info['flight_number']} 登机口由 {prev_gate} 变更为 {gate}。"
                ),
                suggested_action="请前往新登机口候机。",
                raw_data=flight_info,
            ))

        if not results:
            # 一切正常，记录一条 info
            results.append(self._make_result(
                type="flight_normal",
                severity="info",
                title=f"航班 {flight_info['flight_number']} 状态正常",
                message=(
                    f"航班 {flight_info['flight_number']} "
                    f"（{flight_info['origin']} → {flight_info['destination']}）当前状态正常，"
                    f"预计 {flight_info.get('scheduled_departure', '准点')} 起飞。"
                ),
                raw_data=flight_info,
            ))

        return results

    # ------------------------------------------------------------------
    # 按需直查（问答路径调用，不等监控订阅）
    # ------------------------------------------------------------------
    def query(self, flight_number: str, origin: str = "", destination: str = "") -> dict:
        """
        按需查询航班状态（直查工具）。

        Args:
            flight_number: 航班号（如 "CA1234"）
            origin / destination: 出发/到达城市（Mock 用，可选）
        Returns:
            航班信息 dict（含 source / mock / degraded 标记）
        """
        flight_number = (flight_number or "").strip()
        sub = {"origin": origin or "", "destination": destination or ""}
        try:
            info = self._fetch_real(flight_number) if self._api_key else self._fetch_mock(flight_number, sub)
            info["source"] = "flight"
            return info
        except Exception as e:
            logger.error(f"航班直查失败 ({flight_number})，降级 Mock: {e}")
            info = self._fetch_mock(flight_number, sub)
            info["source"] = "flight"
            info["degraded"] = True
            return info

    # ------------------------------------------------------------------
    # 真实 API
    # ------------------------------------------------------------------
    def _fetch_real(self, flight_number: str) -> dict:
        """通过航班 API 获取真实数据"""
        # 航班 API 接口示例（需根据实际服务商调整）
        url = "https://api.aviationstack.com/v1/flights"
        params = {
            "access_key": self._api_key,
            "flight_iata": flight_number,
        }
        data = self._client.get(url, params=params)
        flights = data.get("data", [])
        if not flights:
            logger.warning(f"未查询到航班 {flight_number} 的信息")
            return self._fetch_mock(flight_number, {})

        f = flights[0]
        return {
            "flight_number": f.get("flight", {}).get("iata", flight_number),
            "airline": f.get("airline", {}).get("name", ""),
            "origin": f.get("departure", {}).get("airport", ""),
            "destination": f.get("arrival", {}).get("airport", ""),
            "scheduled_departure": f.get("departure", {}).get("scheduled", ""),
            "actual_departure": f.get("departure", {}).get("actual", ""),
            "delay_minutes": _parse_delay(
                f.get("departure", {}).get("scheduled", ""),
                f.get("departure", {}).get("actual", ""),
            ),
            "status": _normalize_status(f.get("flight_status", "scheduled")),
            "gate": f.get("departure", {}).get("gate", ""),
        }

    # ------------------------------------------------------------------
    # Mock 模式
    # ------------------------------------------------------------------
    def _fetch_mock(self, flight_number: str, subscription: dict) -> dict:
        """生成模拟航班状态数据"""
        # 解析航班号
        if flight_number:
            airline_code = flight_number[:2] if flight_number[:2].isalpha() else random.choice(_AIRLINES)
            num = flight_number[2:] if len(flight_number) > 2 else str(random.randint(1000, 9999))
        else:
            airline_code = random.choice(_AIRLINES)
            num = str(random.randint(1000, 9999))
            flight_number = f"{airline_code}{num}"

        # 出发 / 到达城市
        origin = subscription.get("origin", "").strip()
        destination = subscription.get("destination", "").strip()
        if not origin:
            origin = random.choice(list(_CITY_NAMES.values()))
        if not destination:
            destination = random.choice(list(_CITY_NAMES.values()))
            if destination == origin:
                destination = random.choice([c for c in _CITY_NAMES.values() if c != origin])

        # 模拟状态分布：70% 准点, 20% 延误, 5% 取消, 5% 登机口变更
        roll = random.random()
        hour = random.randint(6, 22)
        minute = random.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
        scheduled_dep = f"{hour:02d}:{minute:02d}"

        if roll < 0.70:
            status = "scheduled"
            delay_min = 0
        elif roll < 0.90:
            status = "delayed"
            delay_min = random.choice([25, 30, 45, 60, 90, 120])
        elif roll < 0.95:
            status = "cancelled"
            delay_min = 0
        else:
            status = "scheduled"
            delay_min = 0

        # 登机口
        gate = f"{random.choice('ABCDEF')}{random.randint(1, 30)}"
        prev_gate = gate
        if roll >= 0.95:
            prev_gate = f"{random.choice('ABCDEF')}{random.randint(1, 30)}"
            while prev_gate == gate:
                prev_gate = f"{random.choice('ABCDEF')}{random.randint(1, 30)}"

        return {
            "flight_number": flight_number,
            "airline": _airline_name(airline_code),
            "origin": origin,
            "destination": destination,
            "scheduled_departure": scheduled_dep,
            "actual_departure": f"{hour:02d}:{(minute + delay_min) % 60:02d}" if delay_min else scheduled_dep,
            "delay_minutes": delay_min,
            "status": status,
            "gate": gate,
            "previous_gate": prev_gate,
            "mock": True,
        }


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------
def _normalize_status(raw: str) -> str:
    """将 API 返回的状态归一化为内部状态"""
    raw = (raw or "").lower()
    if "cancel" in raw:
        return "cancelled"
    if "delay" in raw:
        return "delayed"
    if "scheduled" in raw or "active" in raw or "landed" in raw:
        return "scheduled"
    return "scheduled"


def _parse_delay(scheduled: str, actual: str) -> int:
    """从计划/实际时间计算延误分钟数"""
    if not scheduled or not actual:
        return 0
    try:
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S%z" if "T" in scheduled else "%Y-%m-%d %H:%M"
        s = datetime.strptime(scheduled[:19], fmt[: len(scheduled[:19]) + 3] if "+" in scheduled else fmt)
        a = datetime.strptime(actual[:19], fmt[: len(actual[:19]) + 3] if "+" in actual else fmt)
        return max(0, int((a - s).total_seconds() // 60))
    except Exception:
        return 0


def _airline_name(code: str) -> str:
    """航空公司代码 → 名称"""
    names = {
        "CA": "中国国际航空", "MU": "中国东方航空", "CZ": "中国南方航空",
        "HU": "海南航空", "ZH": "深圳航空", "MF": "厦门航空",
        "FM": "上海航空", "3U": "四川航空",
    }
    return names.get(code, code)
