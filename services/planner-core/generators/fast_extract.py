"""规则式快速参数抽取 —— 常见差旅句式 0 LLM 直取（v3，配合模板直出）。

实测动机（2026-09-18）：模板直出落地后，商务行程生成阶段已 0 LLM（0ms），
但参数抽取仍走大模型 —— deepseek-v4-flash 经 TokenHub 实测 8.8s，成了新瓶颈。
而「9月15号广州飞北京出差，16号拜访客户，17号返程」这类句式的抽参本身
就是固定流程：日期/城市/交通方式/场景关键词全是确定性规则可覆盖的。

策略：
  - 正则命中全部必填参数（scene/destination/start_date/days）→ 直接采用，
    全链路 0 LLM，毫秒级出草案；
  - 命中不全 → 整体回退大模型抽取（复杂句式/相对日期仍可靠），规则结果
    不与大模型结果混拼（避免两套口径打架）；
  - 城市识别用内置主要城市表校验 + 前后缀垃圾修剪，拒绝「我想去北京」误抓；
  - 裸「16号」按已解析日期的月份上下文取月，跨月（「10月1号…15号」）不错位；
  - 过去日期自动顺延到下一年（「9月15号」在 9 月 18 号说 → 明年 9 月 15 日）。

安全网：v2 流程生成的本就是「草案」，确认页展示全部参数，用户可改——
规则抽取的个别歧义由确认环节兜底，与 LLM 抽取同级。
"""
import re
from datetime import date, datetime, timedelta

# 主要城市表（直辖市 + 省会 + 主要商务/旅游城市）。城市不在表内 → 快速抽取
# 放弃城市判定，整体回退大模型，宁慢勿错。
_CITIES = {
    # 直辖市
    "北京", "上海", "天津", "重庆",
    # 省会/首府
    "广州", "深圳", "杭州", "南京", "成都", "西安", "武汉", "长沙", "郑州",
    "石家庄", "太原", "沈阳", "长春", "哈尔滨", "合肥", "福州", "南昌",
    "济南", "南宁", "海口", "贵阳", "昆明", "拉萨", "兰州", "西宁", "银川",
    "乌鲁木齐", "呼和浩特",
    # 计划单列/经济重镇
    "青岛", "大连", "宁波", "厦门", "苏州", "无锡", "佛山", "东莞", "珠海",
    "中山", "惠州", "温州", "金华", "绍兴", "嘉兴", "台州", "泉州", "烟台",
    "潍坊", "洛阳", "唐山", "徐州", "常州", "南通", "扬州", "泰州", "镇江",
    # 旅游热点
    "三亚", "丽江", "桂林", "张家界", "西双版纳", "大理", "北海", "承德",
    "秦皇岛", "泰安", "黄山", "九江", "遵义", "喀什", "伊犁", "延吉",
    "齐齐哈尔", "包头", "鄂尔多斯", "汕头", "湛江", "西宁", "银川",
}

# 场景关键词（按优先级，先命中先定；对齐 LLM 抽取口径）
_SCENE_PATTERNS = [
    ("business", re.compile(r"出差|商务出行|商务之旅")),
    ("meeting", re.compile(r"会议|参会|参展|展会|布展|撤展|峰会|论坛")),
    ("team", re.compile(r"团建|团队出行|拓展|集体活动")),
    ("visit", re.compile(r"拜访|见客户|客户走访|商务宴请")),
    ("personal", re.compile(r"旅游|游玩|去玩|度假|自由行|自驾游|一日游|(?<!玩)玩(?![具笑])")),
]

# 交通方式（airplane 的裸「飞」用否定环视避开「高铁/火车」与「飞机」误判）
_TRANSPORT_PATTERNS = [
    ("airplane", re.compile(r"飞机|航班|机票|飞往|(?<![高火动])飞(?=[一-龥A-Za-z])")),
    ("train", re.compile(r"高铁|火车|动车|列车")),
    ("drive", re.compile(r"自驾|开车|驾车|驱车")),
]

