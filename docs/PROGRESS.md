# 企业智行 Corporate Journey Hub · 进度主线 (PROGRESS)

> 跨会话主线追踪。每次会话开始先读本文件接着干，完成后更新它。
> 跨会话约定/决策见 `.workbuddy/memory/MEMORY.md`。

## 阶段总览
- **P0（可运行）**：✅ 完成 —— 3 服务（journey-hub 8001 / planner-core 8002 / sense-engine 8003）+ React 前端 3001 可跑通。
- **P1（企业化闭环）**：✅ 交付 —— 组织/政策/审批/政策文档 后端+前端写完、串链路、有种子数据；生成→政策检查→自动审批→门禁闭环；实时数据「查询直查 / 推送走监控」已落地（2026-09-03）。
- **P2（深化）**：🟡 进行中 —— 报销 / 报表 / SSO / 导出 + 真向量 RAG 启用。

## P2 交付清单

| 模块 | 状态 | 说明 |
|---|---|---|
| 行程单导出 (export) | ✅ 已完成 | 后端 `GET /trips/{trip_id}/export` 渲染打印友好 HTML；前端「导出行程单」按钮 → 浏览器打印/另存 PDF。零依赖（不装 python-docx）。 |
| 报销 (reimbursement) | ✅ 已完成 | 提交（自动算额+按直属主管指派审批人）/ 审批 / 打款；前端「报销管理」页。 |
| 报表 (report) | ✅ 已完成 | overview / by-department / by-month 只读聚合；前端「报表中心」页（KPI + 部门/月度表）。 |
| SSO | ⏸ 阻塞 | 等外部 IdP，暂未接入。 |
| 真向量 RAG 启用 | ⏸ 待条件 | 框架已就位；需开通 embedding 权限或装 sentence-transformers（`BAAI/bge-large-zh-v1.5`，1024 维）。当前运行态为关键词检索（`mode=keyword`）。 |

## 本次会话交付：行程单导出
- **后端** `services/planner-core/api/routers/trips.py`
  - 新增 `GET /trips/{trip_id}/export`，返回 `text/html; charset=utf-8` 行程单。
  - `_render_itinerary_html(trip)`：纯字符串渲染，含标题/状态/出发地目的地/日期/出行人/总预算 + 逐日行程表 + 出行清单 + 费用预估（复用 `SummaryGenerator._calc_expenses`），内嵌 `@media print` 样式，HTML 转义防注入。
  - `_humanize_party()`：把 `travel_party`（str / list[dict] / dict）统一成可读人名串。
- **前端**
  - `frontend/src/api/planner.js`：`getTripExportHtml(tripId)`（带 `X-API-Key` 拉取 HTML）。
  - `frontend/src/pages/TripDetailPage.jsx`：header「导出行程单」按钮 → `exportTripSheet()`：fetch → `window.open` 写入 → `print()`。
- **验证**：8002 重启后 `/openapi.json` 含该路由；web-user 实测导出 HTTP 200、`text/html`、结构完整、`出行人` 渲染正确。前端需在跑着的 vite 上点击实测打印预览。

## 本次会话交付（续）：报销模块 (reimbursement)
- **后端** `services/planner-core/api/routers/reimbursements.py`：报销 CRUD + 状态机。
  - `POST /reimbursements` 提交：校验行程/员工存在；**金额自动计算**（有明细累加明细，否则用 `SummaryGenerator._calc_expenses` 的行程费用汇总）；**审批人自动指派**为员工直属主管（`EmployeeStore.get_manager`），无主管则要求显式 `approver_id`；初始状态 `pending`。
  - `GET /reimbursements`（按 employee_id / approver_id / status 过滤）、`GET /reimbursements/{id}`（附带行程/员工/审批人信息）。
  - `POST /reimbursements/{id}/approve|reject` 审批；`POST /reimbursements/{id}/pay` 打款（仅 `approved` 可打款 → `reimbursed`）。
  - 配套 `store/org_store.py` 新增 `ReimbursementStore`（BaseJsonStore，`reb_` 前缀）；`api/deps.py`、`api/main.py` lifespan、`api/routers/__init__.py`、store 包导出均已接入；落地目录 `data/org/reimbursements`。
- **前端**
  - `frontend/src/api/organization.js`：新增 `listReimbursements / submitReimbursement / getReimbursement / approveReimbursement / rejectReimbursement / payReimbursement`。
  - `frontend/src/pages/ReimbursementPage.jsx`：新建「报销管理」页（提交表单 + 列表 + 详情弹窗，pending 显审批按钮、approved 显打款按钮），复用 `ApprovalPage` 设计语言。
  - `frontend/src/App.jsx`：新增 `/reimbursement` 路由、侧边栏「报销管理」入口（企业管理组）、页面标题。
