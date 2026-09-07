"""RerouteEngine 重排算法测试（纯函数路径，不依赖 LLM）"""
from generators.reroute import RerouteEngine, _to_minutes, _to_time_str, _activity_duration


def make_engine():
    return RerouteEngine(llm_manager=None)


def make_trip():
    """一日行程：景点 9:00-11:00 → 午餐 11:30-13:00 → 参观 13:30-15:30"""
    return {
        "trip_id": "trip_t",
        "days": [
            {
                "date": "2026-09-01",
                "theme": "测试日",
                "activities": [
                    {"title": "景点A", "time_start": "09:00", "time_end": "11:00", "type": "attraction"},
                    {"title": "午餐", "time_start": "11:30", "time_end": "13:00", "type": "dining"},
                    {"title": "博物馆", "time_start": "13:30", "time_end": "15:30", "type": "attraction"},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# 时间工具
# ---------------------------------------------------------------------------
def test_time_conversions_roundtrip():
    assert _to_minutes("09:30") == 570
    assert _to_time_str(570) == "09:30"
    assert _to_minutes("invalid") == 0


def test_activity_duration():
    assert _activity_duration({"time_start": "09:00", "time_end": "11:00"}) == 120


# ---------------------------------------------------------------------------
# 变更类型识别与活动查找
# ---------------------------------------------------------------------------
def test_detect_change_type():
    detect = RerouteEngine._detect_change_type
    assert detect("景点临时闭园", {}) == "closed"
    assert detect("航班延误 2 小时", {}) == "delayed"
    assert detect("会议提前结束", {}) == "shortened"
    assert detect("客户要求加时", {}) == "extended"
    assert detect("不去这里了", {}) == "removed"
    assert detect("随便改一下", {}) == "changed"


def test_find_activity_exact_and_fuzzy():
    trip = make_trip()
    acts = trip["days"][0]["activities"]
    assert RerouteEngine._find_activity(acts, "午餐") == 1
    assert RerouteEngine._find_activity(acts, "博物") == 2  # 模糊匹配
    assert RerouteEngine._find_activity(acts, "不存在") is None


# ---------------------------------------------------------------------------
# 时间重排算法
# ---------------------------------------------------------------------------
def test_removed_activity_shifts_following_forward():
    eng = make_engine()
    trip = make_trip()
    acts = trip["days"][0]["activities"]
    acts.pop(0)  # 移除景点A，空出 9:00-11:00
    eng._shift_forward(acts, 0, 120)
    assert acts[0]["time_start"] == "09:30"  # 11:30 前移 120 分钟
    assert acts[0]["time_end"] == "11:00"
    assert acts[1]["time_start"] == "11:30"


def test_delay_shifts_following_backward():
    eng = make_engine()
    trip = make_trip()
    acts = trip["days"][0]["activities"]
    eng._shift_backward(acts, 1, 60)  # 从索引1起顺延 60 分钟
    assert acts[1]["time_start"] == "12:30"
    assert acts[2]["time_end"] == "16:30"


def test_realign_reschedules_from_target():
    """realign 只顺延不提前：新起点 = max(前项结束+间隔, 原起点)"""
    eng = make_engine()
    trip = make_trip()
    acts = trip["days"][0]["activities"]
    acts[1]["time_end"] = "14:00"  # 午餐拖到 14:00 结束
    eng._realign(acts, 1)  # 从午餐起重排后续
    # 博物馆原 13:30 早于午餐结束+10min 间隔，被推到 14:10，保持 2 小时时长
    assert acts[2]["time_start"] == "14:10"
    assert acts[2]["time_end"] == "16:10"


# ---------------------------------------------------------------------------
# reroute 主流程（无 LLM 路径）
# ---------------------------------------------------------------------------
def test_reroute_closed_activity_replaces_with_fallback():
    """闭园：规则兜底给替代活动，占原时段；无 LLM 时不前移后续"""
    eng = make_engine()
    trip = make_trip()
    result = eng.reroute(trip, {"title": "景点A", "time_start": "09:00", "time_end": "11:00"}, "景点临时闭园")
    replacement = result["days"][0]["activities"][0]
    assert replacement["status"] == "scheduled"
    assert replacement["title"] == "周边休闲漫步"  # 规则兜底替代
    assert replacement["time_start"] == "09:00"  # 占用原活动时段
    assert "推荐替代" in result["reroute_summary"]


def test_reroute_delayed_extends_and_shifts():
    eng = make_engine()
    trip = make_trip()
    result = eng.reroute(
        trip,
        {"title": "午餐", "time_start": "11:30", "time_end": "14:30"},
        "用餐延误",
    )
    acts = result["days"][0]["activities"]
    assert acts[1]["time_end"] == "14:30"
    assert acts[2]["time_start"] == "15:00"  # 延误 90 分钟后顺延
    assert "延迟" in result["reroute_summary"]


def test_reroute_activity_not_found_is_noop():
    eng = make_engine()
    trip = make_trip()
    result = eng.reroute(trip, {"title": "不存在的活动"}, "闭园")
    assert result["reroute_summary"] == "未找到匹配活动"
    # 原行程未被破坏
    assert len(result["days"][0]["activities"]) == 3
