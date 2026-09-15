# 企业智行 · Corporate Journey Hub

> 面向企业内部的智能行程规划与安排平台，以 LLM 为大脑、以多源实时数据为感知，覆盖「行前规划 → 行中保障 → 行后归档」全链路，服务于员工差旅、客户拜访、会议参展、团队出行等企业内部行程场景。

---

## 📸 界面预览

| 智能助手（行智 · Journey Hub） | 差旅行程（策程 · Planner Core） | 实时监控（感知 · Sense Engine） |
|:---:|:---:|:---:|
| ![智能助手](docs/screenshots/workbench.png) | ![差旅行程](docs/screenshots/trips.png) | ![实时监控](docs/screenshots/alerts.png) |

---

## 一、项目概述

企业智行是一个面向**企业内部行程规划与安排**的多 Agent 协作平台，业务上分为「Agent 编排 → 行程规划 → 实时感知」三层，由三个松耦合服务承载，帮助企业将分散在邮件、IM、Excel 中的行程安排统一为一个智能入口。

| 服务 | 代号 | 定位 | 单体模式 | 微服务模式 |
|:---|:---|:---|:---|:---|
| **行智 · Journey Hub** | `journey-hub` | Agent 编排中心 | `/`（8001） | 8001 |
| **策程 · Planner Core** | `planner-core` | 行程规划引擎 | `/planner`（8001） | 8002 |
| **感知 · Sense Engine** | `sense-engine` | 实时感知引擎 | `/sense`（8001） | 8003 |

三个服务通过 REST API 和 SSE 协同工作，共享平台复用层（`shared/`），零重复代码。

**两种运行模式，一套代码**（`launcher.py start [single|micro]`，默认 single）：

- **单体模式（默认，日常推荐）**：`services/gateway` 把三个服务的 FastAPI app 装配进**同一个进程、同一个端口 8001**——一个进程、一个总控台、一份日志，启动更快、排查更简单；服务之间仍走 HTTP（`/planner`、`/sense` 前缀），编排逻辑零改动。
- **微服务模式（架构演示 / 单服务调试）**：三个服务各自独立进程占 8001/8002/8003，可单独重启、独立扩缩容。

---

## 二、架构分层

```
                    ┌──────────────────────────────┐
   前端工作台 3001  │  统一网关 (8001) · 单体模式    │
   ─────────────────▶  /        行智 Journey Hub    │
                    │  /planner 策程 Planner Core   │
                    │  /sense   感知 Sense Engine   │
                    └──────────────────────────────┘
       微服务模式则在 8001 / 8002 / 8003 上分别独立运行
```

**调用链路**：
- 员工消息 → 行智意图路由 → 策程规划 / 行智问答 / 策程管理 → 回复员工
- 感知引擎定时监控 → 变更检测 → 生成提醒 → 推送通知

---

## 三、核心能力

### 3.1 行前规划
- **一句话生成行程**：自然语言描述 → 结构化行程（含交通、住宿、会议、拜访、餐饮）
- **企业场景适配**：商务出差 / 客户拜访 / 会议参展 / 团队出行多场景自适应
- **出行清单**：根据目的地气候和行程类型自动生成，含证件与公司材料提醒
- **预算预估**：按行程项预估费用，辅助差旅预算申报

### 3.2 行中保障
- **实时感知**：航班延误 / 天气预警 / 路况拥堵主动推送
- **智能问答**：行程相关问题多轮对话（交通、地点、流程）
- **应变重排**：突发情况（延误、闭馆、改期）自动调整后续行程

### 3.3 行后归档
- **行程总结**：概览 + 每日回顾 + 偏差分析 + 花费统计
- **费用统计**：分类费用明细，对齐报销口径，支持导出
- **复用模板**：常用差旅线路（如固定客户拜访路线）一键复用

---

## 四、快速开始

### 4.1 环境要求

- Python 3.10+
- Node.js 18+（前端）
- Docker（可选，用于容器化部署）

### 4.2 后端启动（无需 Docker）

### 4.2 一键启动（推荐）

双击 `start.bat`（或 `CorporateJourneyHub.exe`），或命令行：

