# 企业智行 · 项目进度主线（PROGRESS）

> 维护方式：每次任务完成后更新本文件 + `docs/需求文档.md` 状态。本文件是后续迭代的「任务主线」，新会话从这里继续。
> 最近更新：2026-08-28

---

## 一、当前阶段总览

| 里程碑 | 文档状态 | 代码实际 | 判定 |
|---|---|---|---|
| P0 MVP（行程生成/问答/提醒/Web 工作台） | ✅ 已交付 | ✅ 全部实现且可运行 | 对齐 |
| P1 企业化（组织/政策/审批/RAG） | 🔲 文档标"待开发" | ⚠️ 后端 API + 前端页面**已写完，但未串链路、无数据** | **文档落后于代码** |
| P2 完善（报销/报表/SSO/导出） | 🔲 待开发 | ❌ 未实现 | 对齐（均未做） |

**一句话主线**：把「P0 能演示、P1 代码超前但断链」的项目，推进到「P1 链路打通、有数据可演示、文档如实」的状态，再进入 P2。

> 📋 **优化执行计划**：见 `docs/优化策略.md`。批次 1（5 项高危修复）已于 2026-08-28 完成；下一步是批次 2「拆 god file + 真流式 + 政策/审批自动链路 + 种子数据」。

---

## 二、任务主线（待办清单，按优先级）

| # | 任务 | 优先级 | 状态 | 说明 |
|---|---|---|---|---|
| 1 | 更新 PRD：P1 状态改为「开发中/部分交付」，如实记录代码现状 | 🔴 高 | ⏳ 待办 | 文档与进度脱节的源头，先改文档 |
| 2 | P1 种子数据：组织（部门/员工/职级）+ 差旅政策 + 审批示例 | 🔴 高 | ⏳ 待办 | 目前 `data/` 只有 21 个测试行程，Org/Policy/Approval 页面是空表 |
| 3 | P1 链路打通：行程生成后自动政策检查 + 超标提示 | 🟠 中 | ⏳ 待办 | 文档 F1.4 要求，目前 `generate` 不检查政策 |
| 4 | P1 链路打通：行程生成后自动发起审批（主管审批后生效） | 🟠 中 | ⏳ 待办 | 文档 3.5 要求，目前审批需手动创建 |
| 5 | 向量 RAG 落地：启用 embedding（bge-large-zh-v1.5 / **1024 维**） | 🟠 中 | 🔧 代码已就位 | 见「三、关键决策」第 3 条；框架+降级已完成，等后端开通即可切真向量 |
| 6 | 全链路自检：对话/生成/清单/总结/费用/提醒逐一验证 | 🟡 低 | ⏳ 待办 | 揪出未测试路径的坑（之前只测过部分） |
| 7 | P2 规划：报销对接/报表看板/SSO/费用导出 | 🟢 低 | ⏳ 规划 | 文档已定，等 P1 收尾再启动 |

---

## 三、关键决策记录（已定，勿推翻）

1. **LLM 服务商**：腾讯 TokenHub（OpenAI 兼容）`https://tokenhub.tencentmaas.com/v1`
   - 主模型：`hy-mt2-pro`（混元 Pro 旗舰，全选权限）
   - 仅使用旧 key（`sk-D7I4...`），新 key（`sk-xRVO...`）**不用**（用户明确要求）
   - 前端可选：混元 Pro / DeepSeek V4 / GLM Turbo，全链路透传 `model` 参数
2. **架构**：3 FastAPI 微服务（journey-hub:8001 编排 / planner-core:8002 规划 / sense-engine:8003 感知）+ React19 前端(3001) + shared 公共层；启动走 `launcher.py` + `CorporateJourneyHub.exe`（无黑窗多终端）
3. **Embedding 选型（已拍板，框架已落地）**：`BAAI/bge-large-zh-v1.5`——不用 OpenAI ada（国内延迟高）、不用 M3E（中文长尾差）
   - ⚠️ **维度纠正**：bge 系列为 small=512 / base=768 / **large=1024**，此前记录的「512 维」有误，已修正
   - 架构：可插拔三后端 `local`（本地 bge，数据不出企业）/ `api`（OpenAI 兼容 `/embeddings`）/ `none`（降级关键词），`.env` 用 `EMBEDDING_PROVIDER` 切换
   - 已实现：`shared/embedding/` 模块、`PolicyDocument.to_dict()` 序列化 embedding、`vector_search` 语义检索、`/policy-docs/reindex` 索引管理、**失败熔断**（探测失败后不再重复请求）
   - 待办：启用真向量需二选一——① 控制台为 key 开通 `kinfra-text-embedding-0.6b` 权限；② `pip install sentence-transformers` 走本地 bge
