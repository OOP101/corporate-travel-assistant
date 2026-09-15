# 企业智行 Corporate Journey Hub · 进度主线 (PROGRESS)

> 跨会话主线追踪。每次会话开始先读本文件接着干，完成后更新它。
> 跨会话约定/决策见工作区记忆（本地文件 `.workbuddy/memory/MEMORY.md`，不入库）。

## 阶段总览
- **P0（可运行）**：✅ 完成 —— 3 服务（journey-hub 8001 / planner-core 8002 / sense-engine 8003）+ React 前端 3001 可跑通。
- **P0+（运行形态）**：✅ 完成 —— **单体模式（services/gateway 装配，单进程单端口 8001）+ 总控台**；微服务模式一键切换（2026-09-10）。
- **P1（企业化闭环）**：✅ 交付 —— 组织/政策/审批/政策文档 后端+前端写完、串链路、有种子数据；生成→政策检查→自动审批→门禁闭环；实时数据「查询直查 / 推送走监控」已落地（2026-09-03）。
- **P2（深化）**：🟡 进行中 —— 报销 / 报表 / 导出 ✅；SSO / 真向量 RAG 阻塞；**行程规划对话流 v2 已落地（2026-09-10，见下节）**；**景点攻略语料通道 + 个人出行政策短路已落地（2026-09-15，见下节）**。

## 本次会话交付：文档冗余清理（方案 A）+ 根目录杂物（2026-09-15 下午）
- **文档冗余清单（`docs_企业智行/10`）按方案 A 执行完毕**，文件改名 `10-文档冗余清单（已执行方案A）.md`：
  - **归档 `05`（旅行智脑落地补齐清单）/ `09`（TripStar 形态简历表述）** → `_archive/`（两份的"另建 C 端项目"前提均已被 07 号结论否决；`docs_企业智行/` 本就在 .gitignore，纯本地移动）；
  - `docs_企业智行/README.md`：目录表标注归档与 06 降级引用；修正记录第 3 条补"3 条事实已由 2026-09-15 身份大修解决"；新增「最新交付速览（2026-09-15）」节（身份大修/注册、监控持久化、景点语料、入口收敛、启动清对话、177 测试基线）；
  - `02-简历表述.md` 顶部加📌指向 `docs/简历项目经历-企业智行.md` 为唯一简历权威（02 定位降为面试问答素材库）；`03-后续优化.md` 顶部加📌指向 `docs/PROGRESS.md` 为唯一进度权威（03 是合并快照会持续落后）。
- **根目录清理**：
  - `nexus_demo.py`（Nexus-Ω 认知引擎 demo，24KB，与本项目无关、全仓零引用）→ `git rm`，先备份到 `.backup/root-cleanup-20260915/`；
  - `bench_models.json` / `bench_models_fixed.json` **保留** —— 核实后确认是 `scripts/bench_trip_models.py` 实测结果，被简历权威版引用作抗打假证据（证明"1.3 秒首字"为假），不能删。

## 本次会话交付：启动自动清「对话」但保留「数据」（2026-09-15）
- **需求**：用户原话"我要的只是项目启动之后的首页不要有上一次的对话记录，行程保留即可"。此前 `清空数据` 是**整体大扫除**（行程/审批/报销/画像/监控订阅/日志/缓存全清），与"只想首页干净"是两回事 —— 本次把两者彻底分开。
- **两个独立开关**：
  - **清对话（默认开，每次启动自动做）**：清 localStorage 快照 + 服务端会话历史，**行程/审批/报销/画像一律保留**。
  - **清数据（手动）**：`launcher.py clean|fresh`，整体重置，对话会一并清。