# 日期
_RE_MD = re.compile(r"(?:(\d{4})\s*[-/年]\s*)?(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*[号日]?")
_RE_DAY_ONLY = re.compile(r"(?<![\d/年月-])(\d{1,2})\s*[号日](?![\d月])")
_RE_N_DAYS = re.compile(r"(\d+|[两俩])\s*天")
_RE_N_WEEKS = re.compile(r"(?:(\d+)\s*周|一周)")
_RE_RELATIVE = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}

# 城市
_RE_FROM_TO = re.compile(r"从\s*([一-龥]{2,6})\s*.{0,4}?(?:飞|到|去|前往)\s*([一-龥]{2,6})")
_RE_TO = re.compile(r"([一-龥]{2,6})\s*(?:飞往|飞|坐飞机去|高铁去|到|去|前往)\s*([一-龥]{2,6})")
_RE_DEST_ONLY = re.compile(r"(?:去|到|飞|前往)\s*([一-龥]{2,6})")
# 「三亚度假」「成都旅游」类：城市直接跟活动动词
_RE_DEST_STAY = re.compile(r"([一-龥]{2,6})(?:度假|旅游|出游|旅行)")

# 非城市首缀（「我想去北京」防误抓；命中则丢弃来源候选）
_JUNK_ORIGIN = {"我想", "我们", "打算", "准备", "计划", "想要", "需要", "公司", "总部"}

# 事由（在剔除日期后的文本上匹配）
_RE_PURPOSE = [
    re.compile(r"(拜访[^，。；,;、]{1,15})"),
    re.compile(r"(?:参加|出席)([^，。；,;、]{1,15})"),
    re.compile(r"((?:会见|见)[^，。；,;、]{1,15})"),
]
# 预算/人数
_RE_BUDGET = re.compile(r"(?:预算|费用|花费)[^0-9]{0,4}(\d{3,7})")
_RE_PEOPLE = re.compile(r"(\d+|[两俩])\s*(?:个)?(?:成人|大人|人)")

REQUIRED_KEYS = ("scene", "destination", "start_date", "days")


def _clean_city(span: str) -> str:
    """候选城名修剪：城市可能在片段任意端，垃圾在另一侧。

    依次尝试「去尾」（北京出差→北京）与「去头」（从上海→上海），
    命中垃圾黑名单直接放弃，命中城市表返回。
    """
    if not span:
        return ""
    cands = [span[: len(span) - i] for i in range(len(span) - 1)]
    cands += [span[i:] for i in range(1, len(span) - 1)]
    for s in cands:
        if len(s) < 2:
            break
        if s in _JUNK_ORIGIN:
            return ""
        if s in _CITIES:
            return s
    return ""


def _resolve_date(y: int, m: int, d: int, today: date) -> str:
    """组装日期；过去日期顺延到下一年。非法日期返回空串。"""
    try:
        dt = date(y or today.year, m, d)
    except ValueError:
        return ""
    while dt < today:
        dt = date(dt.year + 1, dt.month, dt.day)
    return dt.strftime("%Y-%m-%d")


def _resolve_bare_day(day: int, base: date, today: date) -> str:
    """裸「16号」按上下文月份取月：从 base 月起向后找 3 个月内首个未过日期。"""
    y, m = base.year, base.month
    for _ in range(3):
        try:
            dt = date(y, m, day)
        except ValueError:
            return ""
        if dt >= today:
            return dt.strftime("%Y-%m-%d")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return ""


