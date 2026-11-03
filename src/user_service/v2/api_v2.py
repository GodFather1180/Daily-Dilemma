from fastapi import APIRouter
from user_service.v2.user_v2 import router as user_router
from user_service.v2.events import router as events_router
from user_service.v2.analytics import router as analytics_router
from user_service.v2.auth_v2 import router as auth_router

router = APIRouter()
router.include_router(user_router)
router.include_router(events_router)
router.include_router(analytics_router)
router.include_router(auth_router)
