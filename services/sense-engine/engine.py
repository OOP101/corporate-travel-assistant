"""
感知引擎核心 —— SenseEngine

职责：
  1. 管理数据源注册与行程订阅
  2. 定时遍历所有订阅，调用数据源 check() 采集最新状态
  3. 变更检测：与上次状态缓存对比，仅对"变更"或"异常"的结果推送提醒
  4. 过滤规则：静默不值得提醒的轻微变化（如航班延误 < 15 分钟）
  5. 通过 APScheduler 实现每 5 分钟一次的定时全量检查，支持优雅启停

持久化：订阅表与状态缓存落盘到 `data/sense/`，服务重启后订阅不丢——
此前为纯内存字典，重启即清空，导致 check_all 空转、实时监控形同虚设。
"""
import json
import logging
import os
import tempfile
import threading
from typing import Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from shared.models import AlertEvent
from alerts.manager import AlertManager
from sources import FlightSource, WeatherSource, TrafficSource, AttractionSource, TrainSource
from sources.base import BaseSource, SourceResult

logger = logging.getLogger("sense-engine.engine")


class SenseEngine:
    """实时感知引擎"""

    def __init__(self, alert_manager: AlertManager, data_dir: Optional[str] = None):
        self.alert_manager = alert_manager
        self._data_dir = data_dir
        # 订阅/状态缓存的读写锁（调度线程与请求线程并发访问）
        self._lock = threading.RLock()

        # 注册数据源
        self._sources: Dict[str, BaseSource] = {
            "flight": FlightSource(),
            "weather": WeatherSource(),
            "traffic": TrafficSource(),
            "attraction": AttractionSource(),
            "train": TrainSource(),
        }

        # 订阅表: trip_id → subscription_dict
        self._subscriptions: Dict[str, dict] = {}

        # 上次状态缓存: "trip_id:source:type" → last_value
        # 用于变更检测，避免重复推送相同状态
        self._state_cache: Dict[str, str] = {}

        # 定时调度器
        self._scheduler: Optional[BackgroundScheduler] = None

        # 回灌上次运行留下的订阅与状态缓存（服务重启不丢监控目标）
        if self._data_dir:
            os.makedirs(self._data_dir, exist_ok=True)
            self._load_state()

    # ------------------------------------------------------------------
    # 持久化（订阅表 + 状态缓存）
    # ------------------------------------------------------------------
    @property
    def _subscriptions_path(self) -> Optional[str]:
        return os.path.join(self._data_dir, "subscriptions.json") if self._data_dir else None

    @property
    def _state_cache_path(self) -> Optional[str]:
        return os.path.join(self._data_dir, "state_cache.json") if self._data_dir else None

    def _load_state(self) -> None:
        """启动时回灌订阅与状态缓存；数据缺失/损坏不阻断启动。"""
        for path, target, label in (
            (self._subscriptions_path, self._subscriptions, "订阅"),
            (self._state_cache_path, self._state_cache, "状态缓存"),
        ):
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    target.update(data)
                    logger.info(f"已恢复 {len(data)} 条{label}")
            except Exception as e:
                logger.error(f"加载{label}失败，从空状态开始: {e}")

    @staticmethod
    def _atomic_write(path: str, data: dict, data_dir: str) -> None:
        """原子写：先写临时文件再替换，避免写一半被读到。"""
        fd, tmp = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _persist_subscriptions(self) -> None:
        path = self._subscriptions_path
        if not path:
            return
        try:
            self._atomic_write(path, self._subscriptions, self._data_dir)
        except Exception as e:
            logger.error(f"订阅落盘失败: {e}")

    def _persist_state_cache(self) -> None:
        path = self._state_cache_path
        if not path:
            return
        try:
            self._atomic_write(path, self._state_cache, self._data_dir)
        except Exception as e:
            logger.error(f"状态缓存落盘失败: {e}")

    # ------------------------------------------------------------------
    # 订阅管理
    # ------------------------------------------------------------------
    def subscribe(self, trip_id: str, subscription: dict) -> None:
        """
        为行程订阅监控

        Args:
            trip_id: 行程 ID
            subscription: 订阅信息，字段包括:
                user_id, flight_number, destination, origin,
                check_weather, check_traffic, check_attractions, attractions
        """
        with self._lock:
            self._subscriptions[trip_id] = subscription
            self._persist_subscriptions()
        logger.info(
            f"已订阅行程 {trip_id}: "
            f"flight={subscription.get('flight_number', '')}, "
            f"train={subscription.get('train_code', '')}, "
            f"weather={subscription.get('check_weather', False)}, "
            f"traffic={subscription.get('check_traffic', False)}, "
            f"attractions={subscription.get('check_attractions', False)} "
            f"({len(subscription.get('attractions') or [])} 个景点)"
        )

    def unsubscribe(self, trip_id: str) -> bool:
        """取消行程的订阅"""
        with self._lock:
            if trip_id not in self._subscriptions:
                return False
            del self._subscriptions[trip_id]
            # 清理该行程的状态缓存
            prefix = f"{trip_id}:"
            keys_to_remove = [k for k in self._state_cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._state_cache[k]
            self._persist_subscriptions()
            self._persist_state_cache()
        logger.info(f"已取消订阅行程 {trip_id}")
        return True

    def get_subscriptions(self) -> dict:
        """返回所有订阅信息"""
        with self._lock:
            return dict(self._subscriptions)

    def get_subscription(self, trip_id: str) -> Optional[dict]:
        """获取单个行程的订阅信息"""
        with self._lock:
            return self._subscriptions.get(trip_id)

    # ------------------------------------------------------------------
    # 检查逻辑
    # ------------------------------------------------------------------
    def check_all(self) -> List[AlertEvent]:
        """遍历所有订阅执行检查，返回本次新产生的提醒列表"""
        all_alerts: List[AlertEvent] = []
        with self._lock:
            trip_ids = list(self._subscriptions.keys())

        if not trip_ids:
            logger.debug("当前无订阅，跳过检查")
            return all_alerts

        logger.info(f"开始全量检查，共 {len(trip_ids)} 个行程订阅")

        for trip_id in trip_ids:
            try:
                alerts = self.check_trip(trip_id)
                all_alerts.extend(alerts)
            except Exception as e:
                logger.error(f"检查行程 {trip_id} 失败: {e}", exc_info=True)

        logger.info(f"全量检查完成，产生 {len(all_alerts)} 条新提醒")
        return all_alerts

    def check_trip(self, trip_id: str) -> List[AlertEvent]:
        """
        检查单个行程的订阅

        根据订阅信息决定调用哪些数据源，
        对每个结果进行变更检测和过滤，仅推送新提醒。
        """
        with self._lock:
            subscription = self._subscriptions.get(trip_id)
        if not subscription:
            logger.warning(f"行程 {trip_id} 无订阅信息")
            return []

        user_id = subscription.get("user_id", "default")
        check_weather = subscription.get("check_weather", True)
        check_traffic = subscription.get("check_traffic", False)
        check_attractions = subscription.get("check_attractions", True)
        flight_number = subscription.get("flight_number", "").strip()
        train_code = subscription.get("train_code", "").strip()
        attractions = subscription.get("attractions") or []

        new_alerts: List[AlertEvent] = []

        # --- 航班检查 ---
        if flight_number:
            results = self._run_source("flight", trip_id, subscription)
            new_alerts.extend(self._process_results(results, trip_id, user_id))

        # --- 铁路检查（12306 车票：停运/无票/正常） ---
        if train_code:
            results = self._run_source("train", trip_id, subscription)
            new_alerts.extend(self._process_results(results, trip_id, user_id))

        # --- 天气检查 ---
        if check_weather and subscription.get("destination"):
            results = self._run_source("weather", trip_id, subscription)
            new_alerts.extend(self._process_results(results, trip_id, user_id))

        # --- 路况检查 ---
        if check_traffic and subscription.get("origin") and subscription.get("destination"):
            results = self._run_source("traffic", trip_id, subscription)
            new_alerts.extend(self._process_results(results, trip_id, user_id))

        # --- 景点检查 ---
        if check_attractions and attractions:
            results = self._run_source("attraction", trip_id, subscription)
            new_alerts.extend(self._process_results(results, trip_id, user_id))

        return new_alerts

    def _run_source(self, source_name: str, trip_id: str, subscription: dict) -> List[SourceResult]:
        """执行单个数据源的检查"""
        source = self._sources.get(source_name)
        if not source:
            return []
        try:
            return source.check(subscription)
        except Exception as e:
            logger.error(f"数据源 {source_name} 检查异常 (trip={trip_id}): {e}", exc_info=True)
            return []

    def _process_results(
        self,
        results: List[SourceResult],
        trip_id: str,
        user_id: str,
    ) -> List[AlertEvent]:
        """对检查结果进行过滤 + 变更检测，推送新提醒"""
        alerts: List[AlertEvent] = []

        for result in results:
            # 过滤：不符合告警条件的静默
            if not self._should_alert(result):
                continue

            # 变更检测：与上次状态对比
            state_key = f"{trip_id}:{result.source}:{result.type}"
            current_value = f"{result.severity}|{result.title}"

            if not self._has_changed(state_key, current_value):
                # 状态未变化，不重复推送
                continue

            # 推送提醒
            alert = self.alert_manager.push(result, trip_id, user_id)
            alerts.append(alert)

        return alerts

    # ------------------------------------------------------------------
    # 变更检测 & 过滤
    # ------------------------------------------------------------------
    def _has_changed(self, key: str, value: str) -> bool:
        """
        变更检测：与缓存中的上次状态对比

        Returns:
            True 表示状态发生变化（或首次出现），应推送提醒
        """
        with self._lock:
            last = self._state_cache.get(key)
            if last is None:
                # 首次出现，视为变更
                self._state_cache[key] = value
                self._persist_state_cache()
                return True
            if last != value:
                self._state_cache[key] = value
                self._persist_state_cache()
                return True
            return False

    def _should_alert(self, source_result: SourceResult) -> bool:
        """
        过滤规则：判断该结果是否值得推送提醒

        规则：
          - critical / warning 级别始终推送
          - info 级别仅在状态变化时推送（正常状态不重复推送）
          - 航班延误 < 15 分钟静默
          - 轻度拥堵（level 3）仅在 info 时推送一次
        """
        # 航班延误 < 15 分钟静默
        if source_result.type == "flight_delay":
            delay = source_result.raw_data.get("delay_minutes", 0)
            if delay < 15:
                return False

        # warning / critical 始终告警
        if source_result.severity in ("warning", "critical"):
            return True

        # info 级别：正常状态（flight_normal / weather_normal / traffic_smooth）
        # 也允许推送，但依赖变更检测去重
        return True

    # ------------------------------------------------------------------
    # 定时调度
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动定时检查任务（每 5 分钟一次）"""
        if self._scheduler is not None:
            logger.warning("调度器已启动，无需重复启动")
            return

        self._scheduler = BackgroundScheduler(
            timezone="Asia/Shanghai",
            job_defaults={"misfire_grace_time": 120, "coalesce": True},
        )
        self._scheduler.add_job(
            self.check_all,
            IntervalTrigger(minutes=5),
            id="sense_check_all",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.start()
        logger.info("感知引擎定时任务已启动（每 5 分钟检查一次）")

    def stop(self) -> None:
        """停止调度器，优雅关闭"""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("感知引擎定时任务已停止")

    @property
    def active_sources(self) -> List[str]:
        """当前注册的数据源名称列表"""
        return list(self._sources.keys())

    @property
    def subscription_count(self) -> int:
        """当前订阅数量"""
        with self._lock:
            return len(self._subscriptions)
