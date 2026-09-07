"""P1 企业化种子数据 —— 组织 / 差旅政策 / 政策文档 / 审批示例

用法（项目根目录）:
    python scripts/seed_p1_data.py

幂等：按名称/编号判断，已存在的记录跳过，可重复运行。
特意创建 employee_id 为 "web-user" 的员工 —— 前端默认会话 ID 即此值，
行程生成链路（政策检查 + 审批自动发起）演示时可直接命中。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "services", "planner-core"))

from shared.config import settings
from shared.logging_config import setup_logging
from store import (
    DepartmentStore, EmployeeStore, PolicyStore, ApprovalStore, PolicyDocumentStore,
)


def org_dir() -> str:
    return os.path.join(os.path.dirname(settings.trip_data_dir), "org")


def ensure(deps, fetch, name_key, name_value, payload):
    """按唯一键幂等写入。返回 (created: bool, entity)。"""
    existing = fetch()
    for e in existing:
        if e.get(name_key) == name_value:
            return False, e
    entity_id = deps.save(payload)
    return True, deps.get(entity_id)


def seed_departments(dept_store):
    created = []
    for payload in [
        {"name": "技术部", "parent_id": "", "manager_id": "emp_1001", "description": "产品研发与技术支持"},
        {"name": "市场部", "parent_id": "", "manager_id": "emp_1001", "description": "市场推广与客户拓展"},
    ]:
        is_new, dept = ensure(dept_store, dept_store.list_all, "name", payload["name"], payload)
        created.append((payload["name"], is_new))
    return created


def seed_employees(dept_store, emp_store):
    tech = next((d for d in dept_store.list_all() if d["name"] == "技术部"), {})
    market = next((d for d in dept_store.list_all() if d["name"] == "市场部"), {})
    payloads = [
        {
            # 前端默认会话 ID 就是 "web-user"，行程生成链路靠它命中
            "employee_id": "web-user",
            "name": "张伟", "dept_id": tech.get("dept_id", ""), "level": "junior",
            "title": "工程师", "email": "zhangwei@corp.example", "phone": "",
            "manager_id": "emp_1001",
        },
        {
            "employee_id": "emp_1001",
            "name": "李明远", "dept_id": tech.get("dept_id", ""), "level": "director",
            "title": "技术总监", "email": "limingyuan@corp.example", "phone": "",
            "manager_id": "",
        },
        {
            "employee_id": "emp_1002",
            "name": "王芳", "dept_id": market.get("dept_id", ""), "level": "junior",
            "title": "市场专员", "email": "wangfang@corp.example", "phone": "",
            "manager_id": "emp_1001",
        },
    ]
    created = []
    for p in payloads:
        if emp_store.get(p["employee_id"]):
            created.append((p["name"], False))
            continue
        fixed_id = p.pop("employee_id")
        emp_store.save({**p, "employee_id": fixed_id})
        created.append((p["name"], True))
    return created


def seed_policies(policy_store):
    payloads = [
        {
            "name": "普通员工差旅标准", "level": "junior", "city_tier": "all",
            "flight_class": "economy", "train_class": "second",
            "hotel_limit": 600, "meal_limit": 150, "transport_limit": 100,
            "daily_subsidy": 100, "requires_approval": True, "approval_threshold": 8000,
            "description": "经济舱/二等座，酒店≤600/晚，审批阈值 8000 元",
        },
        {
            "name": "总监级差旅标准", "level": "director", "city_tier": "all",
            "flight_class": "economy", "train_class": "first",
            "hotel_limit": 1200, "meal_limit": 300, "transport_limit": 200,
            "daily_subsidy": 200, "requires_approval": False, "approval_threshold": 20000,
            "description": "酒店≤1200/晚，预算 2 万以下免审批",
        },
    ]
    created = []
    for p in payloads:
        _, is_new = ensure(policy_store, policy_store.list_all, "name", p["name"], p)
        created.append((p["name"], is_new))
    return created


def seed_policy_docs(doc_store):
    payloads = [
        {
            "title": "差旅费用报销制度",
            "category": "expense",
            "tags": ["报销", "差旅"],
            "source": "财务部",
            "content": (
                "差旅费用报销须在行程结束后 10 个工作日内提交。交通费凭票据实报销："
                "飞机经济舱、高铁二等座。住宿费按职级标准上限报销，超标部分自理。"
                "市内交通（出租车、网约车）实报实销，单日上限 100 元。"
                "餐饮补贴按自然日计算，无需提供发票。所有报销需附行程单与审批单编号。"
            ),
        },
        {
            "title": "出差审批管理制度",
            "category": "approval",
            "tags": ["审批", "制度"],
            "source": "行政部",
            "content": (
                "所有出差行程须提前发起审批，由直属主管审批生效。预算超过 8000 元的行程"
                "需额外抄送部门总监。未经审批的行程费用不予报销。紧急出差可事后 24 小时内"
                "补办审批手续。审批通过后行程方可进入执行状态。"
            ),
        },
        {
            "title": "住宿标准说明",
            "category": "policy",
            "tags": ["住宿", "标准"],
            "source": "行政部",
            "content": (
                "一线城市（北京/上海/广州/深圳）酒店上限：普通员工 600 元/晚，总监级 1200 元/晚。"
                "二线城市按标准的 80% 执行。超标入住须事前说明原因并经主管同意。"
                "同一城市连续住宿超过 5 晚的，超出部分按 90% 报销。"
            ),
        },
    ]
    created = []
    for p in payloads:
        _, is_new = ensure(doc_store, doc_store.list_all, "title", p["title"], p)
        created.append((p["title"], is_new))
    return created


def seed_approvals(approval_store, trip_data_dir, emp_store, policy_store):
    """为 Approval 页面造两条待审批示例：直接挂在已有行程上，没有行程则跳过。"""
    import json
    import glob

    trips = []
    for path in sorted(glob.glob(os.path.join(trip_data_dir, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                trips.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    trips.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
    if not trips:
        return [("（无行程可挂，跳过）", False)]
    zhang = emp_store.get("web-user")
    li = emp_store.get("emp_1001")
    policy = policy_store.get_best_match("junior")
    created = []
    for i, trip in enumerate(trips[:2]):
        remark = f"种子审批示例 {i + 1}：{trip.get('title', '')}"
        dup = any(a.get("remark") == remark for a in approval_store.list_all())
        if dup:
            created.append((remark, False))
            continue
        approval_id = approval_store.save({
            "trip_id": trip.get("trip_id", ""),
            "employee_id": "web-user",
            "approver_id": "emp_1001",
            "total_amount": trip.get("budget_total", 0),
            "policy_id": (policy or {}).get("policy_id", ""),
            "violations": [],
            "remark": remark,
            "status": "pending",
        })
        created.append((f"{remark} -> {approval_id}", True))
    # 兼容修复：早期创建的审批单缺 status 字段，统一补为 pending
    for a in approval_store.list_all():
        if not a.get("status"):
            approval_store.update(a["approval_id"], {"status": "pending"})
    return created


def main():
    setup_logging(level="INFO", service="seed-p1")
    org = org_dir()
    dept_store = DepartmentStore(data_dir=os.path.join(org, "departments"))
    emp_store = EmployeeStore(data_dir=os.path.join(org, "employees"))
    policy_store = PolicyStore(data_dir=os.path.join(org, "policies"))
    approval_store = ApprovalStore(data_dir=os.path.join(org, "approvals"))
    doc_store = PolicyDocumentStore(data_dir=os.path.join(org, "policy_docs"))

    from store import TripStore
    trip_store = TripStore(data_dir=settings.trip_data_dir)  # 仅触发目录初始化
    del trip_store

    report = []
    report += seed_departments(dept_store)
    report += seed_employees(dept_store, emp_store)
    report += seed_policies(policy_store)
    report += seed_policy_docs(doc_store)
    report += seed_approvals(approval_store, settings.trip_data_dir, emp_store, policy_store)

    print("P1 种子数据完成：")
    for name, is_new in report:
        print(f"  {'[新增]' if is_new else '[已存在]'} {name}")
    print(f"汇总：新增 {sum(1 for _, n in report if n)} 条，已有 {sum(1 for _, n in report if not n)} 条")


if __name__ == "__main__":
    main()
