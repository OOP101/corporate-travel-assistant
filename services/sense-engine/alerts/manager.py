"""
提醒管理器 —— 感知结果的存储、检索与分发

负责将 SourceResult 转换为 AlertEvent 并持久化（内存存储），
同时记录 Prometheus 指标，供 API 层查询。
"""
import logging
import threading
from typing import List, Optional

from shared.metrics import alert_pushed_counter
from shared.models import AlertEvent
from sources.base import SourceResult

logger = logging.getLogger("sense-engine.alerts")


class AlertManager:
    """
    提醒管理器

    内存存储 alerts，按 trip_id 分组。
    线程安全：使用 threading.Lock 保护内部字典。
    """

    def __init__(self):
        self._alerts: dict[str, List[AlertEvent]] = {}
        self._lock = threading.Lock()

    def add(self, alert: AlertEvent) -> None:
        """添加一条提醒"""
        with self._lock:
            self._alerts.setdefault(alert.trip_id, []).append(alert)
        logger.info(
            f"提醒已添加: [{alert.severity}] {alert.title} "
            f"(trip={alert.trip_id}, type={alert.type})"
        )

    def get_by_trip(self, trip_id: str) -> List[dict]:
        """获取行程的所有提醒列表"""
        with self._lock:
            alerts = self._alerts.get(trip_id, [])
            return [a.to_dict() for a in alerts]

    def get_undelivered(self, trip_id: str) -> List[dict]:
        """获取行程的未送达提醒"""
        with self._lock:
            alerts = self._alerts.get(trip_id, [])
            return [a.to_dict() for a in alerts if not a.delivered]

    def mark_delivered(self, alert_id: str) -> bool:
        """标记某条提醒为已送达"""
        with self._lock:
            for trip_id, alerts in self._alerts.items():
                for alert in alerts:
                    if alert.alert_id == alert_id:
                        alert.delivered = True
                        logger.debug(f"提醒已标记送达: {alert_id}")
                        return True
        return False

    def clear(self, trip_id: str) -> int:
        """清除行程的所有提醒，返回清除数量"""
        with self._lock:
            removed = len(self._alerts.pop(trip_id, []))
        if removed:
            logger.info(f"已清除行程 {trip_id} 的 {removed} 条提醒")
        return removed

    def push(
        self,
        source_result: SourceResult,
        trip_id: str,
        user_id: str,
    ) -> AlertEvent:
        """
        将 SourceResult 转换为 AlertEvent 并存储

        Args:
            source_result: 数据源检查结果
            trip_id: 关联的行程 ID
            user_id: 用户 ID

        Returns:
            创建的 AlertEvent
        """
        alert = AlertEvent(
            trip_id=trip_id,
            user_id=user_id,
            type=source_result.type,
            severity=source_result.severity,
            title=source_result.title,
            message=source_result.message,
            suggested_action=source_result.suggested_action,
            source=source_result.source,
        )
        self.add(alert)

        # 记录 Prometheus 指标
        alert_pushed_counter.labels(
            type=source_result.type,
            severity=source_result.severity,
        ).inc()

        return alert

    def all_count(self) -> int:
        """返回提醒总数"""
        with self._lock:
            return sum(len(v) for v in self._alerts.values())
