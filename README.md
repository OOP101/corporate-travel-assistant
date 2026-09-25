# 企业智行 · Corporate Journey Hub（v3 · Agent 原生）

> 面向企业内部的智能行程规划与安排平台：**Agent 内核（LangGraph）+ 审批闭环唯一业务主线 + 外接服务总线**，覆盖「行前规划 → 行中保障 → 行后归档」全链路。

> 📌 **完整项目文档**（背景/架构/进度/踩坑/数据口径）见 [`docs/项目文档.md`](docs/项目文档.md)。
> 📌 **v3 重构蓝图**见 [`docs/重构-v3-agent原生-蓝图.md`](docs/重构-v3-agent原生-蓝图.md)。

## 界面预览

| 智能助手（行智） | 差旅行程（策程） | 实时监控（感知） |
|:---:|:---:|:---:|
| ![智能助手](docs/screenshots/workbench.png) | ![差旅行程](docs/screenshots/trips.png) | ![实时监控](docs/screenshots/alerts.png) |

## v3 架构

```
Agent 内核（唯一服务 core，端口 8001）
  ├─ LangGraph 意图路由（plan / chat / manage / respond / emergency）
  ├─ 行程生成引擎（场景澄清 ≤2 轮 · 两阶段输出 · 授权代填显式标注）
  ├─ 审批闭环（唯一业务主线：确认门禁 → 政策检查 → 审批 → 生效/作废）
  └─ 会话与鉴权（HMAC 无状态 token · 自助注册）
工具总线（ToolRegistry）：一切能力皆工具，可插拔、失败静默降级
外接服务：政策服务（差旅规则+文档 RAG）· 攻略服务（个人出游语料 RAG）· 地图 MCP
基建层（原样移植）：LLM 网关 · Embedding 三后端 · JSON 存储 · decision/geo/metrics
```

与 v2（三层微服务 + 10 个 CRUD 路由）的本质区别：**Agent 是一等公民**，业务能力全部工具化外接，
编排层进程内直调（v2 是同进程绕 HTTP 回调）；审批闭环从散落在 CRUD 路由里的逻辑升格为独立引擎。

## 技术栈

| 层次 | 技术选型 |
|:---|:---|
| Web 框架 | FastAPI + Uvicorn（单服务单端口 8001） |
| AI 编排 | LangGraph (StateGraph) + ToolRegistry 工具总线 |
| LLM | 腾讯 TokenHub `deepseek-v4-flash`（主）/ kimi-k3 / hy-mt2-pro |
| 向量检索 | 可插拔：本地 bge-large-zh-v1.5 / OpenAI 兼容 / 关键词降级 |
| 前端 | React 19 + Vite 8 + Tailwind CSS 4 |
| 外部数据 | 腾讯位置服务（SN 签名 + 官方 MCP/SSE 客户端）+ 和风天气 |
| 可观测性 | Prometheus + 结构化日志 + 全链路 Trace |

## 行程规划主链路

| # | 阶段 | 说明 |
|:--|:--|:--|
| 1 | 意图路由 | LangGraph：规划 / 问答 / 管理 / 应急（规则 + 正则排除误路由） |
| 2 | 参数抽取 | 两级抽取：规则直取（典型差旅句式 0 LLM）→ LLM 兜底；部分命中自动补位，已抽参数澄清不重问 |
| 3 | 澄清回合 | 必填缺失反问（≤2 轮）；「你看着办」授权代填并在确认页 `[代填]` 显式标注 |
| 4 | 两阶段生成 | 商务类场景模板直出（毫秒级）；个人出游走 LLM + 攻略语料 RAG |
| 5 | 确认与审批 | 草案确认后才落库；政策预检仅预警；审批通过才生效、拒绝即作废；待审批不可调整 |
| 6 | 生效与触达 | 应变重排 / 出行清单 / 总结 / 消费统计 / 行程单导出 |

## 快速开始

**日常只需双击 `start.bat` 启动、双击 `停止.bat` 停止**（单服务单端口 8001）。

```bash
python launcher.py            # 启动：Agent 内核 8001 + 前端 3001
python launcher.py stop       # 停止全部服务
python launcher.py status     # 查看服务状态
```

- 前端工作台：http://localhost:3001
- 接口文档：http://localhost:8001/docs
- 工具总线清单：http://localhost:8001/agent/tools（内核工具 + 外接服务工具一目了然）

## 测试

```bash
pytest --basetemp=./.pytest_tmp -q
```

**64 passed / 0 failed**（v3 基线：内核 API 11 + 审批闭环 6 + Agent 层 6 + shared 基建 41；2026-09-25 切型实测）。
覆盖：澄清契约与授权代填死循环回归、确认门禁（未确认绝不审批）、审批状态机、个人场景豁免、
越权访问 404、外接服务检索降级、工具总线容错。

## 后续规划

| 方向 | 说明 |
|:--|:--|
| ReAct 思考链帧化 | 管线帧机制输出决策过程（步骤/工具/实测耗时），前端实时渲染（任务 #9） |
| 对话式行程变更 | 「改到周三」→ 快照恢复 → 重生成 → 重新审批（任务 #10） |
| 感知外接服务插装 | 航班/天气/路况轮询与分级提醒以工具形式回归（v2 已验证代码待移植） |
| 行程质量评测集 | 生成质量量化 + Prompt 变更回归门禁 |

> 场景边界（已拍板）：专注企业差旅主线，不做横向场景堆量（详见重构蓝图 §八）。