- **前端**（`frontend/src/store/chatStore.js`）：`?fresh=1` 时除丢 `cjh_chat_*` 快照外，新增 `SKIP_SERVER_HISTORY` 标记 → `hydrate()` 跳过服务端历史兜底（否则清完前端又被服务端旧历史回放）。原逻辑只在"干净启动"触发，现为**每次启动**都带该参数。
- **后端/启动器**（`launcher.py`）：
  - `open_browser(reset_chat=)` 取代 `open_browser(fresh=)`；`?fresh=1` 的语义收敛为**只清对话**（函数名与注释同步更正）。
  - 新增 `reset_chat_history(mode)`：`GET /agent/sessions` 列出活跃会话 → 逐个 `POST /agent/session/{id}/clear`，清服务端内存历史。**服务不可用/鉴权失败静默跳过**，绝不阻断启动。
  - 新增 `_dev_api_key()`：从 `DEV_API_KEY` 环境变量或 `.env` 读取鉴权 key（与前端 `X-API-Key` 同源）—— **踩坑**：这两个端点受 `APIKeyMiddleware` 保护，不带 key 直接 401，第一版漏了 header 会静默失效。
  - `one_shot_start()` 移除已废弃的 `fresh` 形参，改为 `reset_chat=True`（默认清对话）；`fresh_start()` 同步清理。
  - 新增 `--keep-chat`（命令行开关）：本次启动不清对话，调试时保留上次对话可用；参数在解析前先摘除，避免被误当 action/mode（实测 `micro --keep-chat` 曾把 mode 解析成 single，已修）。
- **测试**：新增 `tests/test_chat_reset.py`（7 例）—— 锁定 `_dev_api_key` 非空/优先环境变量/回落默认值、`/agent/sessions` 响应结构、按会话选择性清空（清 alice 不误伤 bob）、不带 key 401、服务不可用时静默 no-op。**基线 170 → 177 passed / 0 failed**。
- **README**：4.2 表补"只清上次对话"说明；新增 **4.3「启动时清对话 vs 清数据」** 对照表，讲清两个开关的边界。

## 本次会话交付（收尾）：启动入口收敛为 start.bat + 停止.bat（2026-09-14）
- **需求**：根目录只留「一个启动、一个停止」，三个服务默认合并为一个进程。用户原话："只要一个启动一个停止，三个服务默认启动为一个"。
- **默认单体已成立**：`launcher.py` 的 `DEFAULT_MODE = MODE_ALIASES.get(os.getenv("CJH_MODE","single"), "single")`，无需改代码——双击 `start.bat` 不带参数即为单进程单端口 8001。
- **删除 3 个 bat**：`总控台.bat` / `干净启动.bat` / `清空数据.bat`（`git rm`）。功能未丢，收进命令行：`python launcher.py menu`（常驻菜单）/ `clean`（清数据）/ `fresh`（干净启动）。
- **保留 4 个 bat 及理由**：`start.bat`（启动入口）/ `停止.bat`（停止入口）/ `一键更新.bat`（出 EXE 分发包，保留）/ `build_exe.bat`（**被 `scripts/rebuild_and_restart.py:82` 代码调用**，不能删）。
- **清理引用**：`launcher.py` docstring 去重 + 去 `总控台.bat` 引用 + 写明"三个服务默认合并为一个进程"；两处提示文案改为指向 `停止.bat` 与命令行；`README.md` 4.2 节整段重写（六脚本表 → 两入口表 + 命令行等价写法），4.1 节去掉"一个总控台"措辞。
- **⚠️ 顺带修掉一个编码隐患**：四个 bat 此前**全是 LF 行尾**，且 `start.bat`（我上轮加的"停止.bat"引用）与 `一键更新.bat`（原有中文 echo）**含非 ASCII 字符**——违反项目铁律（cmd 按 GBK 解析中文易乱码）。已全部规整为 **CRLF + 纯 ASCII**（`一键更新.bat` 的中文 echo 改为英文），复验：`start/停止/一键更新/build_exe` 均 `bareLF=0 / pureASCII=True`。

