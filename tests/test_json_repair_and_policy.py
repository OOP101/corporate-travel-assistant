"""大模型 JSON 容错解析 + 政策/审批场景短路 的回归测试。

覆盖两处 2026-09-14 的改动：
  1. `shared.llm.json_repair` 五层容错解析（长输出被截断 / 值内未转义引号）
  2. `api.routers.trips` 的 `_policy_exempt_reason` 短路（个人出游 / 非员工不再套企业差旅政策）
"""
import json
import os
import sys

import pytest

PLANNER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "planner-core"
)

from shared.llm.json_repair import (  # noqa: E402
    fix_unescaped_quotes,
    parse_json_tolerant,
    repair_truncated_json,
    sanitize_json_str,
)


# ---------------------------------------------------------------------------
# 一、五层容错解析
# ---------------------------------------------------------------------------
def test_plain_json_hits_first_layer():
    data, layer = parse_json_tolerant('{"title": "杭州三日"}')
    assert data == {"title": "杭州三日"}
    assert layer == "原文"


def test_strips_markdown_fence_and_zero_width():
    raw = '```json\n{"title": "杭\u200b州三日"}\n```'
    data, _ = parse_json_tolerant(raw)
    assert data["title"] == "杭州三日"


def test_slices_out_of_surrounding_prose():
    raw = '好的，这是你的行程：\n{"title": "杭州三日"}\n希望你喜欢！'
    data, layer = parse_json_tolerant(raw)
    assert data == {"title": "杭州三日"}
    assert layer in ("区间切片", "原文", "正则提取")


def test_repairs_truncated_brackets():
    """max_tokens 截断导致括号没闭合 —— 必须退到最后一个完整值再补齐。"""
    raw = '{"days": [{"date": "2026-09-14", "activities": ['
    data, layer = parse_json_tolerant(raw)
    assert data is not None, "截断修复失败"
    assert data["days"][0]["date"] == "2026-09-14"
    assert layer == "截断修复"


def test_repairs_truncated_within_nested_value():
    raw = '{"days": [{"date": "2026-09-14", "activities": [{"title": "西湖"'
    data, _ = parse_json_tolerant(raw)
    assert data["days"][0]["activities"][0]["title"] == "西湖"


def test_repairs_unescaped_quotes_in_value():
    """中文输出高频：值内部含裸双引号。"""
    raw = '{"title": "他说"西湖很美"今天"}'
    data, layer = parse_json_tolerant(raw)
    assert data["title"] == '他说"西湖很美"今天'
    assert layer == "修复未转义引号"


def test_repairs_truncated_and_quotes_together():
    raw = '{"title": "他说"西湖很美"", "days": [{"date": "2026-09-14"'
    data, _ = parse_json_tolerant(raw)
    assert data is not None
    assert data["days"][0]["date"] == "2026-09-14"


def test_too_early_truncation_returns_none():
    """一个完整值都没有时无可救内容 —— 应返回失败，由上层走 LLM 修补/演示降级。"""
    data, layer = parse_json_tolerant('{"title": "杭州')
    assert data is None and layer == ""


def test_non_json_returns_none():
    data, layer = parse_json_tolerant("抱歉，我无法为你规划行程。")
    assert data is None and layer == ""


def test_repair_helpers_are_pure_and_idempotent():
    """已是合法 JSON 时，修复函数不应改写内容。"""
    good = '{"a": 1, "b": [1, 2]}'
    assert repair_truncated_json(good) == good
    assert fix_unescaped_quotes(good) == good
    assert sanitize_json_str(good) == good
    # 合法 JSON 二次修复仍合法
    assert json.loads(repair_truncated_json(good)) == {"a": 1, "b": [1, 2]}