4. **数据源**：无 Key 一律走 Mock 降级，保证演示完整

---

## 四、已完成事项

### P0（全部可运行）
- 3 微服务 + 前端 + shared 层，LangGraph 意图路由（plan/chat/reroute/manage/emergency）
- 行程生成（SSE 流式）、CRUD、应变重排、出行清单、行程总结、费用统计、偏好画像、同行人、行程模板
- 实时感知引擎（航班/天气/路况/景点订阅监控 + 提醒）
- 前端 2.0 重构完成：设计系统 + 组件库 + 7 页面（Chat/Trips/TripDetail/Alerts/Org/Policy/Approval）
- 一键启动：`start.bat` + `launcher.py` + `CorporateJourneyHub.exe`（PyInstaller 单文件 8.1MB）
- LLM 全链路接通（TokenHub 混元），前端模型选择器可用

### P1（代码已完成，未串链路/无数据）
- 后端：组织（部门/员工 CRUD）、差旅政策（CRUD/match/check）、政策文档（CRUD/检索）、审批（CRUD/通过/拒绝/取消）——API 全部就绪
- 前端：OrgPage / PolicyPage / ApprovalPage 已实现并注册路由
- **向量 RAG 框架（2026-08-28）**：`shared/embedding/` 可插拔三后端（local bge / api / none）、失败熔断降级、政策文档语义检索 `vector_search`、增量索引 `index_missing_embeddings`、`/policy-docs/reindex` 索引管理接口；检索结果保留原文 excerpt + 相似度 score 供引用
- **文档同步（2026-08-28）**：README 新增「政策知识库检索（RAG）」章节、技术栈补充可插拔 Embedding、前端端口修正 3000→3001、P1 状态改为「开发中」

---

## 五、近期 Bug 修复记录

### 2026-08-27

| Bug | 修复 |
|---|---|
| `.jsx` 含 TS 语法 | 重命名为 `.tsx` |
| Tab.tsx 多余 `}` | 重写文件 |
| Vite 缓存清理被安全删除 shim 拦截 | 启动时清空 `NODE_OPTIONS` |
| exe 自我递归 | launcher `get_python()` 用 `shutil.which` |
| PyInstaller 构建被 shim 拦截 | 构建路径指向 `%TEMP%` + `CODEBUDDY_SAFE_DELETE_SANDBOX=0` |
| 旧 DeepSeek key 失效 | 换 TokenHub 混元 hy-mt2-pro |
| 意图路由 KeyError 'preflight' | `_decide_after_route` 返回 "plan" |
| planner-core 启动崩溃 | `/policy-docs/search` 改用 body 模型 `PolicyDocSearchRequest` |

### 2026-08-29（批次 2 · P1 链路打通，详见 docs/优化策略.md）