```bash
python launcher.py                 # 一键启动（默认单体模式：单进程单端口 8001）→ 自动开工作台，窗口自动关闭
python launcher.py micro           # 以微服务模式启动（8001/8002/8003 三进程）
python launcher.py menu            # 常驻总控台（状态面板 + 启动/停止/重启/日志/清空数据一体化）
python launcher.py stop            # 停止全部服务（含前端；覆盖两种模式端口，先优雅后强杀）
python launcher.py restart         # 重启（当前模式）
python launcher.py status          # 查看服务状态（并行探活，秒级返回）
python launcher.py start micro     # 指定模式启动：start single|micro
python launcher.py clean           # 清空运行数据（行程/审批/报销/画像/日志/缓存），不动服务
python launcher.py fresh           # 干净启动：停止 → 清空运行数据 → 重新启动
```

也可直接双击：**`总控台.bat`**（常驻总控台，含启动/停止/重启/日志/状态）、`停止.bat`（一键停全部）、`start.bat`（启动后自动收窗）、`干净启动.bat`（清空历史后启动）、`清空数据.bat`（只清不启）。
默认 `start` 完成后启动窗口自动关闭，**重复双击不会叠出多个黑窗**（服务本体无窗口，日志落盘 `.logs/`）；
后端 + 前端均后台运行，依赖增量检测（requirements.txt 变化才重装）；
启动为并行拉起 + 增量健康检查（谁先就绪先报谁），单体模式冷启动约 6 秒就绪。

**清空历史数据（解决"上次的行程/对话还在"）**

`scripts/reset_data.py` 是底层清理脚本，`launcher.py` 在它之上封装了三个入口：

| 场景 | 操作 | 效果 |
|:---|:---|:---|
| 清一次 | `清空数据.bat` / `python launcher.py clean` | 停止服务后清空运行数据（不重新启动） |
| 干净启动 | `干净启动.bat` / `python launcher.py fresh` | 停止 → 清空 → 启动，工作台带 `?fresh=1` 顺带清前端对话快照 |
| 每次都清 | 总控台按 `[11]` 开启 | 之后每次 `start.bat` 启动都会先清一遍（标记文件 `.cjh_fresh`，再去按一次即关闭） |

清理范围：`data/trips`、`data/test_trips`、`data/org/approvals`、`data/org/reimbursements`、`data/profiles`、`.logs`、`.run`，以及 `__pycache__` / `.pytest_cache` / `frontend/node_modules/.vite` / `frontend/dist` 等缓存。
**不会动**：`data/system/`（大模型与管理员配置）、`data/org/{departments,employees,policies,policy_docs}`（组织与政策种子）、`.env`、源码。

删除前会整体搬到 `.backup/reset-<时间戳>/`（保留最近 3 份，可随时回滚）。需要连种子数据一起清：
`python scripts/reset_data.py --scope full --reseed`（清完自动重灌组织/政策种子）；只看不动手用 `--dry-run`。

**单体模式下的接口前缀**（对外只有一个 8001）：

| 业务线 | 路径前缀 | 文档 |
|:---|:---|:---|
| 行智 Journey Hub | `/agent/*`、`/auth/*`、`/admin/*` | http://localhost:8001/docs |
| 策程 Planner Core | `/planner/*`（如 `/planner/trips/generate`） | http://localhost:8001/planner/docs |
| 感知 Sense Engine | `/sense/*`（如 `/sense/query`） | http://localhost:8001/sense/docs |

服务索引：`GET http://localhost:8001/` 一键列出三条业务线的前缀与文档地址。

### 4.2.1 开发者手动启动（备用）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM API Key（留空则自动降级为 Demo 模式）

# 3. 启动全部 3 个服务（后台模式）
python scripts/start_local.py

# 4. 验证
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health

