"""
铁路数据源 —— 12306 车票状态实时感知

模式：
  - 真实模式：查询 12306 余票接口（无需 Key），获取车次当日运行/余票状态
  - Mock 模式：12306 查询失败（反爬/网络）时自动降级，保证演示链路完整

感知规则：
  - 车次停运/取消 → critical
  - 无票（需候补）→ warning
  - 有票 → info
"""
import json
import logging
import random
import re
import time
from typing import List, Optional

import requests

from shared.metrics import monitor_check_counter

from .base import BaseSource, SourceResult

logger = logging.getLogger("sense-engine.sources.train")

# 常用车站电报码（避免每次拉站名表；未命中再查 12306 站名表）
_STATION_TELECODE = {
    "北京": "BJP", "北京西": "BXP", "北京南": "VNP", "北京丰台": "BFP",
    "上海": "SHH", "上海虹桥": "AOH", "上海南": "SNH",
    "广州": "GZQ", "广州南": "IZQ", "深圳": "SZQ", "深圳北": "IOQ",
    "成都": "CDW", "成都东": "ICW", "杭州": "HZH", "杭州东": "HGH",
    "西安": "XAY", "西安北": "EAY", "重庆": "CQW", "重庆北": "CUW",
    "武汉": "WHN", "汉口": "HKN", "南京": "NJH", "南京南": "NKD",
    "天津": "TJP", "长沙": "CSQ", "长沙南": "CDQ", "郑州": "ZZF", "郑州东": "ZDF",
}

_QUERY_URL = "https://kyfw.12306.cn/otn/leftTicket/queryU"
_STATION_URL = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
}


