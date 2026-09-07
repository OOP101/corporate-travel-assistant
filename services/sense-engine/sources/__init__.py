"""
感知数据源模块 —— 多源实时采集

支持：航班状态、天气预报、路况信息、景点状态、铁路 12306 车票
"""
from .base import BaseSource, SourceResult
from .flight import FlightSource
from .weather import WeatherSource
from .traffic import TrafficSource
from .attraction import AttractionSource
from .train import TrainSource

__all__ = [
    "BaseSource",
    "SourceResult",
    "FlightSource",
    "WeatherSource",
    "TrafficSource",
    "AttractionSource",
    "TrainSource",
]
