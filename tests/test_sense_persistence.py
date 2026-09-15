"""感知监控持久化测试（修复：重启后订阅与提醒丢失）

背景：`SenseEngine._subscriptions` 与 `AlertManager._alerts` 原为纯内存字典，
服务一重启订阅表清空 → `check_all()` 直接 return → 实时监控形同虚设。
本测试锁定"重启不丢"这一行为，防止回归。

跨服务说明：sense-engine 的 `api.main` 会拉起 APScheduler，这里直接实例化
`SenseEngine` / `AlertManager`（它们只依赖 data_dir），不 import api.main。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENSE_DIR = os.path.join(ROOT, "services", "sense-engine")
if SENSE_DIR in sys.path:
    sys.path.remove(SENSE_DIR)
sys.path.insert(0, SENSE_DIR)

for _mod in [m for m in list(sys.modules) if m == "api" or m.startswith("api.")]:
    del sys.modules[_mod]

from engine import SenseEngine  # noqa: E402
from alerts.manager import AlertManager  # noqa: E402
from sources.base import SourceResult  # noqa: E402


SUB = {
    "user_id": "alice",
    "destination": "深圳",
    "origin": "广州",
    "check_weather": True,
    "check_traffic": False,
    "check_attractions": False,
}


def _boot(tmp_path, name="boot"):
    """用同一目录新建一套 AlertManager + SenseEngine —— 等价于进程重启。"""
    am = AlertManager(data_dir=str(tmp_path / "alerts"))
    eng = SenseEngine(alert_manager=am, data_dir=str(tmp_path / "monitor"))
    return eng, am


def _stable_result(title="固定预警", severity="warning", type_="weather_warning"):
    return SourceResult(
        source="weather", type=type_, severity=severity, title=title, message="测试消息"
    )


# ---------------------------------------------------------------------------
# 一、订阅持久化
# ---------------------------------------------------------------------------
class TestSubscriptionPersistence:
    def test_subscription_survives_restart(self, tmp_path):
        eng, _ = _boot(tmp_path, "first")
        eng.subscribe("trip_1", SUB)
        assert eng.subscription_count == 1

        eng2, _ = _boot(tmp_path, "second")
        assert eng2.subscription_count == 1, "重启后订阅丢失"
        assert eng2.get_subscription("trip_1")["destination"] == "深圳"

    def test_multiple_subscriptions_survive_restart(self, tmp_path):
        eng, _ = _boot(tmp_path, "first")
        for i in range(3):
            eng.subscribe(f"trip_{i}", {**SUB, "user_id": f"u{i}"})

        eng2, _ = _boot(tmp_path, "second")
        assert eng2.subscription_count == 3
        assert eng2.get_subscription("trip_2")["user_id"] == "u2"

    def test_unsubscribe_survives_restart(self, tmp_path):
        eng, _ = _boot(tmp_path, "first")
        eng.subscribe("trip_1", SUB)
        eng.subscribe("trip_2", SUB)
        assert eng.unsubscribe("trip_1") is True

        eng2, _ = _boot(tmp_path, "second")
        assert eng2.subscription_count == 1, "取消的订阅在重启后复活了"
        assert eng2.get_subscription("trip_1") is None

    def test_unsubscribe_unknown_returns_false(self, tmp_path):
        eng, _ = _boot(tmp_path)
        assert eng.unsubscribe("never_existed") is False

    def test_check_all_runs_after_restart(self, tmp_path, monkeypatch):
        """核心回归：重启后 check_all 不能因订阅为空而空转。"""
        eng, _ = _boot(tmp_path, "first")
        eng.subscribe("trip_1", SUB)

        eng2, _ = _boot(tmp_path, "second")
        # 用稳定数据源替换真实（mock）源，隔离随机性
        monkeypatch.setattr(
            eng2, "_run_source", lambda *a, **k: [_stable_result()]
        )
        alerts = eng2.check_all()
        assert len(alerts) == 1, "重启后 check_all 没有产出提醒"

    def test_no_subscription_means_empty_check(self, tmp_path):
        eng, _ = _boot(tmp_path)
        assert eng.check_all() == []


# ---------------------------------------------------------------------------
# 二、提醒持久化
# ---------------------------------------------------------------------------
class TestAlertPersistence:
    def test_alerts_survive_restart(self, tmp_path):
        _, am = _boot(tmp_path, "first")
        am.push(_stable_result(), "trip_1", "alice")
        assert am.all_count() == 1

        _, am2 = _boot(tmp_path, "second")
        assert am2.all_count() == 1, "重启后提醒丢失"
        assert len(am2.get_by_trip("trip_1")) == 1

    def test_alert_fields_roundtrip(self, tmp_path):
        _, am = _boot(tmp_path, "first")
        am.push(_stable_result(title="大风预警", severity="critical"), "trip_1", "alice")

        _, am2 = _boot(tmp_path, "second")
        got = am2.get_by_trip("trip_1")[0]
        assert got["title"] == "大风预警"
        assert got["severity"] == "critical"
        assert got["trip_id"] == "trip_1"
        assert got["user_id"] == "alice"
        assert got["alert_id"]

    def test_delivered_state_survives_restart(self, tmp_path):
        _, am = _boot(tmp_path, "first")
        alert = am.push(_stable_result(), "trip_1", "alice")
        assert am.mark_delivered(alert.alert_id) is True

        _, am2 = _boot(tmp_path, "second")
        assert am2.get_undelivered("trip_1") == [], "已送达状态在重启后丢失"

    def test_clear_survives_restart(self, tmp_path):
        _, am = _boot(tmp_path, "first")
        am.push(_stable_result(), "trip_1", "alice")
        assert am.clear("trip_1") == 1

        _, am2 = _boot(tmp_path, "second")
        assert am2.all_count() == 0, "已清除的提醒在重启后复活了"

    def test_mark_delivered_unknown_id_returns_false(self, tmp_path):
        _, am = _boot(tmp_path)
        assert am.mark_delivered("alert_nope") is False

    def test_alerts_grouped_by_trip(self, tmp_path):
        _, am = _boot(tmp_path, "first")
        am.push(_stable_result(), "trip_1", "alice")
        am.push(_stable_result(title="另一条"), "trip_2", "bob")

        _, am2 = _boot(tmp_path, "second")
        assert len(am2.get_by_trip("trip_1")) == 1
        assert len(am2.get_by_trip("trip_2")) == 1

    def test_per_trip_cap_prevents_unbounded_growth(self, tmp_path):
        """长期运行不能无限增长：超出上限时裁掉最旧的。"""
        import alerts.manager as mgr

        _, am = _boot(tmp_path)
        for i in range(mgr.MAX_ALERTS_PER_TRIP + 20):
            am.push(_stable_result(title=f"第{i}条"), "trip_1", "alice")

        _, am2 = _boot(tmp_path, "second")
        assert am2.all_count() == mgr.MAX_ALERTS_PER_TRIP
        # 保留的是较新的那批
        titles = [a["title"] for a in am2.get_by_trip("trip_1")]
        assert f"第{mgr.MAX_ALERTS_PER_TRIP + 19}条" in titles


# ---------------------------------------------------------------------------
# 三、状态缓存持久化 + 变更检测去重
# ---------------------------------------------------------------------------
class TestStateCachePersistence:
    def test_state_cache_survives_restart(self, tmp_path):
        eng, _ = _boot(tmp_path, "first")
        eng._has_changed("trip_1:weather:weather_warning", "warning|大风")
        assert eng._state_cache

        eng2, _ = _boot(tmp_path, "second")
        assert eng2._state_cache == eng._state_cache

    def test_no_duplicate_push_across_restart(self, tmp_path):
        """重启后同一状态不得重复推送（状态缓存必须一起恢复）。"""
        eng, _ = _boot(tmp_path, "first")
        first = eng._process_results([_stable_result()], "trip_1", "alice")
        assert len(first) == 1

        eng2, am2 = _boot(tmp_path, "second")
        again = eng2._process_results([_stable_result()], "trip_1", "alice")
        assert again == [], "重启后同一状态被重复推送"
        assert am2.all_count() == 1

    def test_changed_value_does_push(self, tmp_path):
        eng, _ = _boot(tmp_path, "first")
        eng._process_results([_stable_result("状态A")], "trip_1", "alice")

        eng2, _ = _boot(tmp_path, "second")
        got = eng2._process_results([_stable_result("状态B")], "trip_1", "alice")
        assert len(got) == 1, "状态真的变了却没有推送"

    def test_dedup_within_same_process(self, tmp_path):
        eng, _ = _boot(tmp_path)
        assert len(eng._process_results([_stable_result()], "t", "u")) == 1
        assert eng._process_results([_stable_result()], "t", "u") == []


# ---------------------------------------------------------------------------
# 四、健壮性：无 data_dir / 数据损坏
# ---------------------------------------------------------------------------
class TestRobustness:
    def test_works_without_data_dir(self):
        """不传 data_dir 时应退化为纯内存，不报错。"""
        am = AlertManager()
        eng = SenseEngine(alert_manager=am)
        eng.subscribe("trip_1", SUB)
        assert eng.subscription_count == 1
        assert am.all_count() == 0
        eng._process_results([_stable_result()], "trip_1", "alice")
        assert am.all_count() == 1

    def test_corrupt_alert_file_does_not_crash(self, tmp_path):
        alert_dir = tmp_path / "alerts"
        alert_dir.mkdir(parents=True)
        (alert_dir / "alerts.json").write_text("{ 这不是合法 JSON", encoding="utf-8")
        # 不应抛异常，从空状态开始
        am = AlertManager(data_dir=str(alert_dir))
        assert am.all_count() == 0

    def test_corrupt_subscription_file_does_not_crash(self, tmp_path):
        mon_dir = tmp_path / "monitor"
        mon_dir.mkdir(parents=True)
        (mon_dir / "subscriptions.json").write_text("]]broken[[", encoding="utf-8")
        am = AlertManager(data_dir=str(tmp_path / "alerts"))
        eng = SenseEngine(alert_manager=am, data_dir=str(mon_dir))
        assert eng.subscription_count == 0
