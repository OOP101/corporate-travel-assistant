"""
景点状态数据源 —— 景点临时关闭/开放时间变更感知

模式：
  - 真实模式：通过景点官方公告 API 查询（需配置 attraction_api_key）
  - Mock 模式：生成模拟景点状态（大部分正常开放，少量临时关闭/维护）

感知规则：
  - 景点临时关闭/维护 → critical，建议替代景点
  - 开放时间变更 → warning
  - 正常开放 → info
"""
import logging
import random
from typing import List

from shared.config import settings
from shared.http_client import ServiceClient
from shared.metrics import monitor_check_counter

from .base import BaseSource, SourceResult

logger = logging.getLogger("sense-engine.sources.attraction")

# 景点内部状态：open | closed | maintenance | hours_changed

# 知名景点 → 推荐替代景点（关闭时建议）
_ALTERNATIVES = {
    "故宫": ["国家博物馆", "景山公园", "北海公园", "雍和宫"],
    "国家博物馆": ["故宫", "首都博物馆", "中国美术馆"],
    "天坛": ["地坛公园", "先农坛", "中山公园"],
    "长城": ["慕田峪长城", "八达岭长城", "司马台长城"],
    "八达岭长城": ["慕田峪长城", "司马台长城", "居庸关"],
    "慕田峪长城": ["八达岭长城", "司马台长城", "箭扣长城"],
    "颐和园": ["圆明园", "香山公园", "玉渊潭公园"],
    "圆明园": ["颐和园", "香山公园", "北京植物园"],
    "兵马俑": ["华清池", "陕西历史博物馆", "大雁塔"],
    "华清池": ["兵马俑", "陕西历史博物馆", "骊山"],
    "大雁塔": ["陕西历史博物馆", "大唐芙蓉园", "小雁塔"],
    "西湖": ["西溪湿地", "灵隐寺", "宋城"],
    "灵隐寺": ["西湖", "飞来峰", "法喜寺"],
    "外滩": ["陆家嘴", "豫园", "上海中心观光厅"],
    "东方明珠": ["上海中心观光厅", "金茂大厦观光厅", "外滩"],
    "豫园": ["城隍庙", "外滩", "南京路步行街"],
    "拙政园": ["狮子林", "留园", "网师园"],
    "虎丘": ["拙政园", "留园", "山塘街"],
    "留园": ["拙政园", "狮子林", "虎丘"],
    "九寨沟": ["黄龙", "牟尼沟", "四姑娘山"],
    "黄龙": ["九寨沟", "牟尼沟", "松潘古城"],
    "都江堰": ["青城山", "熊猫基地", "武侯祠"],
    "青城山": ["都江堰", "熊猫基地", "街子古镇"],
    "宽窄巷子": ["锦里", "武侯祠", "杜甫草堂"],
    "武侯祠": ["锦里", "杜甫草堂", "宽窄巷子"],
    "锦里": ["武侯祠", "宽窄巷子", "杜甫草堂"],
    "鼓浪屿": ["南普陀寺", "厦门大学", "环岛路"],
    "中山陵": ["明孝陵", "灵谷寺", "美龄宫"],
    "夫子庙": ["老门东", "中华门", "玄武湖"],
    "黄山": ["宏村", "西递", "齐云山"],
    "泰山": ["岱庙", "灵岩寺", "徂徕山"],
}

# 临时关闭/维护原因
_CLOSURE_REASONS = [
    "官方临时通知闭馆",
    "设施维护",
    "特殊活动场地封闭",
    "极端天气应急关闭",
    "客流管控临时关闭",
]