## 本次会话交付：固化未提交成果 + 更正两处落后记录（2026-09-15）
- **背景**：init commit 之后全部工作（38 文件 / +1961 行）一直堆在工作区未提交，`PROGRESS.md` 却把功能都标成"已交付"——git 里没有对应 commit，误操作即无回退点。本次拆成 7 个语义化提交固化：`dacbdee` 启动基建 → `6cdc1e6` 单体网关 → `7585ec7` 语料层 → `0184c69` 对话流 v2 + 场景化规则 + 政策短路 → `70102f2` 测试同步 → `b97ca83` 文档 → `da6c69a` 仓库卫生。**全部只在本地，未推送**（远端 `origin/main` 仍为 `d7ee0fd`）。
- **更正 ①：景点知识库不是待做项，已经落地。** 此前一份「改 C 端」可行性评估把「新增景点知识库」判为成本大头/待做项，实际代码里已完成：
  - `shared/store/document_store.py::DocumentCorpusStore` —— 把政策文档的「关键词 + 语义」双路检索抽成通用基类，`PolicyDocumentStore` 改为继承（`store/org_store.py` -129 行），两路检索只留一份实现。
  - `services/planner-core/store/guide_store.py::TravelGuideStore` + `api/routers/guides.py`（CRUD / `POST /guides/search` / `POST /guides/reindex`），与政策文档**分开存储**（`data/org/guide_docs` vs 政策文档目录），避免企业政策与个人出游内容混进同一检索空间。
  - `generators/itinerary.py` 已消费该语料（`guide_store.index_missing_embeddings`），为个人出行提供景点门票 / 建议游玩时长 / 预约要求 / 避坑提示等内容依据，不再"只有日程没有内容"。
  - 测试：`tests/test_guide_corpus.py`，含 `test_no_guides_for_business_scene`、`test_retrieve_guides_for_personal`、`test_two_corpuses_do_not_mix` 等场景隔离与不混库用例。
- **更正 ②：方案 C 的 P0「个人出行政策短路」已完成。** 07 号文档判定这是「P0 必做项」（当时结论：`_match_policy` 对非员工取 `level=""`，`get_by_level()` 会把 `level==""` 的通用政策 `pol_139be3c19e59` 纳入候选，**政策预检照样跑**）。现已在 `routers/trips.py:68` 落地：
  - `_POLICY_EXEMPT_SCENES = {"personal"}`；`_policy_exempt_reason()` 同时门控 `_policy_preview()`（生成时预检）与 `_confirm_policy_flow()`（确认后政策检查 + 发起审批），personal 场景两处均直接跳过。
  - 覆盖用例在 `tests/test_json_repair_and_policy.py`：`test_personal_scene_is_exempt_even_for_employee`（员工选个人出游同样豁免）/ `test_non_employee_is_exempt` / `test_business_scenes_still_checked_for_employee` / `test_policy_preview_skipped_when_exempt` / `test_confirm_flow_skipped_when_exempt`。
- **仓库卫生**：`.env.bak-tokenhub`（环境变量备份，含第三方 TokenHub key）随 init commit 推到了公开仓库 `github.com/OOP101/corporate-travel-assistant`。已 `git rm --cached` 并在 `.gitignore` 加 `.env.bak-*` 模式堵住同类备份。**移除只对分支 tip 生效——历史提交中仍能检出该文件**：本次未重写历史（该 key 已轮换失效）；若换成仍在用的凭据，须 `filter-repo` + 强推才能彻底剥离。另有一批仅本地使用的材料目录一并移出版本控制（本地文件保留）。
- **测试基线更新**：`pytest --basetemp=./.pytest_tmp` → **103 passed / 0 failed**（此前记录的 67 已过时）。

## 本次会话交付（架构）：三服务合并 · 单体模式 + 总控台（2026-09-10 晚）
- 需求：三个后端合并、一个总控台（含停止）。做法：**保留三服务代码与路由，新增装配层网关**，一套代码两种运行模式。
- **新增 `services/gateway/main.py`（统一网关 · 单体模式）**：
  - 以别名包（`jh_api` / `pc_api` / `se_api`）在同一进程加载三个服务的 FastAPI app，规避三服务同名顶层 `api` 包冲突；
  - `AsyncExitStack` 依次进入三份 lifespan（journey → planner → sense），journey 的 `app.state`（user_store/config_store/llm_manager）同步一份到网关；
  - 路由装配：`/planner`→策程、`/sense`→感知、`/`→行智兜底；对外**单进程单端口 8001**；新增 `GET /` 服务索引（列出三条业务线前缀与各自 docs）；子服务 `/planner/docs`、`/sense/docs` 加入免鉴权白名单。
  - 服务间互调仍走 HTTP：`PLANNER_SERVICE_URL=http://127.0.0.1:8001/planner`、`SENSE_SERVICE_URL=.../sense`，编排逻辑零改动。
