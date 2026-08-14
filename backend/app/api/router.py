from fastapi import APIRouter

from app.api.budgets import router as budgets_router
from app.api.channel_rules import router as channel_rules_router
from app.api.children import router as children_router
from app.api.digests import router as digests_router
from app.api.health import router as health_router
from app.api.push import router as push_router
from app.api.youtube_requests import router as youtube_requests_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(children_router)
api_router.include_router(budgets_router)
api_router.include_router(channel_rules_router)
api_router.include_router(digests_router)
api_router.include_router(push_router)
api_router.include_router(youtube_requests_router)
