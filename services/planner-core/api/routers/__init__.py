from .trips import router as trips_router
from .profiles import router as profiles_router
from .templates import router as templates_router
from .org import router as org_router
from .policy import router as policy_router
from .policy_docs import router as policy_docs_router
from .approvals import router as approvals_router
from .reimbursements import router as reimbursements_router
from .reports import router as reports_router

__all__ = [
    "trips_router", "profiles_router", "templates_router",
    "org_router", "policy_router", "policy_docs_router", "approvals_router",
    "reimbursements_router", "reports_router",
]