def fast_extract_params(query: str) -> dict | None:
    """规则抽取行程参数。返回只含命中字段的 dict；完全未命中返回 None。

    字段口径与 LLM 抽取 schema 一致（scene/destination/origin/transport/
    start_date/end_date/days/purpose/num_adults/budget_total）。
    """
    q = str(query or "").strip()
    if not q:
        return None
    today = date.today()
    params: dict = {}

    # ---- 场景 ----
    for scene, pat in _SCENE_PATTERNS:
        if pat.search(q):
            params["scene"] = scene
            break

    # ---- 交通方式 ----
    for mode, pat in _TRANSPORT_PATTERNS:
        if pat.search(q):
            params["transport"] = mode
            break

    # ---- 日期：绝对「X月X号」优先，裸「X号」按其月份上下文，相对词兜底 ----
    date_texts = []
    work = q
    for m in _RE_MD.finditer(q):
        y = int(m.group(1) or 0)
        ds = _resolve_date(y, int(m.group(2)), int(m.group(3)), today)
        if ds:
            date_texts.append(ds)
            work = work.replace(m.group(0), " ")
    base = today
    if date_texts:
        base = datetime.strptime(min(date_texts), "%Y-%m-%d").date()
    for m in _RE_DAY_ONLY.finditer(q):
        ds = _resolve_bare_day(int(m.group(1)), base, today)
        if ds and ds not in date_texts:
            date_texts.append(ds)
            work = work.replace(m.group(0), " ")
    for word, offset in _RE_RELATIVE.items():
        if word in q:
            ds = (today + timedelta(days=offset)).strftime("%Y-%m-%d")
            if ds not in date_texts:
                date_texts.append(ds)
                work = work.replace(word, " ")

    if date_texts:
        date_texts.sort()
        params["start_date"] = date_texts[0]
        if len(date_texts) > 1:
            params["end_date"] = date_texts[-1]
            try:
                params["days"] = (
                    datetime.strptime(date_texts[-1], "%Y-%m-%d")
                    - datetime.strptime(date_texts[0], "%Y-%m-%d")
                ).days + 1
            except ValueError:
                pass

    # ---- 天数兜底：「3天」「两天」「一周」「2周」 ----
    if not params.get("days"):
        m = _RE_N_DAYS.search(q)
        if m:
            n = 2 if m.group(1) in ("两", "俩") else int(m.group(1))
            if 1 <= n <= 30:
                params["days"] = n
        if not params.get("days"):
            m = _RE_N_WEEKS.search(q)
            if m:
                n = 7 * (int(m.group(1)) if m.group(1) else 1)
                if 1 <= n <= 30:
                    params["days"] = n
        if params.get("days") and params.get("start_date"):
            end = datetime.strptime(params["start_date"], "%Y-%m-%d") + timedelta(
                days=params["days"] - 1
            )
            params["end_date"] = end.strftime("%Y-%m-%d")

    # ---- 城市（在剔除日期的文本上匹配，防「号广州」误抓）----
    origin = dest = ""
    m = _RE_FROM_TO.search(work)
    if m:
        origin = _clean_city(m.group(1))
        dest = _clean_city(m.group(2))
    if not dest:
        m = _RE_TO.search(work)
        if m:
            d = _clean_city(m.group(2))
            if d:
                dest = d
                origin = origin or _clean_city(m.group(1))
    if not dest:
        for m in _RE_DEST_ONLY.finditer(work):
            d = _clean_city(m.group(1))
            if d:
                dest = d
                break
    if not dest:
        m = _RE_DEST_STAY.search(work)
        if m:
            dest = _clean_city(m.group(1))
    if dest:
        params["destination"] = dest
    if origin:
        params["origin"] = origin

    # ---- 事由 ----
    for pat in _RE_PURPOSE:
        m = pat.search(work)
        if m:
            params["purpose"] = m.group(1).strip()
            break

    # ---- 人数 / 预算 ----
    m = _RE_PEOPLE.search(q)
    if m:
        n = 2 if m.group(1) in ("两", "俩") else int(m.group(1))
        if 1 <= n <= 50:
            params["num_adults"] = n
    m = _RE_BUDGET.search(q)
    if m:
        params["budget_total"] = int(m.group(1))

    return params or None


def fast_covers_required(params: dict | None) -> bool:
    """规则结果是否已覆盖全部必填参数（覆盖则可跳过 LLM 抽取）。"""
    return bool(params) and all(params.get(k) for k in REQUIRED_KEYS)