- **验证**：8002 重启加载新路由；完整生命周期实测——提交（自动指派审批人 emp_1001、金额 ¥1330、费用构成按类目拆分）→ 审批 → 打款（`reimbursed` + 打款人）；重复打款/未知员工/无主管未指定审批人均正确拦截（400/404）。前端为定向小改，需在 vite 上点击实测。
- **说明**：预算 `budget_total` 与报销金额（按 `estimated_cost` 汇总）是两套口径，前者为预算、后者为实际可报费用，符合 PRD 预期。

## 本次会话交付（续）：报表中心 (report)
- **后端** `services/planner-core/api/routers/reports.py`：三个只读聚合接口。
  - `GET /reports/overview`：全局 KPI——行程（总数/总预算/状态分布）、报销（总数/总金额/状态分布含金额）、审批（同报销口径）。
  - `GET /reports/by-department`：按 `employee_id → dept_id` 映射聚合（未命中落 `未归属` 桶）——人数/行程数/行程预算/报销笔数与金额/已打款/待审批。
  - `GET /reports/by-month`：按月（行程 `start_date[:7]`、报销 `created_at`）聚合行程数与预算、报销提交/已打款/待审批金额。
- **修复的 500（关键排障）**：三接口曾全部 HTTP 500，根因 `TripStore` 是 P0 遗留独立存储、**没有 `list_all()`**（报表首个调用它）→ `store/trip_store.py` 补 `list_all()`（按 updated_at 倒序，对齐 BaseJsonStore）。一处修复三接口同时恢复。
- **前端**
  - `frontend/src/api/organization.js`：新增 `getReportOverview / getReportByDepartment / getReportByMonth`。
  - `frontend/src/pages/ReportsPage.jsx`：新建「报表中心」页——4 张 KPI StatCard（行程/预算/报销/审批）+ 三组状态分布 chips + 部门汇总表 + 月度汇总表，右上角刷新按钮带更新时间。
  - `frontend/src/App.jsx`：新增 `/reports` 路由、侧栏「报表中心」（企业管理组）、页面标题。
- **验证**：8002 重启后三接口全 200（overview：94 行程 ¥274,870 / 报销 1 笔 ¥1330 / 审批 23 笔 ¥64,550；部门：技术部 17 行程、市场部 1 报销、未归属 77 行程；月度：2026-08~12）。前端模块经 Vite 转换冒烟 200；界面点测需在跑着的 vite 上进行。
- **口径提示**：demo/测试行程 `user_id` 大量不在员工表 → 报表里落在「未归属」桶（77/94），属种子数据现状，页面已保留该桶并标注。

## 本次会话交付（续）：智能助手 会话存续 + 流式输出
- **缺陷**：① 与助手对话生成行程后切换菜单（路由），对话与刚生成的行程全部消失 —— 消息放在 ChatPage 组件局部 `useState`，路由卸载即丢；② 生成过程"不流式" —— planner 原始行程 JSON 被逐帧透传进聊天气泡与 TripsPage 横幅，表现为乱码式刷屏、最后 `respond` 才整段替换成人话摘要。
- **后端**（services/journey-hub，三文件）
  - `tools/handlers.py`：`plan_trip_stream` 重写为结构化帧协议 `{"kind":"progress"|"text","content"}` —— 不再透传原始 JSON；按生成 JSON 字符数折算「行程内容生成中…已生成 X 字」进度帧；新增 `_chunk_text` 把人话摘要切成 ~60 字符、20ms 停顿输出（打字机）。同步聚合版 `plan_trip` 只取 `kind=="text"` 帧（兼容 str fallback）。
  - `state/graph.py`：plan 意图流分支映射 —— `kind:progress` → `{"event":"progress"}`、`kind:text`/str → `{"event":"chunk"}`。
  - `api/main.py`：流式端点 docstring 补充 `progress` 帧；新增 `GET /agent/session/{session_id}/history?last_n=N`（session_manager 历史，tool 角色归一为 assistant）。
