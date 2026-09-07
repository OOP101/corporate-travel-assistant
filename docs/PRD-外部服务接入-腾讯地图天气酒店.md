# PRD 补充章 · 外部服务接入（腾讯地图 / 和风天气 / 酒店 POI）

> 配套：PRD-行程规划对话流程-v2.md（流程篇）。本篇解决"规划链路完全不消费任何外部实时/地理/预订服务"的缺口。
> 决策来源（2026-08-27 用户拍板三项全做 + 提供真实 key；2026-09-03 起地图供应商由高德切换为**腾讯位置服务**）：用户提供腾讯地图 key + SecretKey(SK) + 和风天气真实 key；酒店走腾讯地图 POI 结构化候选（携程/美团开放 API 为合作伙伴白名单，个人/小团队拿不到，不纳入）。

## 1. 现状（已核实）

| 能力 | 配置 | 真实代码 | 现接链路 | 实际效果 |
|---|---|---|---|---|
| 腾讯地图（地理编码/路线） | `TENCENT_MAP_KEY=` + `TENCENT_MAP_SK=` 空 | `shared/geo/tencent_client.py`（planner 与 sense-engine 共用） | 规划链路 enrich + 监控路况 | key 空→走降级（None/mock）；填 key 后真实调用 |
| 天气 | `WEATHER_API_KEY=` 空 | `shared/geo/qweather_client.py` + `sense-engine/sources/weather.py` | 规划链路 enrich + 监控 + 问答 | 规划时调用；key 空→问答也是 mock |
| 酒店/美团/携程 | 无 | 零 API 集成（仅腾讯地图 POI 候选） | 无 | 房型/价格/余量均为 LLM 编造 |

根因（已修复）：实时数据曾被设计成 sense-engine 的「感知/监控 + 问答直查」，与 planner-core 纯生成模块未打通；现 `shared/geo` 作为共用客户端，planner 在 **extract 之后、LLM 生成之前** enrich，并注入提示词与行程单。

## 2. 目标

规划（plan）链路在**提取参数之后、LLM 生成之前**消费三类外部数据，并注入生成提示词与行程单：

- **地理编码**：出发地/目的地 → 经纬度（WGS84），为路线与 POI 提供坐标。
- **路线规划**：出发地→目的地驾车距离/时长，写入行程单 `route`。
- **天气**：目的地逐日预报（和风 `v7/weather/7d`），作为生成约束（恶劣天气日避让户外）。
- **酒店候选**：目的地周边酒店 POI（腾讯地图 `ws/place/v1/search`，boundary=nearby），结构化候选注入住宿安排。

## 3. 架构

```
用户需求
  └─ planner-core /trips/generate
       ├─ _extract_params (LLM)            → destination/origin/start_date/days
       ├─ _enrich_external (新增, 同步)     → 调 shared.geo
       │     ├─ TencentMapClient.geocode(origin/destination)
       │     ├─ TencentMapClient.driving_route(origin_geo, dest_geo)
       │     ├─ QWeatherClient.forecast_7d(destination)
       │     └─ TencentMapClient.poi_hotels(destination)
       ├─ _build_generation_prompt(params, ext)  → 把 ext 注入提示词约束
       ├─ llm.chat_stream                  → 行程 JSON
       └─ _parse_trip_text + _attach_external  → trip_dict 挂 geo/route/weather_forecast/hotel_options
```

`shared/geo`（planner 与 sense-engine 共用）：
- `TencentMapClient`：geocode / driving_route / poi_hotels。key 空→返回 `None`。**开启 SN 校验时需 SecretKey(SK) 做 md5 签名**，签名规则 `sig=md5(请求路径?按参数名升序拼接的原始参数+SK)`，sig 作为额外参数传入；SK 缺失时自动跳过签名（适用于未开启 SN 校验的 key）。
- `QWeatherClient`：forecast_7d。key 空→返回 `None`。
- 任意外部调用失败一律 `except → None`，**绝不阻断生成**。

降级原则（关键，避免再次"编造"）：
- **有 key + 调用成功** → 注入真实数据到提示词与行程单，并在行程单标注数据来源。
- **无 key 或调用失败** → 不注入任何假天气/假酒店到提示词（仅附注"实时数据未接入"），行程单对应字段为 `null`/`[]`，前端明确显示"未接入"。

## 4. 各能力规格