class TrainSource(BaseSource):
    """铁路 12306 数据源"""

    name = "train"

    def __init__(self):
        self._station_table: Optional[dict] = None  # 站名 → 电报码缓存

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def check(self, subscription: dict) -> List[SourceResult]:
        """
        检查车票状态

        subscription 字段:
            train_code: 车次（如 "G102"），必填（本源触发条件）
            train_from: 出发站名（如 "广州南"）
            train_to: 到达站名（如 "北京西"）
            train_date: 乘车日期 YYYY-MM-DD
        """
        train_code = (subscription.get("train_code") or "").strip().upper()
        if not train_code:
            return []

        train_from = (subscription.get("train_from") or "").strip()
        train_to = (subscription.get("train_to") or "").strip()
        train_date = (subscription.get("train_date") or "").strip()

        status = None
        try:
            status = self._fetch_real(train_code, train_from, train_to, train_date)
        except Exception as e:
            logger.warning(f"12306 查询失败，降级 Mock: {e}")

        if status is None:
            status = self._fetch_mock(train_code, train_from, train_to, train_date)

        monitor_check_counter.labels(source=self.name, status=status["status"]).inc()
        return [self._build_result(train_code, train_from, train_to, train_date, status)]

    # ------------------------------------------------------------------
    # 按需直查（问答路径调用，不等监控订阅）
    # ------------------------------------------------------------------
    def query(self, train_code: str, train_from: str = "", train_to: str = "", train_date: str = "") -> dict:
        """
        按需查询车次状态（直查工具，复用 12306 采集逻辑）。

        Args:
            train_code: 车次（如 "G102"）
            train_from / train_to: 出发/到达站名
            train_date: 乘车日期 YYYY-MM-DD
        Returns:
            状态 dict（含 source / mock / degraded 标记）
        """
        train_code = (train_code or "").strip().upper()
        if not train_code:
            return {"source": "train", "status": "unknown", "detail": "缺少车次", "mock": False}
        try:
            status = self._fetch_real(train_code, train_from, train_to, train_date)
            if status is None:
                status = self._fetch_mock(train_code, train_from, train_to, train_date)
            status["source"] = "train"
            return status
        except Exception as e:
            logger.warning(f"铁路直查失败 ({train_code})，降级 Mock: {e}")
            status = self._fetch_mock(train_code, train_from, train_to, train_date)
            status["source"] = "train"
            status["degraded"] = True
            return status

    # ------------------------------------------------------------------
    # 真实查询（12306 余票接口，无需 Key）
    # ------------------------------------------------------------------
    def _fetch_real(self, train_code, train_from, train_to, train_date) -> Optional[dict]:
        """查询 12306；返回 {"status": "normal|soldout|cancelled", "detail": str}，失败返回 None"""
        if not (train_from and train_to and train_date):
            return None

        from_code = self._telecode(train_from)
        to_code = self._telecode(train_to)
        if not from_code or not to_code:
            return None

        session = requests.Session()
        session.headers.update(_HEADERS)
        # 先访问查询页拿 Cookie，12306 对无 Cookie 请求常直接拒绝
        session.get("https://kyfw.12306.cn/otn/leftTicket/init", timeout=10)

        resp = session.get(
            _QUERY_URL,
            params={
                "leftTicketDTO.train_date": train_date,
                "leftTicketDTO.from_station": from_code,
                "leftTicketDTO.to_station": to_code,
                "purpose_codes": "ADULT",
            },
            timeout=15,
        )
        # 12306 响应带 UTF-8 BOM，且反爬时返回 HTML 页面而非 JSON
        text = resp.content.decode("utf-8-sig", errors="replace")
        if not text.lstrip().startswith("{"):
            raise RuntimeError("12306 返回非 JSON（疑似反爬拦截），降级模拟数据")
        data = json.loads(text)
        rows = (data.get("data") or {}).get("result") or []

        target = None
        for row in rows:
            cols = row.split("|")
            if len(cols) > 11 and cols[3] == train_code:
                target = cols
                break

        if target is None:
            # 查无此车：当日停运或未开行
            return {"status": "cancelled", "detail": "12306 余票列表中未查到该车次（当日停运或未开行）"}

        remark = target[1] or ""
        if "停运" in remark:
            return {"status": "cancelled", "detail": f"12306 备注：{remark}"}

        # 余票字段：二等座 31 / 一等座 30 / 硬卧 28 / 硬座 29，任一有票即视为有票
        def _ticket(idx):
            if idx >= len(target):
                return ""
            v = target[idx].strip()
            return "" if v in ("", "无", "--") else v

        available = any(_ticket(i) for i in (31, 30, 29, 28))
        if not available:
            bookable = target[11] if len(target) > 11 else ""
            if bookable == "Y" or "候补" in remark:
                return {"status": "soldout", "detail": "各席别无票，可候补"}
            return {"status": "soldout", "detail": "各席别无票"}

        return {"status": "normal", "detail": "有余票"}

    def _telecode(self, station: str) -> Optional[str]:
        """站名 → 12306 电报码；内置常用站，其余查站名表（带缓存）"""
        if station in _STATION_TELECODE:
            return _STATION_TELECODE[station]
        if self._station_table is None:
            self._station_table = self._load_station_table()
        return (self._station_table or {}).get(station)

    @staticmethod
    def _load_station_table() -> Optional[dict]:
        try:
            resp = requests.get(_STATION_URL, headers=_HEADERS, timeout=10)
            resp.encoding = "utf-8"
            # 格式：@bjb|北京北|VAP|beijingbei|bjb|0|...  第3段为电报码
            table = {}
            for m in re.finditer(r"@[^@]+", resp.text):
                parts = m.group(0).strip("@").split("|")
                if len(parts) >= 3:
                    table[parts[1]] = parts[2]
            return table or None
        except Exception as e:
            logger.warning(f"12306 站名表拉取失败: {e}")
            return None

    # ------------------------------------------------------------------
    # Mock 降级
    # ------------------------------------------------------------------
    def _fetch_mock(self, train_code, train_from, train_to, train_date) -> dict:
        """模拟车票状态：按 30 分钟时间窗与车次确定性随机，演示时状态会缓慢演变"""
        slot = int(time.time() // 1800)
        seed = f"{train_code}|{train_date}|{slot}"
        roll = random.Random(seed).random()

        if roll < 0.08:
            return {"status": "cancelled", "detail": "（模拟数据）铁路部门通知该车次临时停运"}
        if roll < 0.28:
            return {"status": "soldout", "detail": "（模拟数据）各席别无票，建议候补或改签"}
        return {"status": "normal", "detail": "（模拟数据）各席别有余票"}

    # ------------------------------------------------------------------
    # 结果构造
    # ------------------------------------------------------------------
    def _build_result(self, code, frm, to, date, status: dict) -> SourceResult:
        route = f"{frm or '?'} → {to or '?'}"
        label_date = f"（{date}）" if date else ""
        if status["status"] == "cancelled":
            return self._make_result(
                type="train_cancel",
                severity="critical",
                title=f"🚄 {code} 次列车停运",
                message=f"车次 {code}（{route}）{label_date}停运/取消：{status['detail']}",
                suggested_action="请改签其他车次或调整行程，联系差旅负责人员",
                raw_data={"train_code": code, "status": "cancelled"},
            )
        if status["status"] == "soldout":
            return self._make_result(
                type="train_soldout",
                severity="warning",
                title=f"🚄 {code} 次列车无票",
                message=f"车次 {code}（{route}）{label_date}车票售罄：{status['detail']}",
                suggested_action="尽快提交候补订单，或改签邻近车次",
                raw_data={"train_code": code, "status": "soldout"},
            )
        return self._make_result(
            type="train_normal",
            severity="info",
            title=f"🚄 {code} 次列车正常",
            message=f"车次 {code}（{route}）{label_date}运行正常，{status['detail']}",
            suggested_action="",
            raw_data={"train_code": code, "status": "normal"},
        )