- **前端**
  - `store/chatStore.js`（新建）：模块级单例对话 store（同 generationStore 套路）——`hydrate`（localStorage 快照 `cjh_chat_web-user` > 服务端历史 > 问候语）/ `send`（loading 中拒重复）/ `stop` / `reset` / `subscribe`；SSE 事件落地：`intent` 存字段、`progress` 存 `msg.progress`（生成中空正文展示用）、`chunk` 追加 content、`respond` 替换全文 + `buildCards`、`done` 按意图设 followups。**流式请求存活于模块作用域，切菜单不中断**。
  - `api/journey.js`：新增 `getSessionHistory / clearSession`。
  - `pages/ChatPage.jsx`：重写为订阅 chatStore；生成中 content 为空且 loading 时显示 progress 文案，空正文非 loading 不渲染占位；底部新增「清空会话」按钮（confirm 后 `chatStore.reset()` → 清本地快照 + 服务端 `/clear`，仅非生成中且对话非空时可用）。
  - `pages/TripsPage.jsx`：生成横幅不再刷原始 JSON —— chunk 折算「已接收 X 字」进度、policy/approval 事件汇入 `approvalNote`、done 显示 `formatTripBrief` 人话摘要 + 政策/审批结论。
- **验证（全部实测通过）**：Vite 转换冒烟 200（chatStore / ChatPage / TripsPage / App / journey）；8001 重启后 openapi 含 history 端点；端到端流式冒烟（web-user，上海当日往返）帧序 `route → intent(plan) → progress×6（已生成 600/1201/…/3019 字）→ chunk×5（人话摘要打字机）→ respond → [DONE]`，无原始 JSON；`GET /agent/session/web-user/history` 返回归一化 2 条（user 提问 + assistant 摘要）。
- **说明**：服务端会话历史仍在进程内（重启即空），跨刷新持久兜底靠 localStorage 快照；跨设备/长期留存后续可接 DB。

## 本次会话交付（续）：输入框上方常驻「快捷建议」卡（随机换一批）
- 需求：聊天页建议卡——输入框上方常驻、每次回答后自动刷新、可随机换一批；气泡下追问保留。
- 实现：
  - `store/chatStore.js`：state 增 `quick/quickIntent`（常驻建议+所属意图）；`done` 事件自动置为该意图固定 3 条（与气泡追问同源 FOLLOWUPS）；导出 `FOLLOWUP_POOL`（各意图 8-9 条候选池）与 `sampleQuick(intent,n)`（随机抽取，优先扩展项、避开固定 3 条）；新 action `chatStore.quickRandom()`；`hydrate` 从本地/服务端恢复历史后 `syncQuickFromLast()` 回填常驻建议。FOLLOWUPS 的 manage/emergency 补齐为 3 条 core。
  - `pages/ChatPage.jsx`：移除消息流内嵌「首轮才显示」的示例块；消息区与输入框之间新增常驻快捷建议区——空对话（仅问候语/刚清空）展示初始示例 3 条、回答后显示「{意图} · 快捷建议」固定 3 条并带「换一批」按钮（RefreshCw → quickRandom 随机抽 3）；点击即发送；生成中（loading）整区隐藏。
- 验证：Vite 转换冒烟 chatStore.js / ChatPage.jsx 均 200。需用户在 vite 实测：回答后输入框上方出现建议、点「换一批」内容变化、空对话显示示例。

## 本次会话交付（续）：聊天空态居中首页 + 「新对话」入口
- 需求：① 提供显式「开启新对话」入口（原只有底部不起眼"清空会话"）；② 空对话首页（问候+示例卡片）居中展示，而非贴顶/贴底。
- 实现（仅 ChatPage.jsx）：
  - 空态（仅问候语/刚开启新对话）改**居中首页视图**：品牌 logo + 「企业行程智能助手」标题 + GREETING 文案 + SUGGESTIONS 三张大卡（点击直接发送）。
  - 非空对话时**顶部右侧「＋ 新对话」**按钮（confirm → chatStore.reset()：清本地快照 + 服务端 /clear，已生成行程/单据不受影响；loading 禁用）；底部"清空会话"按钮删除，footer 提示更新。
  - 输入框上方常驻快捷建议区条件收紧为 `!isEmptyChat && store.quick.length>0`（空态示例由居中首页承担，不再贴底重复）。
- 验证：Vite 转换冒烟 200。需用户实测：进聊天页=居中首页；发送后顶部出现「新对话」；点击回到居中首页；回答后输入框上方仍出快捷建议（固定 3 条 + 换一批）。

