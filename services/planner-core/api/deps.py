"""共享服务实例容器 —— 由 api.main 的 lifespan 初始化，各 router 经此访问。

独立成模块（而非放 main.py）是为了让 router 只依赖它，避免 router ↔ main 循环导入。
"""
from typing import Optional

from shared.llm import LLMManager

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
