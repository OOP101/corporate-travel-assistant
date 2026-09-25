# 企业智行 · Corporate Journey Hub（v3 · Agent 原生）

> 面向企业内部的智能行程规划与安排平台：**Agent 内核（LangGraph）+ 审批闭环唯一业务主线 + 外接服务总线**，覆盖「行前规划 → 行中保障 → 行后归档」全链路。

> 📌 **完整项目文档**（背景/架构/进度/踩坑/数据口径）见 [`docs/项目文档.md`](docs/项目文档.md)。
> 📌 **v3 重构蓝图**见 [`docs/重构-v3-agent原生-蓝图.md`](docs/重构-v3-agent原生-蓝图.md)。
> 📌 **代码审查与修复记录**见 [`docs/审查-v3契约漂移与鉴权缺口-20260925.md`](docs/审查-v3契约漂移与鉴权缺口-20260925.md)。

## 界面预览

| 中控台（落地页） | 差旅行程（策程） |
|:---:|:---:|
| ![中控台](docs/screenshots/workbench.png) | ![差旅行程](docs/screenshots/trips.png) |

> ⚠️ 截图待重拍：`workbench.png` 仍是含「实时监控」卡片的旧中控台版本。该页已随 v3 切型
> 下线（见下「已下线能力」），重拍前请勿据此判断当前界面。智能助手页暂无截图。

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

**70 passed / 0 failed**（v3 基线：内核 API 11 + 审批闭环与鉴权 11 + Agent 层 7 + shared 基建 41；2026-09-25 实测）。
覆盖：澄清契约与授权代填死循环回归、确认门禁（未确认绝不审批）、审批状态机、个人场景豁免、
越权访问 404、**审批接口匿名调用 401 / 非审批人 403 / 非管理员列表收敛到本人**、
**手工建单同步置行程待审批**、档案与同行人读写、外接服务检索降级、工具总线容错。

## 代码审查与修复记录（2026-09-25）

