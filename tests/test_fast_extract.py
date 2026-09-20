"""规则式快速参数抽取（fast_extract）回归测试（2026-09-18）。

背景：模板直出落地后商务行程生成 0 LLM，但参数抽取走大模型实测 8.8s
（deepseek-v4-flash 经 TokenHub）。常见差旅句式改为正则直取：
命中全部必填 → 0 LLM 全链路；命中不全 → 整体回退 LLM（不混拼）。

覆盖：典型句式命中 / 城市修剪 / 裸日期月份上下文 / 过去日期顺延 /
垃圾前缀拒识 / 命中不全回退。
"""
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANNER_DIR = os.path.join(ROOT, "services", "planner-core")


@pytest.fixture(scope="module")
def fe():
    if PLANNER_DIR in sys.path:
        sys.path.remove(PLANNER_DIR)
    sys.path.insert(0, PLANNER_DIR)
    for _m in [m for m in list(sys.modules) if m == "generators" or m.startswith("generators.")]:
        del sys.modules[_m]
    from generators import fast_extract
    return fast_extract


# ---------------------------------------------------------------------------
# 一、典型差旅句式：命中全部必填 → 0 LLM
# ---------------------------------------------------------------------------
def test_user_original_query(fe):
    """用户原话（2026-09-18 反馈样例）：场景/城市/日期/事由全命中。"""
    p = fe.fast_extract_params("9月15号广州飞北京出差，16号上午拜访国贸客户，17号下午返程")
    assert fe.fast_covers_required(p)
    assert p["scene"] == "business"
    assert p["origin"] == "广州" and p["destination"] == "北京"
    assert p["transport"] == "airplane"
    assert p["days"] == 3
    assert p["purpose"] == "拜访国贸客户"


def test_train_and_party_budget(fe):
    p = fe.fast_extract_params("9月15号广州高铁到北京出差3天，2个人，预算8000")
    assert fe.fast_covers_required(p)
    assert p["transport"] == "train"
    assert p["num_adults"] == 2
    assert p["budget_total"] == 8000


def test_relative_date_complete(fe):
    p = fe.fast_extract_params("明天从上海去杭州出差两天")
    assert fe.fast_covers_required(p)
    assert p["origin"] == "上海" and p["destination"] == "杭州"
    assert p["days"] == 2


def test_week_unit(fe):
    p = fe.fast_extract_params("10月1号三亚度假一周")
    assert fe.fast_covers_required(p)
    assert p["days"] == 7 and p["destination"] == "三亚"


# ---------------------------------------------------------------------------
# 二、城市识别防误抓
# ---------------------------------------------------------------------------
def test_junk_origin_rejected(fe):
    """「我想」不是城市 → 只取目的地，不误抓来源。"""
    p = fe.fast_extract_params("我想去北京玩")
    assert p["destination"] == "北京"
    assert "origin" not in p


def test_city_trailing_junk_trimmed(fe):
    """「北京出差」「杭州出差」城市后缀垃圾被修剪。"""
    p = fe.fast_extract_params("明天从上海去杭州出差两天")
    assert p["destination"] == "杭州"


def test_unknown_city_incomplete(fe):
    """城市不在表内（防误抓）→ 判定不完整回退 LLM，宁慢勿错。"""
    p = fe.fast_extract_params("9月15号从北京飞呼伦贝尔出差5天")
    assert not fe.fast_covers_required(p)


# ---------------------------------------------------------------------------
# 三、日期语义
# ---------------------------------------------------------------------------
def test_past_date_rolls_forward(fe):
    """过去日期顺延下一年（今天之后才有意义）。"""
    today = date.today()
    p = fe.fast_extract_params("1月1号广州飞北京出差3天")
    assert fe.fast_covers_required(p)
    y = today.year + 1 if date(today.year, 1, 1) < today else today.year
    assert p["start_date"] == f"{y}-01-01"
    assert p["end_date"] == f"{y}-01-03"


def test_bare_day_uses_month_context(fe):
    """「10月1号…15号」裸日期不落回当前月。"""
    p = fe.fast_extract_params("10月1号去厦门玩，10月5号回")
    assert fe.fast_covers_required(p)
    assert p["start_date"].endswith("-10-01")
    assert p["end_date"].endswith("-10-05")
    assert p["days"] == 5


# ---------------------------------------------------------------------------
# 四、命中不全 → 回退 LLM（不硬凑）
# ---------------------------------------------------------------------------
def test_incomplete_falls_back(fe):
    cases = [
        "下个月去成都旅游5天",     # 相对日期规则不覆盖
        "我想去北京玩",             # 缺日期天数
        "后天去深圳见客户，预算3000",  # 缺天数（单日需澄清）
    ]
    for q in cases:
        p = fe.fast_extract_params(q)
        assert not fe.fast_covers_required(p), q


def test_scene_priority(fe):
    """「出差拜访」→ business 优先；「拜访客户」→ visit。"""
    p1 = fe.fast_extract_params("9月15号广州飞北京出差拜访客户3天")
    assert p1["scene"] == "business"
    p2 = fe.fast_extract_params("明天去深圳拜访客户，16号回")
    assert p2["scene"] == "visit"