# ---------------------------------------------------------------------------
# 二、政策 / 审批场景短路
# ---------------------------------------------------------------------------
@pytest.fixture()
def trips_mod(tmp_path):
    """拿到 planner-core 的 trips 模块，并把组织/政策存储指向临时目录。

    三个服务都有顶层 api 包，必须与 test_planner_api 一样保证 planner-core 优先，
    否则会解析到别的服务同名包。
    """
    if PLANNER_DIR in sys.path:
        sys.path.remove(PLANNER_DIR)
    sys.path.insert(0, PLANNER_DIR)
    for _mod in [m for m in list(sys.modules) if m == "api" or m.startswith("api.")]:
        del sys.modules[_mod]

    import api.routers.trips as trips          # noqa: E402
    from store import EmployeeStore, PolicyStore, ApprovalStore  # noqa: E402

    assert "planner-core" in trips.__file__.replace("\\", "/").lower()

    deps = trips.deps
    deps.employee_store = EmployeeStore(data_dir=str(tmp_path / "employees"))
    deps.policy_store = PolicyStore(data_dir=str(tmp_path / "policies"))
    deps.approval_store = ApprovalStore(data_dir=str(tmp_path / "approvals"))

    deps.employee_store.save(
        {"employee_id": "emp_e1", "name": "测试员工", "level": "junior", "manager_id": "emp_m"}
    )
    deps.employee_store.save(
        {"employee_id": "emp_m", "name": "测试主管", "level": "director", "manager_id": ""}
    )
    deps.policy_store.save({
        "policy_id": "pol_j1",
        "name": "普通员工差旅标准",
        "level": "junior",
        "city_tier": "all",
        "hotel_limit": 600,
        "meal_limit": 100,
        "transport_limit": 0,
        "requires_approval": True,
        "approval_threshold": 8000,
        "is_active": True,
    })
    return trips


@pytest.mark.parametrize("scene", ["personal"])
def test_personal_scene_is_exempt_even_for_employee(trips_mod, scene):
    """个人出游即使对员工也免检（与「企业差旅政策」无关）。"""
    reason = trips_mod._policy_exempt_reason({"scene": scene}, "emp_e1")
    assert reason, "个人出游场景应当免检"


def test_non_employee_is_exempt(trips_mod):
    """无员工档案 → 没有职级可匹配，不该套通用政策。"""
    reason = trips_mod._policy_exempt_reason({"scene": "business"}, "user_without_record")
    assert reason and "无员工档案" in reason


@pytest.mark.parametrize("scene", ["business", "meeting", "visit", "team"])
def test_business_scenes_still_checked_for_employee(trips_mod, scene):
    """员工走企业差旅场景时不得被短路（防止把管控闭环改没了）。"""
    assert trips_mod._policy_exempt_reason({"scene": scene}, "emp_e1") == ""


def test_policy_preview_skipped_when_exempt(trips_mod):
    assert trips_mod._policy_preview({"scene": "personal", "budget_total": 5000}, "emp_e1") == {}


def test_policy_preview_runs_for_business_employee(trips_mod):
    """正向对照：企业差旅场景 + 员工 → 政策预检照常产出。"""
    event = trips_mod._policy_preview(
        {"scene": "business", "budget_total": 5000, "days": []}, "emp_e1"
    )
    assert event.get("event") == "policy"
    assert event.get("policy_id") == "pol_j1"


def test_confirm_flow_skipped_when_exempt(trips_mod):
    """豁免场景下确认不产生政策 / 审批事件，也不建审批单。"""
    events = trips_mod._confirm_policy_flow(
        {"scene": "personal", "budget_total": 5000, "days": []}, "trip_x", "emp_e1"
    )
    assert events == []
    assert trips_mod.deps.approval_store.list_all() == []


def test_confirm_flow_creates_approval_for_business_employee(trips_mod):
    """正向对照：企业差旅场景 + 员工 + 需审批政策 → 政策事件 + 审批单。"""
    events = trips_mod._confirm_policy_flow(
        {"scene": "business", "budget_total": 5000, "days": []}, "trip_y", "emp_e1"
    )
    kinds = [e.get("event") for e in events]
    assert "policy" in kinds
    assert "approval" in kinds
    approvals = trips_mod.deps.approval_store.list_all()
    assert len(approvals) == 1
    assert approvals[0]["approver_id"] == "emp_m"