用 [alibaba/open-code-review](https://github.com/alibaba/open-code-review) 对本仓做全量扫描，再逐条回源码复核。
扫描本身**只覆盖了仓库前 1/3**（DashScope 免费额度在中途耗尽，后端 `services/` 批次几乎全部 403 跳过），
所以后端的结论**不是来自扫描报告，而是本轮的独立源码核验 + 路由表比对**。

| 指标 | 值 |
|:--|:--|
| 扫描覆盖 | 154 文件 / 62 条意见（全部落在前端 + 配置，后端 0 条） |
| 报告的净价值 | 62 条意见里真正有信息量的是 1 条 critical：前端 `api/sense.js` 在调 v3 已删除的端点 |
| 由该线索扩出的真实问题 | **34 条死链 / 6 个死页面**、**3 处审批零鉴权**、**1 处审批闭环断点**、4 处零消费者资产 |
| 修复后 | 死链 **34 → 0**；匿名调审批 **200 → 401**；非审批人 **200 → 403**；测试 **64 → 70 passed** |
| 回归验证手段 | 新增 `scripts/check_api_contract.py`（契约守卫，退出码 1 = 有死链）+ 端到端鉴权复现 |

**聚焦的三处系统性风险**（都不是"某一行写错了"，而是跨层契约失守）：

1. **路由删除没有护栏** —— v3 切型删掉 10 个 CRUD 路由，但 Store 层、前端页面、导航项、Vite 代理全留着，
   导航 12 项里 **5 项通向整页 404**，而没有任何机制能在提交前发现。
2. **鉴权缺口集中在审批链路** —— 建单 / 通过 / 拒绝 / 取消四个接口当时**零鉴权**，任何人可给自己开单并当场批掉。
   现已收敛为：匿名 401、非本人或非管理员 403、列表对非管理员强制收敛到本人、建单的申请人取自登录态（不可由 body 冒名）。
3. **状态机有个静默断点** —— 手工建单不回写行程状态，导致 `approve()` 的回写条件永不成立：
   **审批通过了，行程状态纹丝不动**。这是"审批通过后列表为空"这个历史疑难的历史根因之一（另一个是身份可伪造导致的数据错位）。

> **最有信息量的一条观察**：AI 审查工具在这类问题上**召回率有限、且会漏真 bug**。它抓到的那条 critical 方向是对的，
> 但一个文件里 6 条死链只报出 1 个文件；真正严重的三处**零鉴权**（可实测复现的 HTTP 200）它一条都没报 ——
> 因为在额度耗尽前它根本没读到后端。**AI 审查当"线索"用有效，当"验收结论"用危险。**

### 契约守卫（提交前跑一次）

前端调用的每个路由都必须在后端存在。该检查已脚本化：

```bash
./.venv/Scripts/python.exe scripts/check_api_contract.py   # 退出码 1 = 存在死链
```

实现要点：路由真相取自 `app.openapi()['paths']` —— **不能用 `app.routes`**，新版 FastAPI 会把
`include_router` 的结果表示成惰性 `_IncludedRouter` 包装（没有 `.path`），会让整套路由"看起来不存在"。

完整取证、死链清单、修复动作与验证对照表见
[`docs/审查-v3契约漂移与鉴权缺口-20260925.md`](docs/审查-v3契约漂移与鉴权缺口-20260925.md)。

## 已下线能力（2026-09-25 收敛）

v3 切型移除了这些能力对应的后端服务与路由，导航与前端代码当时未同步清理，已一并下线（**代码同步删除**，含 Store 与配置项，一律走回收站）：

| 能力 | 原前端入口 | 下线原因 | 代码清理 |
|:--|:--|:--|:--|
| 实时监控 | `/alerts`（感知 · Sense Engine） | sense-engine 已随切型移除，替代形态规划为 MCP | `api/sense.js`、`RealtimeCards.tsx`、`shoot_alerts.py`、`settings.sense_data_dir` |
| 行程模板 | `/templates` | 无后端路由，能力暂不保留 | `api/planner.js` 模板五函数、`SaveTemplateDrawer`、`TemplateStore`、`settings.template_data_dir` |
| 报销管理 | `/reimbursement` | `ReimbursementStore` 从未接线，无数据 | `ReimbursementPage.jsx`、`ReimbursementStore` 类 |
| 报表中心 | `/reports` | 依赖报销口径，且后端无 `by_status` 聚合 | `ReportsPage.jsx`、`getReportOverview` |
| 组织管理 | `/org` | 员工数据仍由审批闭环内部使用，不再暴露 CRUD | `OrgPage.jsx`、`DepartmentStore` 类、`deps.dept_store` |

保留：**我的档案**（`/profile`，已补齐后端路由 `/users/me/profile` 与 `/users/me/companions`）；
`EmployeeStore` **保留**——审批闭环靠它把 `user_id` 映射到职级与审批人。

> 顺手清掉的 v2 残留：`launcher.py` 的 micro 模式文案（早已是 single 的退役别名）、
> `settings` 里 8 个零引用的 `journey/planner/sense host/port` 与两个 `*_service_url`。

## 后续规划

| 方向 | 说明 |
|:--|:--|
| ReAct 思考链帧化 | 管线帧机制输出决策过程（步骤/工具/实测耗时），前端实时渲染（任务 #9） |
| 对话式行程变更 | 「改到周三」→ 快照恢复 → 重生成 → 重新审批（任务 #10） |
| 感知外接服务以 MCP 回归 | 航班/天气/路况轮询与分级提醒不复活旧 sense-engine，改由 MCP 提供（替代上面下线的「实时监控」） |
| 报表与组织能力以 MCP 回归 | 同上：不重建 `/reports` `/org` 的 CRUD 路由 |
| 行程质量评测集 | 生成质量量化 + Prompt 变更回归门禁 |

> 场景边界（已拍板）：专注企业差旅主线，不做横向场景堆量（详见重构蓝图 §八）。
