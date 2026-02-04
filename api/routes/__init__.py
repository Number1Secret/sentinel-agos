from .auth import router as auth_router
from .audits import router as audits_router
from .webhooks import router as webhooks_router
from .leads import router as leads_router
from .batches import router as batches_router
from .analytics import router as analytics_router
from .architect import router as architect_router

__all__ = [
    "auth_router",
    "audits_router",
    "webhooks_router",
    "leads_router",
    "batches_router",
    "analytics_router",
    "architect_router",
]