- **相对导入化**（同进程共存前提，微服务模式与测试不受影响）：journey `api/main.py`+`api/admin.py` 3 行、planner `api/main.py`+9 个 routers 共 10 行，`from api...` → `from . / .. import ...`；已 grep 确认无残留绝对 `api` 导入。
- **launcher.py 双模式 + 总控台**：`SINGLE_BACKENDS`（网关 8001）/`MICRO_BACKENDS`（8001/8002/8003）；`start|menu|restart|status` 支持 `single|micro`（默认 single，`CJH_MODE` 可覆盖）；网关入口 `main:app`、微服务 `api.main:app`；`stop` 覆盖两模式全部端口不留孤儿；`status` 附「其他模式端口仍监听」提示；菜单改为 8 项（①单体启动 ②微服务启动 ③停止全部 ④重启当前模式 ⑤日志 ⑥日志目录 ⑦工作台 ⑧刷新），切换模式前自动先停。
- **前端 `vite.config.js`**：默认单端口 8001 —— `/api/journey`→`/`、`/api/planner`→`/planner`、`/api/sense`→`/sense`；`CJH_MODE=micro` 时自动回退三端口直连（launcher 启动前端时会注入该变量，保证与后端模式一致）。
- **新增/更新双击入口**：`总控台.bat`（常驻总控台，含停止）、`控制台.bat`（别名）、`停止.bat`、`start.bat`（默认单体启动后自动收窗）。
- **实测（全过）**：单体模式 `/health`、`/`、`/planner/health`、`/sense/health`、`/planner/trips`、`/sense/monitor/status`、`/docs`、`/planner/docs`、`/sense/docs`、`/agent/sessions` 均 200；真实 LLM 链路「我下周要去深圳」→ clarify（journey→网关 `/planner` 前缀转发通）；「商务出差 9/25-9/26 上海拜访客户」→ 草案 business/上海/2天 → 确认前 0 条 → `POST /agent/plan/confirm` → 落库 1 条 + 政策检查通过；Vite 代理单/微两种模式分别验证 200；微服务模式三端口与对话链路同样通过；全量 pytest 26 passed（3 个 `test_shared_http_client` 失败为既有环境问题，与本次无关）。
- 说明：`docker-compose.yml`、各服务 Dockerfile 仍按微服务模式，未改动。

## 本次会话交付（重大）：行程规划对话流 v2 落地（PRD → 代码全链路）
- 依据 `docs/PRD-行程规划对话流程-v2.md` §9 完成 P1+P2+P3 全部改造，**澄清 → 草案 → 确认 → 落库审批** 四态闭环，审批绝不先于用户确认。
- **planner-core `generators/itinerary.py`**：
  - extract prompt 重写：示例即「未提及=null」，删除 days=3/budget=5000/cultural 等诱导默认值；新增 `scene`（business/meeting/visit/team/personal）与 `purpose` 抽取。
  - `_extract_params` v2：取值优先级 **explicit（确认页显式参数）> LLM 本轮 > carry（澄清轮次续用，治多轮上下文丢失）**；必填（scene/destination/start_date/days）缺失返回 missing 不得生成；可代填字段（人数=1/预算=按差旅标准/出发地）兜底并记 `defaulted[]`。
  - `PLANNING_RULES` 按 scene 拆分：`planning_rules(scene)` 动态拼装；**business/meeting/visit 禁景点**、meeting 布撤展缓冲、personal 保留旅游节奏（`PLANNING_RULES` 常量兼容保留）。
  - `build_clarify_question`：确定性澄清话术（PRD §6.2 模板），不依赖 LLM。
- **planner-core API `routers/trips.py`（三态契约）**：
  - `POST /trips/generate` 改为草案语义：新增 `params`（显式）/`carry`（续用）入参；缺参发 `{"event":"clarify","missing":[...]}` 不生成；生成后**不落库不审批**，政策只预检（`policy` 帧），发 `{"event":"draft","trip","defaulted","params"}` 帧。
  - 新增 `POST /trips/confirm`（S4→S5）：确认后才落库 + 政策检查 + 审批发起（`_confirm_policy_flow`），审批备注附 scene/purpose；需审批置 `pending_approval`。原 `_post_generate_policy_flow` 拆为 `_policy_preview`（只查不批）+ `_confirm_policy_flow`（可批）。