class AttractionSource(BaseSource):
    """景点状态数据源"""

    name = "attraction"

    def __init__(self):
        self._client = ServiceClient(timeout=15)
        self._api_key = settings.attraction_api_key
        self._base_url = settings.attraction_base_url

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def check(self, subscription: dict) -> List[SourceResult]:
        """
        检查景点临时关闭/开放时间变更

        subscription 字段:
            attractions: 要监控的景点名称列表
            destination: 目的地城市名（可选，用于补充上下文）
        """
        attractions = subscription.get("attractions") or []
        # 兼容字符串输入（逗号分隔）
        if isinstance(attractions, str):
            attractions = [a.strip() for a in attractions.split(",") if a.strip()]
        # 去重保序
        seen = set()
        unique: List[str] = []
        for a in attractions:
            a = (a or "").strip()
            if a and a not in seen:
                seen.add(a)
                unique.append(a)
        attractions = unique

        results: List[SourceResult] = []

        if not attractions:
            logger.warning("景点状态检查缺少 attractions 参数")
            return results

        city = (subscription.get("destination") or "").strip()

        for name in attractions:
            try:
                if self._api_key:
                    info = self._fetch_real(name, city)
                else:
                    info = self._fetch_mock(name, city)

                monitor_check_counter.labels(source="attraction", status="ok").inc()

            except Exception as e:
                logger.error(f"景点数据源检查失败 ({name}): {e}")
                monitor_check_counter.labels(source="attraction", status="error").inc()
                continue

            results.extend(self._evaluate(name, info))

        return results

    # ------------------------------------------------------------------
    # 感知规则
    # ------------------------------------------------------------------
    def _evaluate(self, name: str, info: dict) -> List[SourceResult]:
        """根据景点状态生成 SourceResult"""
        status = info.get("status", "open")
        results: List[SourceResult] = []

        if status in ("closed", "maintenance"):
            wtype = "attraction_closed" if status == "closed" else "attraction_maintenance"
            alts = info.get("alternative_attractions") or _suggest_alternatives(name)
            label = "临时关闭" if status == "closed" else "维护中"
            results.append(self._make_result(
                type=wtype,
                severity="critical",
                title=f"景点关闭提醒：{name}{label}",
                message=_build_closure_message(name, info),
                suggested_action=(
                    f"建议改参观以下替代景点：{'、'.join(alts[:3])}。" if alts
                    else "请关注官方公告，及时调整当日行程安排。"
                ),
                raw_data=info,
            ))

        elif status == "hours_changed":
            results.append(self._make_result(
                type="attraction_hours_changed",
                severity="warning",
                title=f"景点开放时间变更：{name}",
                message=_build_hours_message(name, info),
                suggested_action="请根据最新开放时间调整游览计划，提前预约购票。",
                raw_data=info,
            ))

        else:  # open
            results.append(self._make_result(
                type="attraction_normal",
                severity="info",
                title=f"景点正常开放：{name}",
                message=_build_normal_message(name, info),
                raw_data=info,
            ))

        return results

    # ------------------------------------------------------------------
    # 真实 API（景点官方公告）
    # ------------------------------------------------------------------
    def _fetch_real(self, name: str, city: str) -> dict:
        """
        通过景点官方公告 API 查询实时状态

        当前无统一开放的景点公告 API，按配置的 base_url 调用；
        若调用失败或未返回有效数据，回退到 Mock。
        """
        url = f"{self._base_url}/v1/attractions/status"
        params = {"name": name, "city": city, "key": self._api_key}
        try:
            data = self._client.get(url, params=params)
        except Exception as e:
            logger.warning(f"景点公告 API 调用失败 ({name}): {e}，回退到 Mock")
            return self._fetch_mock(name, city)

        if not data or not data.get("status"):
            logger.info(f"景点公告 API 未返回有效数据 ({name})，回退到 Mock")
            return self._fetch_mock(name, city)

        open_time = data.get("open_time", "")
        close_time = data.get("close_time", "")
        return {
            "name": name,
            "city": data.get("city", city),
            "status": _normalize_status(data.get("status")),
            "open_time": open_time,
            "close_time": close_time,
            "normal_open_time": data.get("normal_open_time", open_time),
            "normal_close_time": data.get("normal_close_time", close_time),
            "closure_reason": data.get("closure_reason", ""),
            "announcement": data.get("announcement", ""),
            "alternative_attractions": data.get("alternative_attractions", []),
            "mock": False,
        }

    # ------------------------------------------------------------------
    # Mock 模式
    # ------------------------------------------------------------------
    def _fetch_mock(self, name: str, city: str) -> dict:
        """生成模拟景点状态数据"""
        open_time, close_time = _default_hours(name)

        # 状态分布：85% 正常开放, 6% 临时关闭, 4% 维护, 5% 开放时间变更
        roll = random.random()
        if roll < 0.85:
            status = "open"
        elif roll < 0.91:
            status = "closed"
        elif roll < 0.95:
            status = "maintenance"
        else:
            status = "hours_changed"

        info: dict = {
            "name": name,
            "city": city,
            "status": status,
            "open_time": open_time,
            "close_time": close_time,
            "normal_open_time": open_time,
            "normal_close_time": close_time,
            "closure_reason": "",
            "announcement": "",
            "alternative_attractions": _suggest_alternatives(name),
            "mock": True,
        }

        if status in ("closed", "maintenance"):
            info["closure_reason"] = random.choice(_CLOSURE_REASONS)
            info["announcement"] = (
                f"{name}因{info['closure_reason']}，即日起临时闭园，恢复时间另行通知。"
            )
        elif status == "hours_changed":
            new_open, new_close = _adjust_hours(open_time, close_time)
            info["open_time"] = new_open
            info["close_time"] = new_close
            info["announcement"] = (
                f"{name}今日开放时间调整为 {new_open}-{new_close}，"
                f"原定 {open_time}-{close_time}。"
            )

        return info


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------
def _normalize_status(raw: str) -> str:
    """将 API 返回的状态归一化为内部状态"""
    raw = (raw or "").lower()
    if "clos" in raw:            # close / closed / closure
        return "closed"
    if "maint" in raw:          # maintain / maintenance
        return "maintenance"
    if "hour" in raw or "change" in raw:
        return "hours_changed"
    return "open"


