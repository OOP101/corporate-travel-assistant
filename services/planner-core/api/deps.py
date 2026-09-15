"""共享服务实例容器 —— 由 api.main 的 lifespan 初始化，各 router 经此访问。

独立成模块（而非放 main.py）是为了让 router 只依赖它，避免 router ↔ main 循环导入。
"""
from typing import Optional

from fastapi import Request

from shared.config import settings
from shared.llm import LLMManager
from shared.middleware.session import SignedSession

from generators import ItineraryGenerator, ChecklistGenerator, RerouteEngine
from archive import SummaryGenerator
from store import (
    TripStore, ProfileStore, TemplateStore,
    DepartmentStore, EmployeeStore, PolicyStore, ApprovalStore, ReimbursementStore, PolicyDocumentStore,
    TravelGuideStore,
)

trip_store: Optional[TripStore] = None
profile_store: Optional[ProfileStore] = None
template_store: Optional[TemplateStore] = None
llm_manager: Optional[LLMManager] = None
checklist_gen: Optional[ChecklistGenerator] = None
summary_gen: Optional[SummaryGenerator] = None
reroute_engine: Optional[RerouteEngine] = None

# P1 企业化
dept_store: Optional[DepartmentStore] = None
employee_store: Optional[EmployeeStore] = None
policy_store: Optional[PolicyStore] = None
approval_store: Optional[ApprovalStore] = None
reimbursement_store: Optional[ReimbursementStore] = None
policy_doc_store: Optional[PolicyDocumentStore] = None

# C 端个人出行：景点 / 攻略语料（与政策文档共用 DocumentCorpusStore 能力）
guide_store: Optional[TravelGuideStore] = None


def declared_user_id(request: Request, session_id: str = "") -> Optional[str]:
    """调用方**显式声明**的身份：Bearer → username，其次显式 session_id；都没给返回 None。

    与 `resolve_user_id` 的区别在于「未声明」是一等状态：属主校验必须能区分
    「声明了别人」和「根本没声明」——前者要拒，后者是直接调 API / 演示路径，放行。
    API Key 的 workspace 属于兜底容器，不算声明。
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if token:
        info = SignedSession.decode(token, settings.session_secret)
        if info and info.get("username"):
            return info["username"]
    return session_id or None


def resolve_user_id(request: Request, session_id: str = "") -> str:
    """当前请求的用户身份，按优先级取值：

    1. **登录态** —— `Authorization: Bearer <token>` 解出的 username。前端直连
       planner 时走这条，也是唯一不可伪造的来源。
    2. **显式声明** —— 显式传入的 session_id。用于 journey-hub 的内部转发：
       它已在上游把登录 token 解析成 username，再经 session_id 带下来
       （服务间调用只带 X-API-Key，不带用户 token）。
    3. **API Key 的 workspace** —— 未登录时回退（dev key 下为 "default"），
       保留「不登录也能跑通演示」的路径。

    token 的签名用 SESSION_SECRET 校验，两端共享同一密钥即可离线验证
    （单体模式同进程共享 settings，微服务模式各进程读同一份 .env）。
    """
    return declared_user_id(request, session_id) or getattr(request.state, "workspace_id", "default")