- **journey-hub**：
  - `handlers.py`：`plan_trip_stream` 消费 clarify/draft 帧并新增 `_format_draft_summary`（草案确认摘要：场景/日期/预算/[代填]标注/酒店建议/每日骨架/确认引导）；新增 `confirm_trip`（调 planner /trips/confirm，聚合政策+审批结果文案）。
  - `state/graph.py`：会话阶段机存 `SessionManager.metadata.plan_stage`（clarify/confirm）；clarify 阶段用户答案直通规划；confirm 阶段「确认」→ `_confirm_pending_draft`（发 `trip_saved` 帧）、「取消」→ 终止、其他 → 修改重生成；clarify 帧写 `plan_carry` 供下轮续用。SSE 新帧：`clarify`/`confirm`/`trip_saved`。
  - `api/main.py`：新增 `POST /agent/plan/confirm`（前端确认卡按钮用）；注册 `confirm_trip` 工具。
- **前端**：
  - 新组件 `components/Molecules/TripConfirmCard.jsx`（ChatPage/TripsPage 共用）：场景徽标+日期天数+目的地+人数+预算（[代填] 标注）+酒店建议（`hotel_options` 主选/「换一家」下拉，真实 POI，价格以预订平台为准）+每日骨架（上午/下午/晚间摘要）+政策预警条（可仍然提交）+确认/改参数/取消；`applyHotel` 把选中酒店写回草案。
  - `chatStore.js`：处理 clarify/confirm/trip_saved 事件；新增 `confirmDraft`（调 /agent/plan/confirm）/`cancelDraft`/`editDraft`（回填原需求）；assistant 消息留底 `query`；草案/澄清态不追加常驻追问。
  - `ChatPage.jsx`：澄清 chips（场景五选项 + 「你看着办，按常见差旅默认补全」授权入口）；确认卡内嵌气泡下。
  - `TripsPage.jsx`：生成表单新增**场景下拉（必选）**；clarify/draft/policy 事件处理；横幅内嵌确认卡，确认走 planner `/trips/confirm`。
  - `api/planner.js`：`generateTripStream` 支持 `params`；新增 `confirmTrip`；`api/journey.js` 新增 `confirmTripPlan`。
- **测试**：`tests/test_planner_api.py` 全量改新契约（generate=draft 不落库 → confirm 落库），新增 `test_confirm_rejects_invalid_draft`；**10/10 通过**（运行用 `--basetemp=./.pytest_tmp`，避开 pytest 临时目录网络路径清理报错的既有环境问题）。
- **实测冒烟（真实 LLM hy-mt2-pro，全过）**：
  - U1「我下周要去深圳」→ `clarify missing=[scene,days|start_date,days]`，不再臆造生成；
  - U2 续答「商务出差，9月15号到9月16号，拜访华强北客户」→ carry 续用 destination=深圳 → 草案 business/深圳/2天/代填出发地；
  - 草案确认前列表 count=0（未落库）；confirm 后 count=1 + 政策检查；非员工不误发审批；
  - 文本「确认」→ `trip_saved trip_c892d1c19633`（广州工厂考察之行，标题无「之旅」措辞）。
- **排障记录**：①沙箱收割 launcher detached 进程 → 用工具级后台任务跑 `scripts/fg_service.py`；②本机系统代理劫持 localhost → 请求加 `trust_env=False`；③`ServiceClient.post()` 无 timeout 参数导致确认失败 → 去掉该传参；④首次冒烟发现澄清轮次 destination 丢失 → 设计 carry 三层取值修复。
- 待用户 vite 实测：聊天缺参反问 → 点场景 chips → 草案确认卡（换酒店/确认/改参数）→ TripsPage 场景下拉 + 确认卡。

## P2 交付清单

