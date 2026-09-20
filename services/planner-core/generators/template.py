"""商务场景行程模板直出 —— 固定框架 + 抽取参数填充（v3）。

产品诉求（2026-09-18 用户反馈）：商务差旅行程结构高度固定——去程交通 →
入住 → 拜访/会议 → 返程。此前每次都让大模型从零推理整份行程 JSON，
生成阶段耗时 10s+（实测 hy-mt2-pro 17.2s），且结构雷同、纯烧 token。

本模块把行程骨架改为代码确定性拼装：
  - 大模型只负责阶段一「参数抽取」（~2s）：目的地/日期/事由/交通方式/人数；
  - 骨架按抽取参数填充：日期天序列、事由槽位、交通方式话术、人数、预算估算；
  - 生成阶段 0 次 LLM 调用，毫秒级完成；personal 场景仍走大模型
    （旅游内容需要个性化与攻略语料 RAG 支撑，不做模板）。

时间模型（保证时段不重叠）：
  - 出发档 dep：默认 08:30；用户原话提到「下午/晚上出发」平移到 13:30；
  - 抵达时刻 arrival = dep + 270（市内赴枢纽 1h + 城际 3h 档）；
  - 首日晚间按「抵达时刻」驱动：抵达早（≤16:00）排休整/下午商务，
    抵达晚则直接晚餐+休整，绝不排出 23:00 以后的活动；
  - 单日往返固定早出发（单日排「下午出发」必然崩，强制 08:30 档）；
  - 末日返程统一 14:00 档；用户提到「上午返程」整体前移。

铁律：
  - 不编造航班号/车次/酒店名——交通话术用「按实际出票信息核对」，住宿只写
    「酒店入住办理」，具体品牌交给确认页与酒店候选（hotel_options）。
  - 大交通/住宿明细金额按固定估算口径分摊写入（tips 注明以实际出票/入住为准），
    保证明细条目费用加总与 budget_total 精确一致（2026-09-20 用户反馈：明细
    缺金额、行程缺住宿条目，观感"流程不对"）。
"""
import re
from datetime import datetime, timedelta

# 走模板直出的场景（商务类）。personal 不在此列 → 回退大模型生成。
TEMPLATE_SCENES = {"business", "meeting", "visit", "team"}

_SCENE_TITLE = {
    "business": "商务出差",
    "meeting": "会议参展",
    "visit": "客户拜访",
    "team": "团队出行",
}

# 往返大交通估算（元/人，往返合计；未接实时票价接口前的固定口径，明细按半程分摊）
_ROUNDTRIP_EST = {"airplane": 1600, "train": 1100, "drive": 1000}
# 住宿（元/人/晚）；餐饮与市内交通按骨架实际条目口径在预算公式中计算
_HOTEL_PER_NIGHT = 450

_MODE_NAME = {"airplane": "乘机", "train": "乘高铁", "drive": "自驾"}
_MODE_HUB = {"airplane": "机场", "train": "高铁站", "drive": ""}

_CHECKLIST = [
    "证件类: 身份证（自驾另带驾驶证）",
    "商务资料: 名片、合同/演示材料、笔记本",
    "电子设备: 笔记本电脑、手机充电器、充电宝",
    "衣物类: 商务着装（按会程准备正装）",
    "其他: 常用药品、雨伞",
]


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _act(ts: str, te: str, atype: str, title: str, loc: str,
         cost: int = 0, tips: str = "") -> dict:
    """构造单条活动（结构与大模型输出格式完全一致，前端/政策检查无感知）。"""
    return {
        "time_start": ts,
        "time_end": te,
        "type": atype,
        "title": title,
        "location": {"name": loc, "lat": 0.0, "lng": 0.0, "address": ""},
        "ticket_price": 0,
        "booking_required": False,
        "tips": tips,
        "estimated_cost": cost,
    }


def _minute(h: int, m: int = 0) -> int:
    return h * 60 + m