# 5. 停止
python scripts/stop_local.py
```

### 4.3 前端启动（Web 工作台）

```bash
cd frontend
npm install
npm run dev        # http://localhost:3001（已配置代理到三个后端服务）
```

### 4.4 只启动单个服务

```bash
python scripts/start_local.py --only journey    # 只启动行智
python scripts/start_local.py --only planner    # 只启动策程
python scripts/start_local.py --only sense      # 只启动感知
```

### 4.5 Docker 部署

```bash
docker-compose up -d
```

---

## 五、API 一览

### 5.1 行智 · Journey Hub (8001)

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| POST | `/agent/chat` | 非流式对话 |
| POST | `/agent/chat/stream` | SSE 流式对话 |
| GET | `/agent/sessions` | 活跃会话列表 |
| POST | `/agent/session/{id}/clear` | 清除会话 |
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 指标 |

### 5.2 策程 · Planner Core (8002)

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| POST | `/trips/generate` | 流式生成行程 (SSE) |
| GET | `/trips` | 行程列表 |
| GET | `/trips/{trip_id}` | 行程详情 |
| PUT | `/trips/{trip_id}` | 编辑行程 |
| DELETE | `/trips/{trip_id}` | 删除行程 |
| POST | `/trips/{trip_id}/reroute` | 应变重排 |
| GET | `/trips/{trip_id}/checklist` | 出行清单 |
| POST | `/trips/{trip_id}/summary` | 行程总结 |
| GET | `/trips/{trip_id}/expenses` | 费用统计 |
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 指标 |

### 5.3 感知 · Sense Engine (8003)

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/trips/{trip_id}/alerts` | 获取行程提醒 |
| POST | `/monitor/subscribe` | 订阅监控 |
| GET | `/monitor/status` | 监控运行状态 |
| DELETE | `/monitor/{trip_id}` | 取消订阅 |
| POST | `/monitor/check` | 手动触发检查 |
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 指标 |

---

## 六、使用示例

### 6.1 对话式行程规划（员工视角）

```bash
# 通过行智 Agent 对话规划差旅行程
curl -X POST http://localhost:8001/agent/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_dev_local" \
  -d '{"query": "9月15号广州飞北京出差，16号上午拜访国贸客户，下午内部会议，17号下午返程，帮我安排行程", "session_id": "demo"}'
```

### 6.2 直接调用规划引擎

```bash
# SSE 流式生成行程
curl -X POST http://localhost:8002/trips/generate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_dev_local" \
  -d '{"query": "下周三人去深圳参加三天行业展会，需要提前一天布展，预算人均6000", "session_id": "demo"}'
```

### 6.3 订阅实时监控

```bash
# 为行程订阅航班 + 铁路 12306 + 天气监控
curl -X POST http://localhost:8003/monitor/subscribe \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_dev_local" \
  -d '{
    "trip_id": "trip_xxx",
    "user_id": "emp_1001",
    "flight_number": "CA1234",
    "destination_city": "北京",
    "train_code": "G102",
    "train_from": "广州南",
    "train_to": "北京西",
    "train_date": "2026-09-15"
  }'
```

> 也可以在 Web 工作台「实时监控」页点击「新建订阅」可视化操作（选行程、填航班/车次、勾选监控项）。

---

## 七、目录结构

```
ai-travel-assistant/
├── shared/                         # 平台复用层
│   ├── config/settings.py          # 配置管理
│   ├── llm/manager.py              # LLM 多服务商管理器
│   ├── logging_config.py           # 统一日志
│   ├── metrics.py                  # Prometheus 指标
│   ├── tracing.py                  # 链路追踪
│   ├── http_client.py              # 服务间调用客户端
│   ├── middleware/auth.py          # API Key 鉴权
│   └── models/state.py             # 共享数据模型
├── services/
│   ├── journey-hub/                # 行智 · Agent 编排中心
│   │   ├── api/main.py             # FastAPI 入口 + 登录认证 + 系统管理接口
│   │   ├── state/graph.py          # LangGraph 工作流
│   │   ├── router/intent.py        # 意图路由
│   │   ├── tools/                  # 工具注册 + 处理器
│   │   └── memory/session.py       # 会话管理
│   ├── planner-core/               # 策程 · 行程规划引擎
│   │   ├── api/main.py             # FastAPI 入口
│   │   ├── generators/itinerary.py # 行程生成器
│   │   ├── generators/checklist.py # 清单生成器
│   │   ├── generators/reroute.py    # 应变重排
│   │   ├── store/trip_store.py     # 行程存储
│   │   └── archive/summary.py      # 行后归档
│   └── sense-engine/               # 感知 · 实时感知引擎
│       ├── api/main.py             # FastAPI 入口
│       ├── engine.py               # 感知引擎核心
│       ├── sources/                # 数据源 (航班/天气/路况)
│       └── alerts/manager.py       # 提醒管理
├── frontend/                       # Web 工作台 (React 19 + Vite + Tailwind)
│   ├── src/pages/                  # 智能助手 / 行程管理 / 实时监控
│   ├── src/api/                    # 三个服务的 API 封装 (SSE)
│   └── vite.config.js              # 端口 3001 + 服务代理
├── scripts/
│   ├── start_local.py              # 一键启动
│   └── stop_local.py               # 一键停止
├── docs/
│   └── 需求文档.md                  # 产品需求文档（企业版 PRD）
├── .env.example                    # 环境变量模板
├── requirements.txt                # Python 依赖
└── docker-compose.yml              # Docker 编排
```