def _suggest_alternatives(name: str) -> List[str]:
    """根据景点名称推荐替代景点"""
    if name in _ALTERNATIVES:
        return _ALTERNATIVES[name]
    # 模糊匹配（如"北京故宫博物院"包含"故宫"）
    for key, alts in _ALTERNATIVES.items():
        if key in name or name in key:
            return alts
    return []


def _default_hours(name: str):
    """默认开放时间 (open_time, close_time)"""
    # 博物馆类：9:00-17:00
    if any(k in name for k in ("博物馆", "博物院", "纪念馆", "美术馆")):
        return "09:00", "17:00"
    # 公园类：6:30-21:00
    if any(k in name for k in ("公园", "植物园", "湿地")):
        return "06:30", "21:00"
    # 默认景区：8:30-17:30
    return "08:30", "17:30"


def _adjust_hours(open_time: str, close_time: str):
    """生成调整后的开放时间"""
    oh, om = _parse_hm(open_time, 8, 30)
    ch, cm = _parse_hm(close_time, 17, 30)
    # 开放时间推迟 1-2 小时
    new_oh = (oh + random.choice([1, 2])) % 24
    # 关闭时间提前或延后 1 小时
    new_ch = (ch + random.choice([-1, 1])) % 24
    return f"{new_oh:02d}:{om:02d}", f"{new_ch:02d}:{cm:02d}"


def _parse_hm(text: str, default_h: int, default_m: int):
    """解析 HH:MM 字符串，失败则用默认值"""
    try:
        h, m = text.split(":")
        return int(h), int(m)
    except Exception:
        return default_h, default_m


def _build_closure_message(name: str, info: dict) -> str:
    """构造景点关闭提醒文案"""
    reason = info.get("closure_reason", "临时关闭")
    label = "临时关闭" if info.get("status") == "closed" else "维护中"
    base = f"您关注的景点 {name} 当前{label}（{reason}），可能影响您的游览计划。"
    announcement = info.get("announcement", "")
    if announcement:
        base += f" 官方公告：{announcement}"
    return base


def _build_hours_message(name: str, info: dict) -> str:
    """构造开放时间变更提醒文案"""
    return (
        f"您关注的景点 {name} 今日开放时间调整为 "
        f"{info.get('open_time', '?')}-{info.get('close_time', '?')}，"
        f"原定 {info.get('normal_open_time', '?')}-{info.get('normal_close_time', '?')}。"
    )


def _build_normal_message(name: str, info: dict) -> str:
    """构造正常开放文案"""
    return (
        f"{name} 当前正常开放，开放时间 "
        f"{info.get('open_time', '?')}-{info.get('close_time', '?')}。"
    )
