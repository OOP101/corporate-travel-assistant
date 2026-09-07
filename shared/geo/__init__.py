"""共享地理/天气客户端（planner 与 sense-engine 共用）。

腾讯位置服务（地理编码 / 驾车路线 / POI 酒店候选）+ 和风天气（逐日预报）。
API Key 未配置或调用失败时一律返回 None，由调用方决定是否走 mock 兜底，
绝不抛出异常阻断主流程。
"""
from .tencent_client import TencentMapClient
from .qweather_client import QWeatherClient

__all__ = ["TencentMapClient", "QWeatherClient"]
