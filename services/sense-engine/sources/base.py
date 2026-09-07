"""
数据源基类 —— 统一的数据采集抽象

所有具体数据源（航班、天气、路况）均继承 BaseSource，
实现 check() 方法返回 SourceResult 列表。
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("sense-engine.sources")


@dataclass
class SourceResult:
    """单次数据源检查结果"""

    source: str = ""               # flight | weather | traffic
    type: str = ""                 # flight_delay | weather_warning | traffic_jam ...
    severity: str = "info"         # info | warning | critical
    title: str = ""
    message: str = ""
    suggested_action: str = ""
    raw_data: dict = field(default_factory=dict)
    changed: bool = False          # 是否为相对上次的变更


class BaseSource(ABC):
    """
    数据源基类

    子类需实现 check() 方法，从订阅信息中提取所需参数，
    采集最新数据并返回 SourceResult 列表。
    """

    name: str = "base"

    @abstractmethod
    def check(self, subscription: dict) -> List[SourceResult]:
        """
        检查数据源，返回感知结果列表

        Args:
            subscription: 订阅信息字典，包含行程相关的采集参数

        Returns:
            SourceResult 列表（可能为空）
        """
        ...

    def query(self, **kwargs) -> dict:
        """
        一次性直查（按需拉取，不等监控订阅）。

        子类按需实现；默认抛 NotImplementedError，
        表示本源不支持按需直查。
        """
        raise NotImplementedError(f"{self.name} 不支持按需直查")

    def _make_result(
        self,
        type: str,
        severity: str,
        title: str,
        message: str,
        suggested_action: str = "",
        raw_data: Optional[dict] = None,
    ) -> SourceResult:
        """构造 SourceResult 的便捷方法"""
        return SourceResult(
            source=self.name,
            type=type,
            severity=severity,
            title=title,
            message=message,
            suggested_action=suggested_action,
            raw_data=raw_data or {},
            changed=False,
        )