### 4.1 腾讯位置服务（TencentMapClient）
- 域名 `https://apis.map.qq.com`，需 `key` + （SN 校验时）`SecretKey(SK)` 签名。
- `geocode(address) -> {"lng","lat","address"} | None`：端点 `/ws/geocoder/v1`，返回 `result.location.lat/lng` 与 `title`。
- `driving_route(origin_geo, dest_geo) -> {"distance_km","duration_min"} | None`：端点 `/ws/direction/v1/driving`，`from/to` 格式为 `lat,lng`（**与高德 lng,lat 相反**），返回 `result.routes[0].distance`(米)/`duration`(秒)。
- `poi_hotels(city=None, geo=None, keyword="酒店", limit=6) -> [{name,address,tel,type,lng,lat}] | None`：端点 `/ws/place/v1/search`，`boundary=nearby(lat,lng,5000)`（有坐标时）或 `region(城市,0)`，`page_size=limit`，返回 `data[]`（title/address/location.lat-lng）。

### 4.2 和风天气（QWeatherClient）
- `forecast_7d(location) -> [{date,cond_day,cond_night,temp_max,temp_min,precip,wind_day}] | None`：先 `geo/v2/city/lookup` 取 city_id，再 `v7/weather/7d`。
- 生成约束：逐日 `cond_day` 含 暴雨/台风/雷阵雨/大雪 → 当日避免户外景点，改室内备选；`temp_max>=35` 或 `temp_min<=0` → tips 提示防暑/保暖。

### 4.3 酒店结构化候选
- 仅腾讯地图 POI 结构化候选（名称/地址/电话/坐标），**非实时报价/余量**。
- 生成约束：住宿优先从候选选，标注「推荐酒店」；明确不承诺价格与可订性。

## 5. 注入点（代码落点）

- 新增：`shared/geo/__init__.py`、`shared/geo/tencent_client.py`、`shared/geo/qweather_client.py`
- 修改：`services/planner-core/generators/itinerary.py`
  - `generate()` / `generate_stream()`：extract 后调 `_enrich_external(params)`，生成后 `_attach_external(trip_dict, ext)`。
  - `_build_generation_prompt(params, query, preferences, ext=None)`：追加 `_external_prompt_block(ext, params)`。
  - 新增 `_enrich_external` / `_external_prompt_block` / `_attach_external` / `_empty_ext`。
  - `_demo_generate` 返回也经 `_attach_external` 挂空占位，保证结构一致。
- 修改：`services/sense-engine/sources/traffic.py`：原高德调用改为复用 `shared.geo.TencentMapClient`（geocode + driving_route），拥堵等级由「实际时长/自由流时长」启发式估算；key 空→mock。
- 配置：`shared/config/settings.py` 新增 `tencent_map_key`(env `TENCENT_MAP_KEY`) 与 `tencent_map_sk`(env `TENCENT_MAP_SK`)，移除 `amap_api_key`；`.env` 与 `docker-compose.yml` 同步替换。
- 落库字段（trip dict 增量，不改 Trip dataclass）：`geo`、`route`、`weather_forecast`、`hotel_options`、`external_data.real`。

## 6. 验收

- U-E1：`.env` 填 `TENCENT_MAP_KEY`/`TENCENT_MAP_SK`/`WEATHER_API_KEY` 后，规划一次真实目的地，行程单 `geo` 含经纬度、`weather_forecast` 为真实逐日、`hotel_options` 为真实候选，`external_data.real=true`。
- U-E2：key 为空时，规划不报错、不注入假数据，`external_data.real=false`，前端显"实时数据未接入"。
- U-E3：腾讯/和风服务不可达或 key 非法时，规划仍成功（ext 全 None），不抛异常、不混入错误 JSON。
- U-E4：恶劣天气日（如预报暴雨）生成的行程不含户外景点（人工/用例核验提示词约束生效）。
- U-E5：任一外部调用超时（>15s）被客户端截断，不拖垮整体生成。

## 7. 不在本期

- 携程/美团/聚合酒店 API 真实预订（白名单/商务合作门槛）。
- 前端行程详情页天气徽标/酒店候选展示（任务 #22，结构先落库）。
- 腾讯地图驾车路线的逐段实时拥堵指数（需额外 traffic 参数；当前用时长比启发式估算，见 §5 traffic.py）。
