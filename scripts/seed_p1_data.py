"""P1 企业化种子数据 —— 组织 / 差旅政策 / 政策文档 / 审批示例 / 景点语料

用法（项目根目录）:
    python scripts/seed_p1_data.py

幂等：按名称/编号判断，已存在的记录跳过，可重复运行。
特意创建 employee_id 为 "web-user" 的员工 —— 前端默认会话 ID 即此值，
行程生成链路（政策检查 + 审批自动发起）演示时可直接命中。

同时预置一批景点/攻略语料（C 端个人出游 RAG 通道），使切换 personal 场景
时行程能引用真实景点内容，而不是只排日程。
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
    TravelGuideStore,
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


def seed_guides(guide_store):
    """景点/攻略语料（C 端个人出游 RAG 通道）。

    价格与时长均为公开参考值，正文已注明「以官方最新为准」，避免生成链路把
    演示语料当成实时准确报价（真实票价以外部 API / 官方渠道为准）。
    """
    payloads = [
        {
            "title": "杭州·西湖景区游玩攻略",
            "category": "attraction",
            "tags": ["杭州", "西湖", "景点", "免费"],
            "source": "示例语料（演示用）",
            "content": (
                "西湖环湖免费开放，全天可游。核心看点：断桥残雪、苏堤春晓、三潭印月（上岛游船参考 55 元/人，"
                "以码头当日挂牌为准）。建议游玩 3~4 小时，可步行苏堤/白堤或租公共自行车环湖。"
                "避坑：节假日及周末人流极大，建议 08:00 前抵达；雷峰塔登塔另收费（参考 40 元）。"
                "交通：地铁 1 号线龙翔桥站步行可达。"
            ),
        },
        {
            "title": "杭州·灵隐寺与飞来峰攻略",
            "category": "attraction",
            "tags": ["杭州", "灵隐寺", "飞来峰", "寺庙"],
            "source": "示例语料（演示用）",
            "content": (
                "进入灵隐寺需先购飞来峰景区门票（参考 45 元），再单独购灵隐寺香花券（参考 30 元），"
                "两票分开购买，别只买一张。建议游玩 2~3 小时。飞来峰石窟造像为全国重点文物，值得细看。"
                "提示：寺内素面口碑不错；初一十五及节假日香客众多，建议工作日上午前往。"
                "交通：公交 7 路/游 2 路至灵隐站。"
            ),
        },
        {
            "title": "成都·大熊猫繁育研究基地攻略",
            "category": "attraction",
            "tags": ["成都", "熊猫", "亲子", "景点"],
            "source": "示例语料（演示用）",
            "content": (
                "门票参考 55 元/人，需提前在官方渠道实名预约（旺季常约满，务必提前 1~3 天）。"
                "最佳时段为 07:30~09:30——熊猫上午进食活跃，午后多在睡觉，晚到体验大打折扣。"
                "建议游玩 3 小时。亲子推荐：月亮产房、太阳产房、幼年熊猫别墅。"
                "交通：地铁 3 号线熊猫大道站换乘接驳；自驾停车紧张建议早到。"
            ),
        },
        {
            "title": "成都·宽窄巷子与锦里古街攻略",
            "category": "food",
            "tags": ["成都", "宽窄巷子", "锦里", "小吃"],
            "source": "示例语料（演示用）",
            "content": (
                "宽窄巷子与锦里均免费开放，以川西民居与市井小吃为主。建议各安排 1.5~2 小时，"
                "傍晚亮灯后氛围最佳。小吃推荐：钟水饺、担担面、三大炮、蛋烘糕。"
                "避坑：核心街区内餐饮偏贵且排队久，可步行至周边居民区小店；节假日夜间非常拥挤。"
                "交通：地铁 4 号线宽窄巷子站；锦里紧邻武侯祠，可一并安排。"
            ),
        },
        {
            "title": "北京·故宫博物院参观攻略",
            "category": "attraction",
            "tags": ["北京", "故宫", "博物馆", "预约", "注意事项"],
            "source": "示例语料（演示用）",
            "content": (
                "【必须提前实名预约】故宫实行全网实名预约，通常提前 7 天在官方小程序放票，当天不现场售票，"
                "周一例行闭馆（法定节假日除外）。门票参考：旺季 60 元/淡季 40 元，珍宝馆/钟表馆另购。"
                "建议游玩 3~4 小时，动线只能由午门（南）进、神武门（北）或东华门出，不可逆行。"
                "避坑：务必带身份证原件；建议 08:30 开门即入以避开人流；租讲解器或提前预约讲解体验更好。"
            ),
        },
        {
            "title": "北京·八达岭长城攻略",
            "category": "attraction",
            "tags": ["北京", "长城", "八达岭", "户外"],
            "source": "示例语料（演示用）",
            "content": (
                "门票参考 40 元/人，需实名预约。建议游玩 3~4 小时，北八楼为最高点、坡度较陡，量力而行。"
                "交通：市郊铁路 S2 线（黄土店站）或旅游公交专线直达，比自驾省心（自驾停车远）。"
                "避坑：节假日人极多，建议工作日前往并早出发；长城上风大温差大，备外套；"
                "部分路段台阶落差大，穿防滑运动鞋，老人小孩优先坐缆车/滑车（另收费）。"
            ),
        },
        {
            "title": "西安·秦始皇兵马俑博物馆攻略",
            "category": "attraction",
            "tags": ["西安", "兵马俑", "博物馆", "预约"],
            "source": "示例语料（演示用）",
            "content": (
                "门票参考 120 元/人，需实名预约（官方渠道），建议提前 1~2 天购票。建议游玩 3 小时。"
                "参观顺序推荐：一号坑（规模最大）→ 三号坑 → 二号坑 → 铜车马展厅。"
                "避坑：强烈建议请讲解或租电子导览，否则只是「看土人」；景区外拉客的「免费讲解」多为购物团，谨慎。"
                "交通：地铁 9 号线华清池站换乘公交，或火车站东广场乘游 5 路（306 路）。"
            ),
        },
        {
            "title": "三亚·亚龙湾海滨度假攻略",
            "category": "attraction",
            "tags": ["三亚", "亚龙湾", "海滩", "度假"],
            "source": "示例语料（演示用）",
            "content": (
                "亚龙湾沙滩免费开放，沙质细白、水质清澈，适合游泳与亲子戏水。建议游玩 2~3 小时，"
                "傍晚看日落最佳。水上项目（摩托艇/潜水/拖伞）现场另收费，价格差异大，务必先问清再玩。"
                "避坑：正午紫外线极强，需高倍防晒并在 11:00~15:00 减少暴晒；"
                "海边拉客项目谨防临时加价。交通：市区乘 15/25 路公交可达，或打车约 40 分钟。"
            ),
        },
    ]
    created = []
    for p in payloads:
        _, is_new = ensure(guide_store, guide_store.list_all, "title", p["title"], p)
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
    guide_store = TravelGuideStore(data_dir=os.path.join(org, "guide_docs"))

    from store import TripStore
    trip_store = TripStore(data_dir=settings.trip_data_dir)  # 仅触发目录初始化
    del trip_store

    report = []
    report += seed_departments(dept_store)
    report += seed_employees(dept_store, emp_store)
    report += seed_policies(policy_store)
    report += seed_policy_docs(doc_store)
    report += seed_guides(guide_store)
    report += seed_approvals(approval_store, settings.trip_data_dir, emp_store, policy_store)

    print("P1 种子数据完成：")
    for name, is_new in report:
        print(f"  {'[新增]' if is_new else '[已存在]'} {name}")
    print(f"汇总：新增 {sum(1 for _, n in report if n)} 条，已有 {sum(1 for _, n in report if not n)} 条")


if __name__ == "__main__":
    main()