## 本次会话交付（重大）：行程规划对话流程 PRD v2（重写需求文档）
- 触发：用户实测「我下周要去深圳」→ 系统生成「深圳3天文化自然人文之旅」并自动审批；用户质疑天数/酒店随机、场景错误，指出整个项目流程有大问题，要求**重写需求文档**。
- 根因定案（代码行号证据见新 PRD §1.2 / §11）：extract 示例默认值诱导 + setdefault 兜底 + PLANNING_RULES 纯旅游引擎 + 无澄清/确认环节 + 表单仅 query 一字段 + README 场景宣言未实现。
- 用户决策：场景由**用户选择**；缺参**反问优先、次要字段可代填**。
- 交付物：`docs/PRD-行程规划对话流程-v2.md` —— 场景模型（business/meeting/visit/team/personal）、参数必填/可代填规则、对话状态机 S0-S6（新增 S2 澄清 ≤2 轮、S4 方案确认页；**审批只在用户确认后触发**）、澄清话术、酒店规范（1 主选+2 备选/政策上限）、验收用例 U1-U6、改造落点与分期（P1 澄清+场景 → P2 确认页 → P3 scene 化规则）。
- 待用户评审后按 PRD §9 实施；本期先不做代码改造（文档先行，避免再次方向性返工）。

## 关键约束（勿推翻）
- LLM：小米 MiMo 为 `.env` 默认 provider；多模型经 admin `default_model=hy-mt2-pro` 走 TokenHub 网关（mimo/hy/deepseek/glm 经 model_id 路由）。
- Embedding：`BAAI/bge-large-zh-v1.5`（1024 维）；`EMBEDDING_PROVIDER` 切换 local/api/none，当前 none（关键词降级）。
- 服务启停：**`launcher.py` 统一控制台**（一键启动/停止/重启/看日志，支持 `stop|restart|status` 子命令）；`scripts/fg_service.py <journey|planner|sense>`（前台单服务调试）；`scripts/start_local.py` 仍可用于后台批量启动（沙箱内 netstat 有时无输出，需手动 `netstat -ano|grep :PORT` + `taskkill /F /PID`）。
- 前端 2.0 已重构，改前端先读 `src` 现状，别推翻设计系统。
- 沙箱坑：Vite 启动需清空 `NODE_OPTIONS`；PyInstaller 构建路径指 `%TEMP%`；`taskkill` 经 Git Bash 参数会被吞，用 Python `subprocess.run(['taskkill','/F','/PID',pid])`。

## 下一步建议
1. 用户在 vite 上实测：①聊天生成行程后切菜单再切回（对话/行程卡片应保留）；②生成过程应看到「已生成 X 字」进度 + 人话摘要打字机输出；③底部「清空会话」后刷新页面仍为全新对话；④「导出行程单 / 报销管理 / 报表中心」页面交互。
2. 服务端历史仍为进程内，重启即空（跨刷新持久靠 localStorage 快照）。
3. P2 剩余项均受外部条件阻塞：SSO 等外部 IdP；真向量 RAG 需开通 embedding 权限或 `pip install sentence-transformers`（`BAAI/bge-large-zh-v1.5`，1024 维）。
4. 可选深化：报表加时间范围过滤（?from=&to=）、导出 CSV/Excel、报销按费用类目透视。

## 本次会话交付（续）：外部服务接入（腾讯地图 / 和风天气 / 酒店 POI）
- 触发：用户指出出发地未接地图 API key/未调用、天气工具未在规划链路调用、酒店/美团/携程未集成。核实结论：**全部属实**——`planner-core/**` 对 weather/traffic/geocode/sense 零引用，`shared/state/graph.py` 零引用；地图/和风仅存在于 sense-engine 的监控+问答直查路径且 key 为空（=mock）；酒店零 API 集成。根因：实时数据被设计成 sense-engine 的感知/监控+问答，与 planner 纯生成模块未打通，外部 key 以空串占位+mock 源。
- 用户拍板（AskUserQuestion）：三项全做；用户提供真实 key；酒店走地图 POI 结构化候选（携程/美团开放 API 为白名单，不纳入）。
- **地图供应商切换（2026-09-03）：由高德切换为腾讯位置服务**。原因：用户要求统一用腾讯地图。关键差异——腾讯需 `key + SecretKey(SK)` 做 `sig=md5(请求路径?排序参数+SK)` 签名（高德仅 key）。故新增 `TENCENT_MAP_SK` 配置项；`from/to` 格式为 `lat,lng`（与高德相反）；POI 用 `ws/place/v1/search` + `boundary`。
- 交付物：`docs/PRD-外部服务接入-腾讯地图天气酒店.md`（架构/数据流/各能力规格/注入点/验收 U-E1~E5）。
- 代码落点：
  - 新增 `shared/geo/__init__.py` + `tencent_client.py`（`TencentMapClient`：geocode / driving_route / poi_hotels，端点 `apis.map.qq.com/ws/geocoder/v1`、`/ws/direction/v1/driving`、`/ws/place/v1/search`，含 SK 签名逻辑）+ `qweather_client.py`（forecast_7d，端点 `devapi.qweather.com/geo/v2/city/lookup` + `/v7/weather/7d`）。key 空或调用失败一律返回 None，绝不阻断。
  - 改造 `services/planner-core/generators/itinerary.py`：`generate()`/`generate_stream()` 在 extract 后调 `_enrich_external(params)`；`_build_generation_prompt` 注入 `_external_prompt_block(ext)`（真实数据才注入坐标/逐日天气/酒店候选；无 key 仅附注"未配置，勿编造"）；生成后 `_attach_external` 把 `geo/route/weather_forecast/hotel_options/external_data.real` 挂到行程 dict 落库。`_demo_generate` 亦挂空占位保持结构一致。
  - 改造 `services/sense-engine/sources/traffic.py`：原高德调用改为复用 `shared.geo.TencentMapClient`（geocode + driving_route），拥堵等级由「实际时长/自由流时长」启发式估算；key 空→mock。移除 `amap_api_key` 依赖。
  - 配置：`shared/config/settings.py` 移除 `amap_api_key`，新增 `tencent_map_key`(env `TENCENT_MAP_KEY`) + `tencent_map_sk`(env `TENCENT_MAP_SK`)；`.env` 与 `docker-compose.yml`（planner-core + sense-engine 均注入）同步替换。
