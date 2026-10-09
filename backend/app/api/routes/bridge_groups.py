from fastapi import APIRouter

from app.api.deps import DatasetServiceDep, PageParamsDep
from app.schemas.common import Page
from app.schemas.dataset import BridgeGroupOut

router = APIRouter(prefix="/bridge-groups", tags=["bridge-groups"])


@router.get("", response_model=Page[BridgeGroupOut])
def list_bridge_groups(service: DatasetServiceDep, params: PageParamsDep) -> Page[BridgeGroupOut]:
    return service.list_bridge_groups(params)