| 模块 | 状态 | 说明 |
|---|---|---|
| 行程单导出 (export) | ✅ 已完成 | 后端 `GET /trips/{trip_id}/export` 渲染打印友好 HTML；前端「导出行程单」按钮 → 浏览器打印/另存 PDF。零依赖（不装 python-docx）。 |
| 报销 (reimbursement) | ✅ 已完成 | 提交（自动算额+按直属主管指派审批人）/ 审批 / 打款；前端「报销管理」页。 |
| 报表 (report) | ✅ 已完成 | overview / by-department / by-month 只读聚合；前端「报表中心」页（KPI + 部门/月度表）。 |
| 景点攻略语料 (guides) | ✅ 已完成 | `TravelGuideStore` + `/guides`（CRUD / search / reindex）。与政策文档共用 `DocumentCorpusStore` 双路检索能力，但**分开存储**（`data/org/guide_docs`）；供 `personal` 场景的行程生成提供景点内容依据。 |
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

## 本次会话交付：交通方式选择（v2.1，默认飞机 + 卡片可选）
- **需求**：澄清/确认交互升级为选项卡片式；新增城际交通方式（飞机/高铁/自驾，默认飞机，需可选）。
- **现状确认**：场景选择已实现为澄清 chips（ChatPage）+ 表单下拉（TripsPage）；本次缺口=交通方式不在参数体系。
- **后端** `services/planner-core/generators/itinerary.py`：
  - 新增 `_TRANSPORT_NAMES` / `_TRANSPORT_ALIASES` / `normalize_transport()`（中英文别名 → airplane/train/drive）。
  - `_build_extraction_prompt` 增加 `transport` 字段（未提及=null，不猜）。
  - `_extract_params`：params 增 `transport`（pick 链：explicit > LLM > carry）→ 归一化 → 缺省兜底 `airplane` 并记入 **defaulted [代填]**（"默认飞机，确认页可更换"）。
  - `_build_generation_prompt` 参数块注入「交通方式」行 + 规划约束（飞机=航班机场衔接 / 高铁=车次车站衔接 / 自驾=里程与驾驶时间）。
- **前端**：
  - `TripConfirmCard.jsx`：新增「交通方式」卡片选择区（飞机/高铁/自驾 chips，当前值高亮）；确认时经 `applyChoices()` 写回 `trip.transport` 随确认提交；`DEFAULTED_LABELS` 加 transport。
  - `TripsPage.jsx`：生成表单新增交通方式下拉（ModalForm `initialValues={{transport:'airplane'}}`），显式参数带上 transport。
- **链路确认**：req.params(explicit) → generate_stream → _extract_params(explicit=) 已通；确认提交走 trip dict 原样落库，transport 自然携带。
- **验证**：py_compile OK；Python 冒烟（归一化 5 例 + 无 LLM 抽取默认 airplane + 代填记录 + 缺参澄清）PASS；临时 Vite(3019) 转换冒烟 TripConfirmCard/TripsPage/ChatPage/chatStore 全 200，已停。待用户在正常启动的前端实测点选。

## 关键约束（勿推翻）
- LLM：小米 MiMo 为 `.env` 默认 provider；多模型经 admin `default_model=hy-mt2-pro` 走 TokenHub 网关（mimo/hy/deepseek/glm 经 model_id 路由）。
- Embedding：`BAAI/bge-large-zh-v1.5`（1024 维）；`EMBEDDING_PROVIDER` 切换 local/api/none，当前 none（关键词降级）。
- 服务启停：**`launcher.py` 统一控制台**（一键启动/停止/重启/看日志，支持 `stop|restart|status` 子命令）；`scripts/fg_service.py <journey|planner|sense>`（前台单服务调试）；`scripts/start_local.py` 仍可用于后台批量启动（沙箱内 netstat 有时无输出，需手动 `netstat -ano|grep :PORT` + `taskkill /F /PID`）。
- 前端 2.0 已重构，改前端先读 `src` 现状，别推翻设计系统。
- 沙箱坑：Vite 启动需清空 `NODE_OPTIONS`；PyInstaller 构建路径指 `%TEMP%`；`taskkill` 经 Git Bash 参数会被吞，用 Python `subprocess.run(['taskkill','/F','/PID',pid])`。

