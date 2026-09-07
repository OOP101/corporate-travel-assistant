"""
感知 · Sense Engine —— FastAPI 服务入口

AI出行管家 实时感知引擎，端口 8003

API:
  GET  /health               → 健康检查
  GET  /metrics              → Prometheus 指标
  GET  /trips/{trip_id}/alerts → 获取行程关联的提醒
  POST /monitor/subscribe    → 为行程订阅监控
  GET  /monitor/status       → 监控任务运行状态
  DELETE /monitor/{trip_id}  → 取消订阅
  POST /monitor/check        → 手动触发一次全量检查
  POST /query                → 按需直查实时数据（天气/航班/铁路），不等监控订阅
"""
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.logging_config import setup_logging
from shared.config import settings
from shared.middleware import api_key_auth
from shared.middleware.app_factory import create_app

from alerts.manager import AlertManager
from engine import SenseEngine
from sources.weather import WeatherSource
from sources.flight import FlightSource
from sources.train import TrainSource

logger = logging.getLogger("sense-engine")


# ---------------------------------------------------------------------------
# 全局服务实例
# ---------------------------------------------------------------------------
engine: Optional[SenseEngine] = None
alert_manager: Optional[AlertManager] = None


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------
class SubscribeRequest(BaseModel):
    """订阅监控请求"""
    trip_id: str = Field(..., description="行程 ID")
    user_id: str = Field(default="default", description="用户 ID")
    flight_number: str = Field(default="", description="航班号，如 CA1234")
    train_code: str = Field(default="", description="车次，如 G102（铁路 12306 监控）")
    train_from: str = Field(default="", description="出发车站，如 广州南")
    train_to: str = Field(default="", description="到达车站，如 北京西")
    train_date: str = Field(default="", description="乘车日期 YYYY-MM-DD")
    destination: str = Field(default="", description="目的地城市")
    origin: str = Field(default="", description="出发地城市（路况检查需要）")
    check_weather: bool = Field(default=True, description="是否检查天气")
    check_traffic: bool = Field(default=False, description="是否检查路况")
    check_attractions: bool = Field(default=True, description="是否检查景点状态")
    attractions: list = Field(default=[], description="要监控的景点名称列表")


class QueryRequest(BaseModel):
    """按需直查实时数据请求（问答路径调用，不等监控订阅）"""
    type: str = Field(..., description="查询类型：weather | flight | train")
    city: Optional[str] = Field(default="", description="天气查询城市（weather 用）")
    flight_number: Optional[str] = Field(default="", description="航班号（flight 用）")
    origin: Optional[str] = Field(default="", description="出发城市（flight 用）")
    destination: Optional[str] = Field(default="", description="到达城市（flight 用）")
    train_code: Optional[str] = Field(default="", description="车次（train 用）")
    train_from: Optional[str] = Field(default="", description="出发站（train 用）")
    train_to: Optional[str] = Field(default="", description="到达站（train 用）")
    train_date: Optional[str] = Field(default="", description="乘车日期 YYYY-MM-DD（train 用）")


class SubscribeResponse(BaseModel):
    status: str = "ok"
    trip_id: str
    sources: list = []


class CheckResponse(BaseModel):
    status: str = "ok"
    subscriptions_checked: int = 0
    new_alerts: int = 0
    alerts: list = []


# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, alert_manager

    setup_logging(
        level=settings.log_level,
        service="sense-engine",
        use_json=settings.log_json,
    )

    # 注册开发用 API Key
    api_key_auth.register_workspace("default", settings.dev_api_key)

    # 初始化提醒管理器与感知引擎
    alert_manager = AlertManager()
    engine = SenseEngine(alert_manager=alert_manager)
    engine.start()

    logger.info("感知·Sense Engine 已启动 (port 8003)")
    yield
    engine.stop()
    logger.info("感知·Sense Engine 已关闭")


# ---------------------------------------------------------------------------
# FastAPI 应用（使用共享工厂）
# ---------------------------------------------------------------------------
app = create_app(
    title="感知 · Sense Engine",
    description="AI出行管家 实时感知引擎 —— 航班/天气/路况/景点监控",
    lifespan=lifespan,
    tags=[
        {"name": "行程提醒", "description": "获取行程关联的提醒列表"},
        {"name": "监控管理", "description": "订阅/取消/状态查询/手动检查"},
        {"name": "系统", "description": "健康检查、Prometheus 指标"},
    ],
)


