"""
提醒管理器 —— 感知结果的存储、检索与分发

负责将 SourceResult 转换为 AlertEvent 并持久化，同时记录 Prometheus 指标，
供 API 层查询。

持久化：提醒落盘到 `data/sense/alerts/`（每行一条 alert，按 alert_id 为键）。
此前为纯内存字典，服务一重启提醒全部丢失，前端"提醒中心"永远空白。
"""
import logging
import os
import threading
import time
from typing import List, Optional

from shared.metrics import alert_pushed_counter
from shared.models import AlertEvent
from sources.base import SourceResult

logger = logging.getLogger("sense-engine.alerts")

# 每个行程最多保留的提醒条数（防止长期运行无限增长）
MAX_ALERTS_PER_TRIP = 200


class AlertManager:
    """
    提醒管理器

    持久化存储 alerts，按 alert_id 索引，内存中维护 trip_id → [alert] 的视图。
    线程安全：使用 threading.RLock 保护内部字典与落盘。
    """

    def __init__(self, data_dir: Optional[str] = None):
        self._alerts: dict[str, List[AlertEvent]] = {}
        # alert_id → trip_id，便于 mark_delivered 直接定位
        self._index: dict[str, str] = {}
        self._lock = threading.RLock()
        self._data_dir = data_dir
        if self._data_dir:
            os.makedirs(self._data_dir, exist_ok=True)
            self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    @property
    def _store_path(self) -> Optional[str]:
        return os.path.join(self._data_dir, "alerts.json") if self._data_dir else None

    @staticmethod
    def _to_dict(alert: AlertEvent) -> dict:
        return alert.to_dict()

    @staticmethod
    def _from_dict(raw: dict) -> AlertEvent:
        return AlertEvent(
            alert_id=raw.get("alert_id") or f"alert_{int(time.time() * 1000)}",
            trip_id=raw.get("trip_id", ""),
            user_id=raw.get("user_id", ""),
            type=raw.get("type", ""),
            severity=raw.get("severity", "info"),
            title=raw.get("title", ""),
            message=raw.get("message", ""),
            suggested_action=raw.get("suggested_action", ""),
            source=raw.get("source", ""),
            created_at=raw.get("created_at") or time.time(),
            delivered=bool(raw.get("delivered", False)),
        )

    def _load(self) -> None:
        """启动时回灌磁盘上的提醒（无数据 / 损坏时静默跳过，不影响服务可用）。"""
        path = self._store_path
        if not path or not os.path.exists(path):
            return
        try:
            import json

            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            alerts = payload.get("alerts", []) if isinstance(payload, dict) else payload
            for raw in alerts:
                alert = self._from_dict(raw)
                self._alerts.setdefault(alert.trip_id, []).append(alert)
                self._index[alert.alert_id] = alert.trip_id
            logger.info(
                f"已加载 {len(self._index)} 条历史提醒，覆盖 {len(self._alerts)} 个行程"
            )
        except Exception as e:
            # 落盘数据损坏不应阻断服务启动：留日志，从空状态开始
            logger.error(f"加载提醒数据失败，从空状态开始: {e}")

    def _persist(self) -> None:
        """将全部提醒原子写入磁盘（先写临时文件再替换）。"""
        path = self._store_path
        if not path:
            return
        try:
            import json
            import tempfile

            flat = [self._to_dict(a) for alerts in self._alerts.values() for a in alerts]
            fd, tmp = tempfile.mkstemp(dir=self._data_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"alerts": flat}, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except Exception:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        except Exception as e:
            logger.error(f"提醒落盘失败: {e}")

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------
    def add(self, alert: AlertEvent) -> None:
        """添加一条提醒"""
        with self._lock:
            bucket = self._alerts.setdefault(alert.trip_id, [])
            bucket.append(alert)
            self._index[alert.alert_id] = alert.trip_id
            # 超量时裁掉最旧的，避免长期运行无限增长
            if len(bucket) > MAX_ALERTS_PER_TRIP:
                for stale in bucket[:-MAX_ALERTS_PER_TRIP]:
                    self._index.pop(stale.alert_id, None)
                del bucket[:-MAX_ALERTS_PER_TRIP]
            self._persist()
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
            trip_id = self._index.get(alert_id)
            if not trip_id:
                return False
            for alert in self._alerts.get(trip_id, []):
                if alert.alert_id == alert_id:
                    alert.delivered = True
                    self._persist()
                    logger.debug(f"提醒已标记送达: {alert_id}")
                    return True
        return False

    def clear(self, trip_id: str) -> int:
        """清除行程的所有提醒，返回清除数量"""
        with self._lock:
            removed_alerts = self._alerts.pop(trip_id, [])
            for a in removed_alerts:
                self._index.pop(a.alert_id, None)
            removed = len(removed_alerts)
            if removed:
                self._persist()
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