## 下一步建议
1. 用户在 vite 上实测：①聊天生成行程后切菜单再切回（对话/行程卡片应保留）；②生成过程应看到「已生成 X 字」进度 + 人话摘要打字机输出；③「清空会话 / 新对话」后刷新页面仍为全新对话；④「导出行程单 / 报销管理 / 报表中心」页面交互。
2. 服务端历史仍为进程内，重启即空（跨刷新持久靠 localStorage 快照）。
3. P2 剩余项均受外部条件阻塞：SSO 等外部 IdP；真向量 RAG 需开通 embedding 权限或 `pip install sentence-transformers`（`BAAI/bge-large-zh-v1.5`，1024 维）。
4. 可选深化：报表加时间范围过滤（?from=&to=）、导出 CSV/Excel、报销按费用类目透视。
5. **改 C 端四项 P0：全部完成 ✅**
   - ✅ **身份贯通**（已落地）：`shared/middleware/session.py` 新增 `SignedSession`；`api/routers/profiles.py`/`templates.py`/`trips.py` 全部改用 `deps.resolve_user_id(request, …)`，经 `deps.declared_user_id()` 读 `Authorization: Bearer` → username，未登录才回落显式 `session_id` / workspace。
   - ✅ **Token 持久化**（已落地）：`AuthService` 由进程内 `_tokens: dict` 改为无状态签名 token（`issue()`=`SignedSession.encode`，`resolve()`=`SignedSession.decode`），服务重启不掉线；改 `SESSION_SECRET` 即可让全部在途 token 失效。新增 `SESSION_SECRET`（留空回退 `DEV_API_KEY`）。
   - ✅ **自助注册**（已落地）：新增 `POST /auth/register` —— 注册即签发 token（注册即登录）。用户名 `3-32 位 [A-Za-z0-9_.-]`、大小写不敏感查重；`admin`/`web-user`/`default` 列为保留名（与组织侧 `employee_id` 同值，放开会继承他人档案与行程）；**角色不接受客户端指定**，新账号一律 `user`。前端 `LoginPage` 增登录/注册双模式。见 commit `0ba1df7`。
   - ✅ **个人出行政策短路**：见上节「更正 ②」。

6. **口令哈希升级（随注册一并落地）**：`UserStore` 由单轮 `sha256(salt+password)` 改为 **pbkdf2-sha256（12 万轮）**，标准库实现免额外依赖；写入带 `algo` 标记，旧记录仍可验证并在登录成功时**自动升级**；哈希比对改用 `secrets.compare_digest` 防时序侧信道。

7. **测试基线（2026-09-15）**：`./.venv/Scripts/python.exe -m pytest --basetemp=./.pytest_tmp -q` → **150 passed / 0 failed**（121 → 150，新增 `tests/test_register.py` 29 例）。

8. **文档冗余清单**：新建 `docs_企业智行/10-文档冗余清单（待决策）.md`（**只列不动，待拍板**）。核心结论：`docs/` 全保留；`05`（TravelAI 补齐清单）/`09`（C 端简历模板）前提已被否决、建议归档；`06` 两处结论已被 07 推翻；`README.md` 修正记录需更新；pptx 基于 8/30 旧版已过期。另发现**简历口径双源**（`02-简历表述.md` vs `docs/简历项目经历-企业智行.md`）与 `03` 持续落后 PROGRESS 两个风险。

9. **修复实时监控失效（2026-09-15）**：用户报「启动了也不能实时监控」。排查确认进程非崩溃而是被沙箱回收（`gateway.log` 无 traceback），真正的缺陷是**订阅与提醒均为纯内存态**——`SenseEngine._subscriptions` 与 `AlertManager._alerts` 服务一重启即清空，`check_all()` 走 `if not trip_ids: return` 空转，"执行成功"的日志实为假象。
   - 修复：新增 `sense_data_dir`（`data/sense`）；订阅表 + 状态缓存落盘 `data/sense/monitor/`、提醒落盘 `data/sense/alerts/alerts.json`（含 `delivered`）；均原子写（`tempfile`+`os.replace`），启动回灌，损坏数据只记日志不阻断；`SenseEngine` 加 `RLock` 保护调度线程与请求线程并发；单行程提醒上限 200 条防膨胀；`reset_data.py` 纳入 `data/sense`。
   - 验证：新增 `tests/test_sense_persistence.py` 20 例；HTTP 层实测「订阅 → 检查 → 提醒 → 重启 → 订阅与提醒均保留」。**全量 170 passed（150 → 170）**。
   - ⚠️ 排查陷阱：mock 数据源每次返回**随机结果**，会让 `check_all` 持续产出新提醒——这是 mock 特性而非去重失效（稳定数据下实测 1,0,0 正确）。

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