def _fmt(mins: int) -> str:
    mins = max(0, min(mins, 23 * 60 + 59))
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _detect_time_preference(query: str) -> dict:
    """从用户原话识别出发/返程时段偏好（正则，确定性）。

    例：「17号下午返程」→ 返程默认就在下午，无需特判；
        「上午返程」→ 末日整体前移；「下午出发」→ 首日出发档平移到 13:30。
    """
    q = str(query or "")
    late_depart = bool(re.search(r"(下午|晚上)[^，。]{0,8}(出发|飞|走|乘车|坐车|的高铁|的航班)", q))
    early_return = bool(re.search(r"上午[^，。]{0,8}(返程|返回|回程|回)", q))
    return {"late_depart": late_depart, "early_return": early_return}


def _party_members(params: dict) -> list:
    """按人数参数生成出行人列表（姓名用通用占位，确认页可改）。"""
    members = []
    spec = [("num_adults", "adult", "出行人"), ("num_children", "child", "儿童"),
            ("num_elders", "elder", "老人")]
    for field, role, base in spec:
        try:
            n = int(params.get(field) or 0)
        except (TypeError, ValueError):
            n = 0
        for i in range(max(0, n)):
            members.append({
                "name": base if i == 0 else f"{base}{i + 1}",
                "role": role,
                "age": 0,
            })
    return members or [{"name": "出行人", "role": "adult", "age": 0}]


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_trip_from_template(params: dict, preferences: dict = None,
                             query: str = "") -> dict | None:
    """商务类场景模板直出。适用条件不满足时返回 None（调用方回退大模型生成）。

    Args:
        params: 阶段一抽取（合并显式/澄清参数后）的完整参数
        preferences: 用户偏好补充（原样挂到行程 preferences）
        query: 用户原始需求（用于识别「下午出发/上午返程」时段线索）

    Returns:
        行程字典（结构与大模型输出一致），或 None
    """
    params = params or {}
    scene = str(params.get("scene") or "").strip().lower()
    if scene not in TEMPLATE_SCENES:
        return None
    dest = str(params.get("destination") or "").strip()
    start_date = str(params.get("start_date") or "").strip()
    if not dest or not start_date:
        return None
    try:
        days = max(1, int(params.get("days")))
    except (TypeError, ValueError):
        return None
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        return None

    origin = str(params.get("origin") or "").strip()
    mode = params.get("transport") or "airplane"
    if mode not in _MODE_NAME:
        mode = "airplane"
    purpose = str(params.get("purpose") or "").strip()
    biz_title = purpose or _SCENE_TITLE[scene]
    notes = str(params.get("notes") or "").strip()
    dietary = params.get("dietary") or []
    diet_tips = f"饮食偏好：{'、'.join(dietary)}" if dietary else ""

    tp = _detect_time_preference(query)
    # 单日往返固定早出发（下午出发单日排不下），多日识别「下午出发」平移
    dep = _minute(8, 30) if (days == 1 or not tp["late_depart"]) else _minute(13, 30)
    arrival = dep + 270  # 城际大交通抵达时刻

    def dates() -> list:
        return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    def transport_title(frm: str, to: str) -> str:
        seg = f"{frm} → {to}" if frm else f"前往{to}"
        return f"{_MODE_NAME[mode]} {seg}".strip()

    def leg_out(acts: list):
        """去程两段：市内前往枢纽 + 城际大交通。"""
        hub = f"{origin}{_MODE_HUB[mode]}" if origin else _MODE_HUB[mode]
        acts.append(_act(_fmt(dep), _fmt(dep + 60), "transport",
                         f"前往{_MODE_HUB[mode]}" + (f"（{origin}）" if origin else ""),
                         hub, cost=50, tips="预留值机/安检缓冲"))
        acts.append(_act(_fmt(dep + 90), _fmt(dep + 270), "transport",
                         transport_title(origin, dest), dest,
                         cost=_ROUNDTRIP_EST[mode] // 2,
                         tips="按实际出票信息核对航班/车次；金额为往返估价的一半，如需调整出发时段，在确认页说明后重新生成"))

    def return_day(acts: list):
        """末日返程：退房 → 收尾沟通 → 午餐 → 枢纽 → 城际 → 抵达。

        默认 14:00 档返程；「上午返程」整体前移（早班返程不排午餐）。
        """
        if tp["early_return"]:
            acts.append(_act("08:30", "09:00", "accommodation",
                             "酒店退房 · 行李寄存前台", dest))
            acts.append(_act("09:00", "10:00", "meeting",
                             f"{biz_title}（收尾沟通）", dest,
                             tips="提前确认参会/拜访时间地点与对接人"))
            acts.append(_act("10:00", "10:30", "transport",
                             f"前往{_MODE_HUB[mode]}（{dest}）",
                             f"{dest}{_MODE_HUB[mode]}", cost=50))
            acts.append(_act("11:00", "14:00", "transport",
                             transport_title(dest, origin) if origin
                             else f"{_MODE_NAME[mode]} 返回出发地",
                             origin or "出发地", cost=_ROUNDTRIP_EST[mode] // 2,
                             tips="按实际出票信息核对航班/车次；金额为往返估价的一半"))
            acts.append(_act("14:30", "15:00", "other",
                             f"抵达{origin or '出发地'}，行程结束", origin or "出发地"))
        else:
            acts.append(_act("08:30", "09:00", "accommodation",
                             "酒店退房 · 行李寄存前台", dest))
            acts.append(_act("09:00", "11:30", "meeting",
                             f"{biz_title}（收尾沟通/机动时段）", dest,
                             tips="提前确认参会/拜访时间地点与对接人"))
            acts.append(_act("11:30", "12:30", "dining", "午餐", dest,
                             cost=60, tips=diet_tips))
            acts.append(_act("12:30", "13:30", "transport",
                             f"前往{_MODE_HUB[mode]}（{dest}）",
                             f"{dest}{_MODE_HUB[mode]}", cost=50))
            acts.append(_act("14:00", "17:00", "transport",
                             transport_title(dest, origin) if origin
                             else f"{_MODE_NAME[mode]} 返回出发地",
                             origin or "出发地", cost=_ROUNDTRIP_EST[mode] // 2,
                             tips="按实际出票信息核对航班/车次；金额为往返估价的一半"))
            acts.append(_act("17:30", "18:00", "other",
                             f"抵达{origin or '出发地'}，行程结束", origin or "出发地"))

    def biz_block(acts: list, tag: str, start_min: int, end_min: int):
        """业务主体活动槽位：事由来自抽取参数，不编造客户名。"""
        acts.append(_act(_fmt(start_min), _fmt(end_min), "meeting",
                         f"{biz_title}（{tag}）", dest,
                         tips="提前确认参会/拜访时间地点与对接人"))

    def dine(acts: list, start_min: int, title: str, cost: int, mins: int = 90):
        acts.append(_act(_fmt(start_min), _fmt(start_min + mins), "dining",
                         title, dest, cost=cost, tips=diet_tips))

    all_dates = dates()
    trip_days = []

    if days == 1:
        # 单日压缩：早去午谈晚归（固定早出发档）
        acts = []
        leg_out(acts)
        acts.append(_act(_fmt(arrival + 30), _fmt(arrival + 60), "transport",
                         "前往客户/会场", dest))
        biz_block(acts, "下午", arrival + 60, arrival + 240)   # 14:00-17:00
        dine(acts, arrival + 270, "晚餐", 80, mins=60)          # 17:30-18:30
        acts.append(_act(_fmt(arrival + 330), _fmt(arrival + 360), "transport",
                         f"前往{_MODE_HUB[mode]}（{dest}）",
                         f"{dest}{_MODE_HUB[mode]}", cost=50))
        acts.append(_act(_fmt(arrival + 390), _fmt(arrival + 570), "transport",
                         transport_title(dest, origin) if origin
                         else f"{_MODE_NAME[mode]} 返回出发地",
                         origin or "出发地", cost=_ROUNDTRIP_EST[mode] // 2,
                         tips="按实际出票信息核对航班/车次；金额为往返估价的一半"))
        acts.append(_act(_fmt(arrival + 600), _fmt(arrival + 630), "other",
                         f"抵达{origin or '出发地'}，行程结束", origin or "出发地"))
        trip_days.append({"date": all_dates[0],
                          "theme": f"{biz_title}（当日往返）", "activities": acts})
    else:
        # ---- 首日：去程 + 按抵达时刻分流晚间 ----
        d1 = []
        leg_out(d1)
        d1.append(_act(_fmt(arrival), _fmt(arrival + 45), "accommodation",
                       "酒店入住办理", dest, cost=_HOTEL_PER_NIGHT,
                       tips="住宿建议选客户/会场附近，候选见酒店选项；金额按 450/晚 估算，以实际入住为准"))
        if arrival + 45 <= _minute(16):
            # 抵达早：下午留给休整（≥3 天）或首场商务（2 天）
            if days == 2:
                biz_block(d1, "下午", arrival + 60, min(arrival + 240, _minute(17, 30)))
            else:
                d1.append(_act(_fmt(arrival + 60), _fmt(arrival + 180), "rest",
                               "驻地休整 · 准备明日行程", dest,
                               tips=notes or f"核对明日{biz_title}安排"))
            dine(d1, _minute(18), "晚餐", 100)
        else:
            # 抵达晚（「下午出发」档）：直接晚餐+休整，不硬塞商务
            dine(d1, arrival + 60, "晚餐", 100)
            d1.append(_act(_fmt(arrival + 150), _fmt(arrival + 210), "rest",
                           "驻地休整 · 准备明日行程", dest,
                           tips=notes or f"核对明日{biz_title}安排"))
        theme1 = f"赴{dest} · 抵达安顿" if days >= 3 else f"赴{dest} · {biz_title}"
        trip_days.append({"date": all_dates[0], "theme": theme1, "activities": d1})

        # ---- 中间天：全天商务 ----
        for i in range(1, days - 1):
            dm = []
            dm.append(_act("08:30", "09:00", "transport", "前往客户/会场", dest, cost=30))
            biz_block(dm, "上午", _minute(9), _minute(12))
            dine(dm, _minute(12), "午餐（工作餐）", 60)
            biz_block(dm, "下午", _minute(14), _minute(17, 30))
            dine(dm, _minute(18), "晚餐", 80)
            dm.append(_act("20:00", "21:00", "rest", "晚间复盘 · 整理当日纪要", dest))
            dm.append(_act("21:00", "21:30", "accommodation", "返回酒店休息", dest,
                           cost=_HOTEL_PER_NIGHT,
                           tips="金额按 450/晚 估算，以实际入住为准"))
            trip_days.append({
                "date": all_dates[i],
                "theme": biz_title if purpose else f"{dest}{_SCENE_TITLE[scene]}",
                "activities": dm,
            })

        # ---- 末日：收尾 + 返程 ----
        dl = []
        return_day(dl)
        trip_days.append({"date": all_dates[-1], "theme": "返程", "activities": dl})

    # ---- 预算：用户给了就用用户的；没给按固定口径估算（代填） ----
    try:
        budget = float(params.get("budget_total") or 0)
    except (TypeError, ValueError):
        budget = 0
    budget_estimated = budget <= 0
    if budget_estimated:
        adults = int(params.get("num_adults") or 1)
        children = int(params.get("num_children") or 0)
        elders = int(params.get("num_elders") or 0)
        party = max(1, adults + children + elders)
        # 预算 = 明细条目金额（人均）× 人数，与前端条目费用加总精确一致
        # （2026-09-20 用户反馈：此前公式口径与明细脱节，条目缺金额观感"流程不对"）
        per_person = sum(a.get("estimated_cost", 0)
                         for d in trip_days for a in d["activities"])
        budget = round(per_person * party)

    title = f"{start.year}年{start.month}月{dest}{biz_title}之行"
    return {
        "title": title,
        "destination": dest,
        "origin": origin,
        "start_date": all_dates[0],
        "end_date": all_dates[-1],
        "budget_total": budget,
        "travel_party": _party_members(params),
        "days": trip_days,
        "checklist": list(_CHECKLIST),
        "preferences": dict(preferences or {}),
        "generation_mode": "template",
        "budget_estimated": budget_estimated,
    }
