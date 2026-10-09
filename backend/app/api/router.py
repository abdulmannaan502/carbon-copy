"""Versioned API router. Each feature area registers its own sub-router here
(e.g. patients, donors, requests, cascade) as it is implemented."""

from fastapi import APIRouter

from app.api.routes import bridge_groups, donors, learning, notifications, patients, requests, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(patients.router)
api_router.include_router(donors.router)
api_router.include_router(bridge_groups.router)
api_router.include_router(requests.router)
api_router.include_router(learning.router)
api_router.include_router(notifications.router)
