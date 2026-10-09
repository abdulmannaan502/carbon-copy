from fastapi import APIRouter

from app.api.deps import SystemServiceDep
from app.schemas.system import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(service: SystemServiceDep) -> HealthResponse:
    return service.health()
