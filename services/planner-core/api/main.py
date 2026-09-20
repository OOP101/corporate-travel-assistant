"""
策程 · Planner Core —— FastAPI 服务入口

AI出行管家 行程规划引擎，端口 8002

路由按领域拆分至 api/routers/（trips/profiles/templates/org/policy/policy_docs/approvals），
共享服务实例在 api/deps.py，由本模块 lifespan 初始化。

API 总览:
  行程:   POST /trips/generate (SSE) · GET/PUT/DELETE /trips/{id} · POST /trips/{id}/reroute
          GET /trips/{id}/checklist · POST /trips/{id}/summary · GET /trips/{id}/expenses
  画像:   GET/PUT /users/me/profile · GET/POST /users/me/companions
  模板:   POST /trips/{id}/template · GET /templates · POST /templates/{id}/apply
  组织:   /departments · /employees (CRUD)
  政策:   /policies (CRUD) · GET /policies/match · POST /policies/check
  文档:   /policy-docs (CRUD) · POST /policy-docs/search (RAG) · POST /policy-docs/reindex
  景点:   /guides (CRUD) · POST /guides/search (RAG) · POST /guides/reindex （个人出行语料）
  审批:   /approvals (CRUD) · POST /approvals/{id}/approve|reject|cancel
  报销:   /reimbursements (CRUD) · POST /reimbursements/{id}/approve|reject|pay
  报表:   /reports/overview · /reports/by-department · /reports/by-month
  系统:   GET /health · GET /metrics
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.llm import LLMManager
from shared.embedding import EmbeddingManager, init_embedder
from shared.config import settings
from shared.logging_config import setup_logging
from shared.middleware import api_key_auth
from shared.middleware.app_factory import create_app

from generators import ChecklistGenerator, RerouteEngine
from archive import SummaryGenerator
from store import (
    TripStore, ProfileStore, TemplateStore,
    DepartmentStore, EmployeeStore, PolicyStore, ApprovalStore, ReimbursementStore, PolicyDocumentStore,
    TravelGuideStore,
)

# 相对导入：api 包名在三个服务中重名，单进程统一网关下按别名加载，故不用绝对包名
from . import deps
from .routers import (
    trips_router, profiles_router, templates_router,
    org_router, policy_router, policy_docs_router, guides_router, approvals_router,
    reimbursements_router, reports_router,
)

logger = logging.getLogger("planner-core")


# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(
        level=settings.log_level,
        service="planner-core",
        use_json=settings.log_json,
    )

    api_key_auth.register_workspace("default", settings.dev_api_key)

    # LLM
    llm = LLMManager()
    llm.register(
        "openai_compatible",
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    # 多模型：腾讯 TokenHub 统一网关（2026-09-17 全量切换：DeepSeek / Kimi / 混元三系）
    # 其余已开通未注册路由（记录备查）：glm-5 系 / minimax-m2.7 / mimo-v2.5-pro /
    # deepseek-v4-pro-0813 / deepseek-v4-pro-202606 / kimi-k2.7-code / hunyuan-role-latest
    # 注意：kimi-k2.6 为思考模式仅允许 temperature=1，未注册默认路由
    if settings.tencent_maas_api_key and settings.tencent_maas_base_url:
        llm.register(
            "tencent_maas",
            api_key=settings.tencent_maas_api_key,
            base_url=settings.tencent_maas_base_url,
            model="deepseek-v4-flash",
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        for _m in ("deepseek-v4-flash", "kimi-k3", "hy-mt2-pro", "hy-mt2-lite"):
            llm.register_model_route(_m, "tencent_maas")
        logger.info("已接入腾讯 TokenHub 多模型网关（deepseek-v4-flash / kimi-k3 / hy-mt2-pro / hy-mt2-lite）")

    # 未显式传 model 时的默认模型（对齐管理员配置的 default_model）
    if settings.llm_default_model:
        llm.default_model = settings.llm_default_model

    # 存储
    deps.trip_store = TripStore(data_dir=settings.trip_data_dir)
    deps.profile_store = ProfileStore(data_dir=settings.profile_data_dir)
    deps.template_store = TemplateStore(data_dir=settings.template_data_dir)

    # P1 企业化存储
    org_data_dir = os.path.join(os.path.dirname(settings.trip_data_dir), "org")
    deps.dept_store = DepartmentStore(data_dir=os.path.join(org_data_dir, "departments"))
    deps.employee_store = EmployeeStore(data_dir=os.path.join(org_data_dir, "employees"))
    deps.policy_store = PolicyStore(data_dir=os.path.join(org_data_dir, "policies"))
    deps.approval_store = ApprovalStore(data_dir=os.path.join(org_data_dir, "approvals"))
    deps.reimbursement_store = ReimbursementStore(data_dir=os.path.join(org_data_dir, "reimbursements"))
    deps.policy_doc_store = PolicyDocumentStore(data_dir=os.path.join(org_data_dir, "policy_docs"))
    # C 端景点/攻略语料（与政策文档分离存储，避免企业/个人数据混在一起）
    deps.guide_store = TravelGuideStore(data_dir=os.path.join(org_data_dir, "guide_docs"))

    # Embedding（可插拔：local 本地 bge / api OpenAI 兼容 / none 关闭）
    embedder = EmbeddingManager(
        provider=settings.embedding_provider,
        local_model=settings.embedding_model,
        api_base_url=settings.embedding_base_url or settings.llm_base_url,
        api_key=settings.embedding_api_key or settings.llm_api_key,
        api_model=settings.embedding_api_model or settings.embedding_model,
        dim=settings.embedding_dim,
    )
    init_embedder(embedder)

    # 生成器（ItineraryGenerator 按请求创建实例，避免并发请求共享 model/_last_trip 状态串单）
    deps.llm_manager = llm
    deps.checklist_gen = ChecklistGenerator(llm)
    deps.summary_gen = SummaryGenerator(llm)
    deps.reroute_engine = RerouteEngine(llm)

    logger.info(
        f"策程·Planner Core 已启动 (port {settings.planner_port}, "
        f"LLM={'on' if llm.is_available() else 'off(demo)'}, "
        f"Embedding={embedder.mode}{'' if embedder.available else '(降级关键词检索)'})"
    )
    yield
    logger.info("策程·Planner Core 已关闭")


# ---------------------------------------------------------------------------
# FastAPI 应用（使用共享工厂 + 领域 Router）
# ---------------------------------------------------------------------------
app = create_app(
    title="策程 · Planner Core",
    description="AI出行管家 行程规划引擎 —— 行程生成+存储+归档",
    lifespan=lifespan,
    tags=[
        {"name": "行程管理", "description": "行程 CRUD、应变重排、出行清单、总结"},
        {"name": "行程生成", "description": "自然语言 → 结构化行程（SSE 流式）"},
        {"name": "用户画像", "description": "偏好画像、同行人管理"},
        {"name": "行程模板", "description": "模板保存、查询、应用"},
        {"name": "组织管理", "description": "部门、员工、职级管理"},
        {"name": "差旅政策", "description": "差旅政策配置、违规检查"},
        {"name": "政策文档", "description": "政策文档管理、RAG 检索"},
        {"name": "景点攻略", "description": "景点/攻略语料管理、RAG 检索（个人出行）"},
        {"name": "审批管理", "description": "行程审批流转"},
        {"name": "系统", "description": "健康检查、Prometheus 指标"},
    ],
)

app.include_router(trips_router)
app.include_router(profiles_router)
app.include_router(templates_router)
app.include_router(org_router)
app.include_router(policy_router)
app.include_router(policy_docs_router)
app.include_router(guides_router)
app.include_router(approvals_router)
app.include_router(reimbursements_router)
app.include_router(reports_router)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.planner_host,
        port=settings.planner_port,
        reload=False,
    )