---

## 八、技术栈

| 层次 | 技术选型 |
|:---|:---|
| Web 框架 | FastAPI + Uvicorn |
| AI 编排 | LangGraph (StateGraph) |
| LLM 调用 | OpenAI 兼容多模型适配（混元 / DeepSeek / Qwen / GLM / 小米 MiMo），支持模型热切换与管理员在线配置 |
| 向量检索 (RAG) | Embedding 可插拔后端：本地 `BAAI/bge-large-zh-v1.5` 或 OpenAI 兼容 `/embeddings`，不可用时自动降级关键词检索 |
| 前端 | React 19 + Vite 8 + Tailwind CSS 4 + React Router |
| 定时调度 | APScheduler |
| HTTP 客户端 | requests (连接池 + 自动重试) |
| 可观测性 | Prometheus + 结构化 JSON 日志 + 全链路 Trace |
| 容器化 | Docker + Docker Compose |

---

## 九、降级策略

所有模块均内置降级兜底，**无 API Key 也能完整演示**：

| 模块 | 正常模式 | 降级模式 |
|:---|:---|:---|
| 行程生成 | LLM 智能规划 | 模板示例行程 |
| 清单生成 | LLM 个性化推荐 | 默认清单模板 |
| 行程总结 | LLM 智能总结 | 规则模板统计 |
| 航班监控 | 航班 API 查询 | Mock 模拟数据 |
| 天气监控 | 和风天气 API | Mock 模拟数据 |
| 路况监控 | 高德地图 API | Mock 模拟数据 |
| 政策检索 (RAG) | 向量语义检索 | 关键词检索 |

---

## 十、政策知识库检索（RAG）

政策文档（差旅标准、报销规则、审批制度等）入库后支持语义检索，供 LLM 引用原文作答，
满足合规可解释性要求。**Embedding 采用可插拔后端**，按可用性自动选择：

| 后端 | 说明 | 启用方式 |
|:---|:---|:---|
| `local` | 本地 `BAAI/bge-large-zh-v1.5`（1024 维），**数据不出企业**，适合私有化部署 | `pip install sentence-transformers` |
| `api` | OpenAI 兼容 `/embeddings` 接口（如 TokenHub `kinfra-text-embedding-0.6b`） | 配置 `EMBEDDING_API_MODEL` 并开通模型权限 |
| `none` | 关闭向量，全部走关键词检索（默认降级态） | `EMBEDDING_PROVIDER=none` |

通过 `.env` 的 `EMBEDDING_PROVIDER`（auto / local / api / none）切换。
检索接口返回 `mode` 字段标明本次走的是 `vector` 还是 `keyword`，
并保留原文 `excerpt` 与相似度 `score` 供引用。

```bash
# 语义检索政策文档
curl -X POST http://localhost:8002/policy-docs/search \
  -H "Content-Type: application/json" -H "X-API-Key: ak_dev_local" \
  -d '{"query": "总监去北京住宿标准是多少", "top_k": 3}'

# 重建向量索引（force=true 强制全量重建）
curl -X POST "http://localhost:8002/policy-docs/reindex?force=false" \
  -H "X-API-Key: ak_dev_local"
```

> bge 系列维度：small=512 / base=768 / **large=1024**，可按成本与精度选择规格。

---

## 十一、开发计划

| 阶段 | 范围 | 状态 |
|:---|:---|:---|
| **P0 · MVP** | 行程生成 + 智能问答 + 实时提醒 + Web 工作台 | ✅ 已完成 |
| **P1 · 企业化** | 差旅政策知识库 (RAG) + 预算管控 + 审批流转 + 组织与人员管理 | ✅ 已交付（生成→政策检查→自动审批→门禁闭环，含登录权限与种子数据） |
| **P2 · 完善** | 报销对接 + 管理报表看板 + 企业 SSO (OIDC) + 费用导出 | 🔲 待开发 |

---

## 十一、License

MIT
