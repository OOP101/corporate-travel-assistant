"""
感知 · Sense Engine 单元测试
"""
import sys
import os
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources.base import BaseSource, SourceResult
from sources.flight import FlightSource
from sources.weather import WeatherSource
from sources.traffic import TrafficSource
from alerts.manager import AlertManager
from engine import SenseEngine
from shared.models import AlertEvent


class TestSources:
    """数据源测试"""

    def test_flight_source_check(self):
        """航班数据源应返回 SourceResult 列表"""
        source = FlightSource()
        sub = {"flight_number": "CA1234", "date": "2026-08-20"}
        results = source.check(sub)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, SourceResult)

    def test_weather_source_check(self):
        """天气数据源应返回 SourceResult 列表"""
        source = WeatherSource()
        sub = {"destination_city": "成都", "date": "2026-08-20"}
        results = source.check(sub)
        assert isinstance(results, list)

    def test_traffic_source_check(self):
        """路况数据源应返回 SourceResult 列表"""
        source = TrafficSource()
        sub = {"origin": "北京站", "destination": "故宫"}
        results = source.check(sub)
        assert isinstance(results, list)


class TestAlertManager:
    """提醒管理器测试"""

    def setup_method(self):
        self.manager = AlertManager()

    def test_add_and_get(self):
        alert = AlertEvent(
            trip_id="trip_test",
            user_id="user_test",
            type="flight_delay",
            severity="warning",
            title="航班延误",
            message="CA1234 延误30分钟",
        )
        self.manager.add(alert)
        alerts = self.manager.get_by_trip("trip_test")
        assert len(alerts) >= 1

    def test_mark_delivered(self):
        alert = AlertEvent(
            trip_id="trip_test2",
            user_id="user_test",
            type="weather_warning",
            severity="info",
            title="天气预报",
            message="明天有雨",
        )
        self.manager.add(alert)
        undelivered = self.manager.get_undelivered("trip_test2")
        assert len(undelivered) >= 1
        self.manager.mark_delivered(undelivered[0]["alert_id"])
        after = self.manager.get_undelivered("trip_test2")
        assert len(after) < len(undelivered)


class TestSenseEngine:
    """感知引擎测试"""

    def test_subscribe_and_check(self):
        alert_manager = AlertManager()
        engine = SenseEngine(alert_manager)

        sub = {
            "trip_id": "trip_engine_test",
            "user_id": "user_test",
            "flight_number": "MU5678",
            "destination_city": "上海",
            "origin": "酒店",
            "destination": "机场",
        }
        engine.subscribe("trip_engine_test", sub)
        engine.check_all()

        # 检查应有订阅
        assert "trip_engine_test" in engine._subscriptions

    def test_unsubscribe(self):
        alert_manager = AlertManager()
        engine = SenseEngine(alert_manager)
        engine.subscribe("trip_unsub", {"trip_id": "trip_unsub"})
        engine.unsubscribe("trip_unsub")
        assert "trip_unsub" not in engine._subscriptions


class TestTrainSource:
    """铁路 12306 数据源测试"""

    def _source(self):
        from sources.train import TrainSource
        return TrainSource()

    def test_no_train_code_returns_empty(self):
        assert self._source().check({"destination": "北京"}) == []

    def test_real_failure_falls_back_to_mock(self, monkeypatch):
        src = self._source()
        monkeypatch.setattr(src, "_fetch_real", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("网络失败")))
        results = src.check({
            "train_code": "G102", "train_from": "广州南", "train_to": "北京西",
            "train_date": "2026-09-15",
        })
        assert len(results) == 1
        r = results[0]
        assert r.source == "train"
        assert r.type in ("train_normal", "train_soldout", "train_cancel")
        assert r.severity in ("info", "warning", "critical")
        assert "模拟数据" in r.message  # Mock 路径有标注

    def test_status_mapping(self, monkeypatch):
        src = self._source()
        cases = [
            ({"status": "cancelled", "detail": "停运"}, "train_cancel", "critical"),
            ({"status": "soldout", "detail": "无票"}, "train_soldout", "warning"),
            ({"status": "normal", "detail": "有余票"}, "train_normal", "info"),
        ]
        for status, want_type, want_sev in cases:
            monkeypatch.setattr(src, "_fetch_real", lambda *a, s=status, **k: s)
            r = src.check({"train_code": "G8", "train_from": "广州南", "train_to": "北京西"})[0]
            assert r.type == want_type and r.severity == want_sev

    def test_engine_integrates_train(self, monkeypatch):
        alert_manager = AlertManager()
        engine = SenseEngine(alert_manager)
        monkeypatch.setattr(engine._sources["train"], "_fetch_real",
                            lambda *a, **k: {"status": "cancelled", "detail": "停运"})
        engine.subscribe("trip_train", {
            "trip_id": "trip_train", "user_id": "u1",
            "train_code": "G102", "train_from": "广州南", "train_to": "北京西",
            "train_date": "2026-09-15",
        })
        alerts = engine.check_trip("trip_train")
        assert len(alerts) == 1
        assert "停运" in alerts[0].title
        # 状态未变不重复推送
        assert engine.check_trip("trip_train") == []