# ---------------------------------------------------------------------------
# 提醒查询
# ---------------------------------------------------------------------------
@app.get("/trips/{trip_id}/alerts", tags=["行程提醒"])
async def get_trip_alerts(trip_id: str, undelivered: bool = False):
    """获取行程关联的提醒列表"""
    if not alert_manager:
        raise HTTPException(503, "提醒管理器未就绪")

    if undelivered:
        alerts = alert_manager.get_undelivered(trip_id)
    else:
        alerts = alert_manager.get_by_trip(trip_id)

    return {"trip_id": trip_id, "count": len(alerts), "alerts": alerts}


# ---------------------------------------------------------------------------
# 监控订阅
# ---------------------------------------------------------------------------
@app.post("/monitor/subscribe", response_model=SubscribeResponse, tags=["监控管理"])
async def subscribe_monitor(req: SubscribeRequest):
    """为行程订阅监控"""
    if not engine:
        raise HTTPException(503, "感知引擎未就绪")

    subscription = {
        "trip_id": req.trip_id,
        "user_id": req.user_id,
        "flight_number": req.flight_number,
        "train_code": req.train_code,
        "train_from": req.train_from,
        "train_to": req.train_to,
        "train_date": req.train_date,
        "destination": req.destination,
        "origin": req.origin,
        "check_weather": req.check_weather,
        "check_traffic": req.check_traffic,
        "check_attractions": req.check_attractions,
        "attractions": list(req.attractions or []),
    }

    # 确定该订阅会激活哪些数据源
    active = []
    if req.flight_number:
        active.append("flight")
    if req.train_code:
        active.append("train")
    if req.check_weather and req.destination:
        active.append("weather")
    if req.check_traffic and req.origin and req.destination:
        active.append("traffic")
    if req.check_attractions and req.attractions:
        active.append("attraction")

    engine.subscribe(req.trip_id, subscription)

    logger.info(f"订阅成功: trip={req.trip_id}, sources={active}")
    return SubscribeResponse(trip_id=req.trip_id, sources=active)


@app.get("/monitor/status", tags=["监控管理"])
async def monitor_status():
    """监控任务运行状态"""
    if not engine:
        raise HTTPException(503, "感知引擎未就绪")

    subs = engine.get_subscriptions()
    return {
        "status": "running",
        "subscription_count": len(subs),
        "subscriptions": [
            {
                "trip_id": tid,
                "flight_number": sub.get("flight_number", ""),
                "destination": sub.get("destination", ""),
                "check_weather": sub.get("check_weather", False),
                "check_traffic": sub.get("check_traffic", False),
                "check_attractions": sub.get("check_attractions", False),
                "attractions": sub.get("attractions", []),
            }
            for tid, sub in subs.items()
        ],
        "active_sources": engine.active_sources,
        "total_alerts": alert_manager.all_count() if alert_manager else 0,
    }


@app.delete("/monitor/{trip_id}", tags=["监控管理"])
async def unsubscribe_monitor(trip_id: str):
    """取消行程的监控订阅"""
    if not engine:
        raise HTTPException(503, "感知引擎未就绪")

    removed = engine.unsubscribe(trip_id)
    if not removed:
        raise HTTPException(404, f"行程 {trip_id} 无订阅")

    # 同时清除该行程的提醒
    cleared = alert_manager.clear(trip_id) if alert_manager else 0

    return {"status": "ok", "trip_id": trip_id, "alerts_cleared": cleared}


@app.post("/monitor/check", response_model=CheckResponse, tags=["监控管理"])
async def manual_check():
    """手动触发一次全量检查"""
    if not engine:
        raise HTTPException(503, "感知引擎未就绪")

    alerts = engine.check_all()

    return CheckResponse(
        subscriptions_checked=engine.subscription_count,
        new_alerts=len(alerts),
        alerts=[a.to_dict() for a in alerts],
    )


@app.post("/query", tags=["实时直查"])
async def query_source(req: QueryRequest):
    """按需直查实时数据（问答路径调用，不等监控订阅）。

    支持 weather / flight / train；失败统一降级为 Mock 或返回错误。
    """
    if not engine:
        raise HTTPException(503, "感知引擎未就绪")

    try:
        if req.type == "weather":
            data = WeatherSource().query(req.city or req.destination or "")
        elif req.type == "flight":
            data = FlightSource().query(req.flight_number or "", req.origin or "", req.destination or "")
        elif req.type == "train":
            data = TrainSource().query(req.train_code or "", req.train_from or "", req.train_to or "", req.train_date or "")
        else:
            raise HTTPException(400, f"不支持的查询类型: {req.type}")
        return {"type": req.type, "data": data}
    except HTTPException:
        raise
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except Exception as e:
        logger.error(f"实时直查失败 ({req.type}): {e}")
        raise HTTPException(502, f"实时直查失败: {e}")


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.sense_host,
        port=settings.sense_port,
        reload=False,
    )
