from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DatasetServiceDep, DonorStateEngineDep, PageParamsDep
from app.schemas.common import Page
from app.schemas.dataset import DonorOut
from app.schemas.donor_state import DonorRequestAssessment, DonorStateAssessment
from app.services.donor_state import UnknownCode

router = APIRouter(prefix="/donors", tags=["donors"])

EvaluateAt = Annotated[
    Literal["auto", "now", "request_start"],
    Query(description="auto: active requests now, resolved requests at the moment coordination began."),
]


@router.get("", response_model=Page[DonorOut])
def list_donors(service: DatasetServiceDep, params: PageParamsDep) -> Page[DonorOut]:
    return service.list_donors(params)


@router.get("/{donor_code}/state", response_model=DonorStateAssessment, tags=["donor-state"])
def donor_state(donor_code: str, engine: DonorStateEngineDep) -> DonorStateAssessment:
    assessment = engine.assess(donor_code)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Donor {donor_code} not found")
    return assessment


@router.get(
    "/{donor_code}/state-for-request/{request_code}", response_model=DonorRequestAssessment, tags=["donor-state"]
)
def donor_state_for_request(
    donor_code: str, request_code: str, engine: DonorStateEngineDep, evaluate_at: EvaluateAt = "auto"
) -> DonorRequestAssessment:
    try:
        return engine.assess_for_request(donor_code, request_code, evaluate_at)
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