- 验证：`.venv` 跑双分支冒烟——① key 空：全部 None、不联网不抛异常、提示词只给未配置提示、不编造假天气/酒店；② 模拟真实 key（含 SK 签名）：坐标/路线/逐日天气/酒店候选注入提示词，行程单 `real=true`。两端均 PASS。
- 待用户回填真实 key（TENCENT_MAP_KEY/TENCENT_MAP_SK/WEATHER_API_KEY 写入 .env）后做端到端真实冒烟（任务 #23）。前端行程详情页展示天气徽标/酒店候选为独立任务（#22，结构已落库）。

## 本次会话交付：一键启动改造 —— 统一控制台 launcher.py
- **触发**：用户要求「一键启动改造」，选定方向=体验升级（统一控制台），并参照 `D:/Users/code_VIP/AI元年/skills/ai-year-launcher/SKILL.md`（AI元年一键启动改造模板 + 实战踩坑）。
- **改造前痛点**：启动弹多个窗口（前端独立 cmd）、`input()` 阻塞式交互、停止只能另跑 `scripts/stop_local.py`（taskkill /F 直接强杀）、依赖每次全量判断、健康检查失败无日志线索。
- **新 `launcher.py`（统一控制台）**：
  - 单窗口交互菜单：实时状态面板（4 服务彩色 运行中/未启动 + PID + 日志文件）+ [1]启动全部 [2]停止全部 [3]重启全部 [4]查看服务日志 [5]打开日志目录 [6]打开工作台 [7]刷新 [0]退出（服务存活）。
  - CLI 子命令：`start`（默认，一键链路后进控制台）/ `stop` / `restart` / `status`（exit code 反映全栈状态）；`start.bat` 已透传 `%*`。
  - 前端不再弹独立窗口：与后端一致 detached 后台（`DETACHED_PROCESS|NEW_PROCESS_GROUP`）+ 日志落盘 `.logs/frontend.log`（仍清空 `NODE_OPTIONS`）。
  - 停止策略升级：先 `taskkill /PID`（不带 /F）优雅关闭 → 2 秒后残留 `/F` 强杀 → `.run/*.pid` 兜底清理（吸收 skill 模板）。
  - 依赖增量检测：`.venv/.req_hash` 存 requirements.txt SHA256 前缀，哈希不变跳过 pip install，启动显著提速。
  - 健康检查超时：逐个打印未就绪服务日志尾部 15 行，崩因立现。
  - 按-端口按需启动：已运行的服务自动跳过（不再像 start_local.py 那样先全杀再起）。
  - netstat 解析按字节 capture 后 `decode(errors="ignore")`（GBK 坑）；ANSI 彩色在非 TTY 自动降级。
- **保持兼容**：exe 打包行为一致（frozen 路径解析）；`scripts/start_local.py`/`stop_local.py` 保留为开发者备用；后端子进程环境（.env 加载/PYTHONPATH/服务互连 URL/DEV_API_KEY）与 start_local.py 对齐。
- **验证**：`py_compile` 通过；真实环境 `python launcher.py status` 实测——4 服务全识别（8001/8002/8003/3001 + PID + 日志）；`tail_log` 实测正常。菜单交互与 stop/restart 需用户双击实测（沙箱会收割 detached 进程，见 skill 踩坑 #2）。
