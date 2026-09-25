# 企业智行 v3 重构蓝图 —— Agent 原生架构（2026-09-25 立项）

> 缘起：用户对 v2「三层微服务 + 10 个 CRUD 路由」的架构叙事不满意——业务内核被写成了传统企业后端，
> 政策/攻略这些能力本该是 Agent 可外接的服务。v3 从 PRD 需求原点推倒重来。
> 安全网：重构前全量封存于 tag `pre-refactor-20260925`（commit c9d522b），随时可回滚。

---

## 一、需求原点（不变的铁律，来自 PRD v2）

1. 场景由用户选择（business/meeting/visit/team/personal），系统不得擅自假设；
2. 必填缺失必须澄清（≤2 轮），仅次要字段可代填且必须显式展示 `[代填]`；
3. 生成内容全部来源于用户确认过的参数，不臆造；
4. 生成的是**草案**，用户确认（S4）才落库 + 触发审批（审批绝不先于确认）；
5. 待审批行程不可调整；主管通过才生效，拒绝即作废。

## 二、v3 架构总纲

    Agent 内核（唯一服务 core，端口 8001）
      ├─ LangGraph 意图路由（plan / chat / manage / respond / emergency）
      ├─ 行程生成引擎（场景澄清 · 两阶段输出 · 授权代填）
      ├─ 审批闭环（唯一业务主线，core/approval/engine.py 一等模块）
      └─ 会话与鉴权（HMAC 无状态 token · 自助注册）
    工具总线（ToolRegistry）：一切能力皆工具，可插拔、失败静默降级
    外接服务：政策服务（规则+RAG）· 攻略服务（RAG）· 地图 MCP（已有）
              感知服务（规划插装）· 报销/报表（规划插装）
    基建层（原样移植）：LLM 网关 · Embedding 三后端 · 存储 · decision/geo/metrics

与 v2 的本质区别：
- v2：编排层经 HTTP 回调 planner-core/sense-engine（同进程绕网络），业务逻辑长在 CRUD 路由里；
- v3：Agent 是一等公民，工具进程内直调；政策/攻略是**外接服务**（服务函数 + Agent 工具 + HTTP 三出口），
  审批闭环从散落在 trips.py/approvals.py 里的逻辑升格为独立引擎。

## 三、目录结构（v3）

    services/core/               # Agent 内核（唯一服务）
      main.py                    # 入口 + lifespan 装配
      deps.py                    # 实例容器 + 身份解析
      auth.py / admin.py         # 鉴权与管理端（移植）
      agent/                     # LangGraph 运行时
        graph.py intent.py preflight.py registry.py handlers.py pipeline.py emergency.py mcp_map.py
      approval/engine.py         # 审批闭环引擎（唯一业务主线）
      generation/                # 生成引擎（移植：itinerary/template/fast_extract/reroute/checklist）
      archive/ memory/ stores/   # 总结生成 / 会话 / JSON 存储（移植）
      api/                       # HTTP 薄壳（trips/approvals）
    services/policy_service/     # 外接服务①：差旅政策（service + router + tools）
    services/guide_service/      # 外接服务②：景点攻略（service + router[+tools]）
    shared/                      # 基建层（原样保留）

## 四、移植与重写清单

**原样移植**（已验证资产）：生成引擎 5 件套、JSON 存储 9 件套、意图路由/前置校验、
会话管理、应急模块、地图 MCP、鉴权/管理端、shared 全部基建。

**重写**：`agent/handlers.py`（HTTP 回调 → 进程内直调）、`agent/pipeline.py`（生成管线，
HTTP 与 Agent 共用）、`approval/engine.py`（确认+政策+审批状态机）、`core/main.py`（单服务装配）、
政策/攻略两服务。

**MVP 后置**：感知服务插装、报销/报表服务、前端收敛、launcher/start.bat 切换、旧服务删除。

## 五、v3 已修复的 v2 遗留缺陷

1. **演示降级模式丢弃显式场景参数**（写死 personal）→ 降级模式下 business 行程被误判
   个人出游、跳过政策与审批链路。v3：降级也尊重 explicit/carry 参数。
2. **规则抽取部分命中被整包丢弃**（仅全覆盖才用）→ 用户说了目的地还被澄清重问。
   v3：LLM 结果优先、规则补位（fast_fallback_fields 可观测）。
3. **关键词检索整串子串匹配**（「住宿 上限」因空格漏召回）→ v3 分词任一命中，全词优先。

## 六、测试基线

- v3 新基线：`tests/test_core_api.py`（11）+ `tests/test_core_approval.py`（6）+
  `tests/test_core_agent.py`（6）= 23 项全绿（澄清契约 / 确认门禁 / 审批状态机 /
  豁免规则 / 外接服务检索 / 工具总线）。
- 覆盖历史死循环回归（授权代填缺参必须收敛）与政策审批链路 E2E。

## 七、简历口径（重构后重定，待切型后统一）

- 旧口径作废：三层微服务 / 10 个 APIRouter / 网关单体装配；
- 新叙事：**Agent 内核（LangGraph）+ 审批闭环唯一业务主线 + 外接服务总线（可插拔/降级）**，
  数字以切换提交后的实测为准（服务数 / 工具数 / 测试数）。

---

## 八、Nexus 参考对比结论与场景路线图（2026-09-25 用户拍板）

参考项目：`C:\Users\JJY\Pictures\豆包\出行`（Nexus 多Agent出行平台，豆包生成）。
Supervisor 规则路由 → 8+1 场景 Agent + ReAct 思考链可视化 + HITL 审批卡 + Vue3 单页。
**实现为演示壳**：场景 Agent 忽略用户输入（参数写死）、工具全 mock、无 LLM/持久化/测试、
审批仅 status 字符串——其价值在需求版图与过程可视化叙事，不在实现。

### 8.1 吸收进 v3（切型后任务，#9 / #10）

1. **ReAct 思考链帧化**：pipeline 帧机制加 chain 帧（步骤/详情/工具/实测耗时），
   前端渲染决策过程；数据全部来自真实管线，不学它编造耗时。
2. **对话式行程变更**：「改到周三」→ 会话快照恢复 → 重生成/重排 → 政策预检 → 重新审批；
   复用 pending_draft / plan_stage 快照与 reroute 引擎，不做假定输入。

### 8.2 明确不做（2026-09-25 用户拍板：专注企业内部差旅主线）

Nexus 的通勤班车、公务用车、访客接待、加班打车、会议保障、园区接驳等场景
**一律不进 v3 路线图**。v3 场景面保持：business / meeting / visit / team / personal
五场景的「行程生成 → 政策 → 审批 → 报销回流 → 感知监控」主线；
后续扩展只考虑该主线上的外接服务（报销联动、感知插装），不做横向场景堆量。