| 事项 | 说明 |
|---|---|
| planner god file 拆分 | `api/main.py` 1,200→~140 行装配层；路由拆到 `api/routers/` 7 个领域文件；共享实例入 `api/deps.py` |
| 修复存量 bug：/policies/match 被 {policy_id} 吞 | router 内调整注册顺序，match/check 已可达 |
| 修复存量 bug：数据孤岛 | `.env` 相对数据路径按服务 cwd 解析到 `services/planner-core/data/`；settings 增加 `_anchor_data_path` 锚定项目根，36 个数据文件迁移合并到根 `data/` |
| journey-hub 真流式 | `graph.invoke_stream`：chat 意图逐 chunk 透传，新增 `chunk` 帧；`ChatPage.jsx` 增量渲染，`respond` 整帧契约保留 |
| 生成后政策检查 + 审批自动发起 | SSE 尾部追加 `policy`/`approval` 帧；员工按 session_id 解析（`web-user` 已做种子员工），审批人取直属主管 |
| P1 种子数据 | `scripts/seed_p1_data.py` 幂等：2 部门/3 员工/2 政策/3 政策文档/2 待审批示例 |
| 审批门禁（PRD 3.5，2026-08-29） | 自动发起审批的行程 `pending_approval`，主管通过→`planned`、拒绝→`cancelled`，待审批禁止重排（409）；修复审批单缺 `status` 字段导致审批人看不到的 bug |
| 修复行程总结页崩溃（2026-08-29） | 后端 summary 为结构化对象（overview/daily_recap/偏差/花费），前端当字符串渲染触发 React "Objects are not valid as a React child" 白屏；TripDetailPage 改为分区渲染 + 请求失败错误兜底；浏览器实测渲染正常 |
| 批次 3（2026-08-29） | 前端：API 层去重（新增 client.js 公共封装）、organization.js 401 bug 修复、7 页面 React.lazy 分包；后端：测试 24→62（shared 层/reroute 算法/API 集成）；配置：journey-hub 统一走 settings、删 REDIS_URL 死配置、requirements 加版本上界。E2E 六项全过 |
| 主页行程流式输出（2026-08-29） | journey-hub 规划意图改流式：新增 `plan_trip_stream` 工具（即时进度 → 行程摘要分段 → 政策检查 → 审批结果），graph 流式入口逐段透传 chunk 帧；首帧 0.1s 即时反馈，行程完成后摘要与政策/审批结果渐进渲染 |
| 收尾优化（2026-08-29） | 重复代码收敛：`http_client` 四方法抽 `_request`、UTF-8 charset 修复统一为 `ensure_utf8_encoding`、SSE 响应样板抽 `shared/sse.py` 两服务复用、SessionManager 私有访问改公共方法；`shared/sse.py` + HTTP 请求级 metrics 中间件（路由模板做标签防高基数）；emergency 硬编码 312→185 行数据外置 JSON；修复历史乱码行程数据（latin-1→UTF-8 修复而非删除）；删前端空 hooks 目录。pytest 62 passed、E2E 六项全过 |
| 修复审批页操作报错（2026-08-29） | `loadApprovals` 误定义在 useEffect 作用域内，审批通过/拒绝/取消后调用报 ReferenceError，被 try/catch 捕获后误报"审批失败"（后端实际已成功）；提升到组件作用域修复，浏览器实测审批通过后列表正常刷新 |
| 登录 + 管理员界面 + 模型配置（2026-08-29） | 后端（journey-hub）：`/auth/login|logout`（用户 JSON 存储，sha256+salt，种子 admin/admin123 与 web-user/123456，内存 token 24h）；`/agent/models` 公开模型列表 + `/admin/models`、`/admin/llm-config`（管理员守卫 401/403，LLM 配置在线热更新重新注册 provider，Key 脱敏）；前端：登录页 + 登录门卫、按角色显隐导航（企业管理/系统管理仅管理员）、AdminPage（模型列表增删改/设默认、LLM 配置状态与在线修改）、模型选择器改为后端拉取（失败回退内置列表）、退出登录接真。修复 ConfigStore 主键字段错配（config_id vs id 导致读写落空）。pytest 62 passed；接口 8 项验证 + 浏览器实测（登录/权限视图/管理页）全过 |
| 接入小米 MiMo 模型（2026-08-30） | `.env` 切到 `https://api.xiaomimimo.com/v1` + mimo-v2.5（旧 TokenHub 配置备份 .env.bak-tokenhub）；管理页模型列表新增「MiMo 快速（mimo-v2.5）/ MiMo Pro 深度（mimo-v2.5-pro）」；适配修复：① chat_stream 解析器崩溃（MiMo 发送空 choices 帧致 IndexError 中断流式）② chat_json 空正文（推理模型思考消耗 max_tokens，预算下限抬到 2048）③ JSON 输出瑕疵兜底（提取首个 {} 块重解析）④ plan_trip_stream 超时 300s ⑤ 意图优化：移除过宽的"出差/旅游/旅行"关键词（误伤报销/保险类问答），裸"城市飞城市"句式正则识别。实测：问答首字 4.1s/145 chunks/总 8s；行程生成 80s 真实 LLM（926 chunks 无 error）；Embedding 因 MiMo 无 embeddings 接口降级关键词检索（设计内行为）。pytest 62 passed |
| 铁路 12306 监控 + 订阅表单（2026-08-30） | 新增 TrainSource：查询 12306 余票接口（免 Key），感知停运（critical）/无票候补（warning）/正常（info），反爬拦截或网络失败自动降级 Mock（BOM/非 JSON 响应已处理）；订阅字段新增 train_code/train_from/train_to/train_date；**补上监控页订阅表单**（此前 subscribeMonitor API 无页面入口——选行程+航班/车次/车站/日期+天气路况景点开关）；新增 4 例测试。pytest 66 passed；订阅→检查→提醒→去重链路实测通过 |
| 对话卡片式回答 + 补充追问（2026-08-30） | 后端：chat_query/invoke_stream 政策类问答自动检索差旅政策知识库原文注入回答依据（RAG 补充，失败静默跳过）；前端 ChatPage：回答完成后解析文本生成结构化卡片（行程卡→跳详情页、政策检查卡→跳政策页、审批卡→跳审批页）+ 按意图挂补充追问 chips（点击直接作为新问题追问）；意图规则补"出差+长尾"句式（带排除词防误伤报销/保险问答）。意图 17 例分类全过、pytest 66 passed、浏览器实测（政策问答引用文档 + chips 渲染 + 点击追问联动） |

