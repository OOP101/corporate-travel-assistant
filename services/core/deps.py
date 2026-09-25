"""核心服务实例容器 —— 由 core.main 的 lifespan 初始化，各模块经此访问。

独立成模块（而非放 main.py）是为了让 api/agent 只依赖它，避免循环导入。
v3 变化：政策/攻略能力由外接服务持有（policy_service / guide_service），
本容器只持有内核资产（行程/组织/模板存储 + LLM + 生成器）与服务引用。
"""
import logging
import os
from typing import Optional

from fastapi import HTTPException, Request

from shared.config import settings
from shared.llm import LLMManager
from shared.middleware.session import SignedSession

from core.generation import ItineraryGenerator, ChecklistGenerator, RerouteEngine
from core.archive import SummaryGenerator
from core.stores import (
    TripStore, ProfileStore, TemplateStore,
    DepartmentStore, EmployeeStore,
)

logger = logging.getLogger("core.deps")

# ---- 内核资产 ----
trip_store: Optional[TripStore] = None
profile_store: Optional[ProfileStore] = None
template_store: Optional[TemplateStore] = None
dept_store: Optional[DepartmentStore] = None
employee_store: Optional[EmployeeStore] = None
llm_manager: Optional[LLMManager] = None
checklist_gen: Optional[ChecklistGenerator] = None
summary_gen: Optional[SummaryGenerator] = None
reroute_engine: Optional[RerouteEngine] = None

# ---- 外接服务引用（实例归 policy_service / guide_service 包所有）----
policy_service = None   # policy_service.service.PolicyService
guide_service = None    # guide_service.service.GuideService

# ---- 审批闭环（唯一业务主线，core.approval.engine.ApprovalEngine）----
approval_engine = None


def org_data_dir() -> str:
    return os.path.join(os.path.dirname(settings.trip_data_dir), "org")


def declared_user_id(request: Request, session_id: str = "") -> Optional[str]:
    """调用方**显式声明**的身份：Bearer → username，其次显式 session_id；都没给返回 None。

    与 `resolve_user_id` 的区别在于「未声明」是一等状态：属主校验必须能区分
    「声明了别人」和「根本没声明」——前者要拒，后者是直接调 API / 演示路径，放行。
    API Key 的 workspace 属于兜底容器，不算声明。

    第三种状态是「声明了但无效」：带了 Bearer 却验不过签名/有效期，抛 401。
    这不等同于「没声明」，不能落到 workspace 兜底（否则按归属过滤的接口会
    返回 200 + 空数组，故障表现为「查无数据」而非「登录失效」，排查成本极高）。
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if token:
        info = SignedSession.decode(token, settings.session_secret)
        if info and info.get("username"):
            return info["username"]
        raise HTTPException(401, "登录已过期，请重新登录")
    return session_id or None


def resolve_user_id(request: Request, session_id: str = "") -> str:
    """当前请求的用户身份，按优先级取值：

    1. **登录态** —— Bearer token 解出的 username（唯一不可伪造的来源）。
    2. **显式声明** —— 显式传入的 session_id（前端 / 集成直连时的声明）。
    3. **API Key 的 workspace** —— 未登录时回退（dev key 下为 "default"），
       保留「不登录也能跑通演示」的路径。
    """
    return declared_user_id(request, session_id) or getattr(request.state, "workspace_id", "default")


def employee_of(user_id: str) -> Optional[dict]:
    """按用户 ID 取员工档案（政策匹配 / 审批人解析用）；无档案返回 None。"""
    return employee_store.get(user_id) if employee_store else None
