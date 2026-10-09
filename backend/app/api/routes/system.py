from fastapi import APIRouter

from app.api.deps import DatasetServiceDep, SystemServiceDep
from app.schemas.dataset import DatasetStats
from app.schemas.system import SystemStatusResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatusResponse)
def system_status(service: SystemServiceDep) -> SystemStatusResponse:
    return service.status()


@router.get("/dataset-stats", response_model=DatasetStats)
def dataset_stats(service: DatasetServiceDep) -> DatasetStats:
    return service.stats()