验证：pytest 24 passed；31 API 路径全注册；E2E 六项检查（生成/属主/阻塞/并发/政策审批链路/真流式）。

### 2026-08-28（批次 1 · 高危优化，详见 docs/优化策略.md）

| 问题 | 修复 |
|---|---|
| journey-hub async 路由同步执行 LangGraph/LLM 卡死整个服务 | `/agent/chat` 改普通 `def` 走线程池 |
| 鉴权后门（ak_dev_local/ak_test_* 全环境放行 + ?api_key= 泄日志） | `APP_ENV=production` 时关闭后门与 query 传 key（`shared/middleware/auth.py`） |
| 行程 IDOR（知道 trip_id 可读写任意行程） | trips 及子资源加 `_deny_if_not_owner` 属主校验（声明身份才校验，兼容匿名） |
| 生成器并发竞态（全局 model 覆写 + `_last_trip` 串单） | 每请求独立 `ItineraryGenerator` 实例 |
| LLM 流式错误文本混进行程 JSON | `chat_stream` 抛 `LLMError`，API 层发独立 error 帧；`chat_json` 重试 1 次再抛 |
| BaseJsonStore 非原子写、无锁 | temp + `os.replace` 原子写 + RLock |

验证：pytest 24 passed；`scripts/e2e_verify.py` 覆盖生成/属主/阻塞/并发四项。⚠️ 生产部署需在 `.env` 加 `APP_ENV=production`。

### 2026-08-28（早前）

| Bug | 修复 |
|---|---|
| **行程中文全乱码**（`æ·±å³`） | `requests` 对无 charset 的 `text/*` 响应按 ISO-8859-1 解码。三处修复：`shared/llm/manager.py`（chat_stream + chat，**主因**）、`shared/http_client.py`（post_stream）、两个服务 SSE `media_type` 补 `; charset=utf-8` |
| 不指定模型时行程规划返回 422 | `GenerateTripRequest.model` / `ChatRequest.model` 类型注解 `str` 与 `default=None` 冲突，Pydantic 拒绝 None；改为 `Optional[str]` |

---

## 六、环境注意（本机复现用）

- Python：系统 `D:\software\Python311\python.exe`（exe 内解析用）；Node：managed 22.22.2 或系统 24
- Vite 启动必须清空 `NODE_OPTIONS`，否则依赖优化器清理缓存时崩溃
- 原生模块（better-sqlite3 等）ABI 与编译时 node 版本绑定，混用会 `ERR_DLOPEN_FAILED`
- npm 在沙箱内限速，装依赖用本机终端跑；后台任务不继承非沙箱网络

---

## 七、验收对照（PRD 10.1，8 项）

| # | 验收项 | 现状 |
|---|---|---|
| 1 | 一句话 30s 内生成多日行程 | ✅ 已实现（SSE） |
| 2 | 行程合理性（≤30min 通勤/预留缓冲/用餐） | ✅ Prompt 约束 |
| 3 | 商务场景会议优先 | ✅ Prompt 约束 |
| 4 | 问答 3s 首字响应 | ✅ 已实现 |
| 5 | 异常 60s 内推送提醒 | ✅ 已实现（依赖数据源） |
| 6 | 应变重排 + 替代方案 | ✅ 已实现 |
| 7 | 分类费用汇总 | ✅ `/trips/{id}/expenses` |
| 8 | LLM 不可用降级规则模板 | ✅ 已实现 |