## 本次会话交付：运行数据一键清空（干净启动）
- **触发**：用户反馈「项目每次初步启动老是留着上一次的缓存，希望全部清除，所有行程记录」。
- **根因**：`launcher.py` 只做"启动"，从不清理运行态数据——本次实测清理前堆积：`data/trips` 102 份行程、`data/test_trips` 144 份、`data/org/approvals` 28 条审批、报销 1 条，另有 `.logs`（约 400KB）、`.run`、31 个 `__pycache__`、Vite 预构建缓存；前端侧还有 localStorage 对话快照 `cjh_chat_web-user` ——「上次的缓存还在」是服务端文件 + 浏览器快照两处叠加。
- **新增 `scripts/reset_data.py`**（仅标准库，可独立运行）：
  - `--scope runtime`（默认）：清 `data/trips`、`data/test_trips`、`data/org/approvals`、`data/org/reimbursements`、`data/profiles`、`.logs`、`.run`，并递归清 `__pycache__` / `.pytest_cache` / `.pytest_tmp` / `frontend/node_modules/.vite` / `frontend/dist`；目录类目标清完重建空目录。
  - `--scope full`：额外清组织/员工/政策/政策文档/模板，配 `--reseed` 清完自动重灌 `seed_p1_data.py`。
  - **永不清**：`data/system/`（大模型 provider、管理员与用户配置）、`.env`、源码 —— 清了要重新配 key。
  - 安全：默认先把目标**整体 move 到 `.backup/reset-<时间戳>/`**（保留最近 3 份，可回滚）再删；`_guard()` 拒绝 BASE_DIR 之外路径；文件被占用只跳过该目标并提示先停止，不中断其余；`--dry-run` 预览、`--no-backup`、`--json`。
  - 输出按类别分组汇总（几百条行程不再糊屏）。
- **`launcher.py` 封装三个入口**：
  - `clean`（= `清空数据.bat`）：先 `stop_if_running()` 释放文件占用 → 交互确认 → 清理。
  - `fresh`（= `干净启动.bat`）：停止 → 清空 → 正常启动，且工作台 URL 带 `?fresh=1`。
  - **自动清空**：标记文件 `.cjh_fresh`（内容 runtime|full）。存在时 `one_shot_start()` 启动前自动「停止→清理→启动」，并把 `fresh=True` 传给 `open_browser()`。总控台菜单新增 `[9] 清空运行数据`、`[10] 干净启动`、`[11] 每次启动自动清空：开/关`。
- **前端**：`store/chatStore.js` 模块加载时检测 URL `?fresh=1` → 丢弃 localStorage 对话快照（仅清对话缓存，不动 `cjh_auth` 登录态），随后 `history.replaceState` 摘掉参数，避免后续手动刷新被误清。解决"后端清了、前端还显示旧对话"。
- **`.gitignore`**：补 `.backup/` 与 `.cjh_fresh`。
- **验证**（真机冒烟，全部 PASS）：
  1. `reset_data.py --dry-run`：runtime 312 项 / full 327 项，分类计数正确，`data/system` 未入列。
  2. `launcher.py clean`：312 项清理、**0 跳过**；复核 `data/trips|test_trips|approvals|reimbursements|profiles|.logs|.run` 全为 0，`data/system/{config,users}`、org 种子（3/3/3/5）完整；备份 `.backup/reset-20260910-202729` 10MB 结构正确。
  3. 自动清空链路：放入假行程 `trip_zzz_should_be_cleared.json` → `launcher.py start` → 清空 7 项 → 服务就绪（8001 4.9s / 3001 6.4s）→ 工作台 URL 确认为 `http://localhost:3001/?fresh=1`。
  4. 修复缺口：自动清空路径原先 `fresh` 仍为 False（URL 不带参数），已在 `run_reset` 后置 `fresh = True`。
- **默认状态**：`.cjh_fresh` 已写入（用户要求"每次启动都清"），总控台按 `[11]` 或删除该文件即可关闭。
- **注意**：清理需在服务停止后进行（先 stop 再删），否则日志句柄占用会被跳过——`clean`/`fresh` 已内置自动停止。
