from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import (
    DatasetServiceDep,
    DigitalTwinServiceDep,
    DonorStateEngineDep,
    CascadeEngineDep,
    CoordinationNotifierDep,
    FailureAutopsyEngineDep,
    LearningReportServiceDep,
    MatchingEngineDep,
    PageParamsDep,
    SelfHealingReportServiceDep,
)
from app.schemas.common import Page
from app.schemas.dataset import BloodRequestOut
from app.schemas.digital_twin import DigitalTwinRequestContext
from app.schemas.donor_state import DonorComparison
from app.schemas.cascade import CascadeResult
from app.schemas.failure_autopsy import IndividualFailureAutopsy, RequestAutopsy
from app.schemas.learning import LearningReport
from app.schemas.matching import MatchingResult
from app.schemas.notification import NotificationDispatchReport
from app.schemas.self_healing import SelfHealingReport
from app.services.coordination_notifications import NotificationBatchRejected, SimulationParams
from app.services.cascade import CASCADE_SEED, DEFAULT_MAX_WAVES, MAX_WAVE_SIZE, MAX_WAVES_LIMIT
from app.services.learning_report import MAX_LEARNING_RUNS
from app.services.matching import MAX_LIMIT
from app.services.donor_state import UnknownCode

MAX_COMPARED_DONORS = 10

router = APIRouter(prefix="/requests", tags=["requests"])


@router.get("", response_model=Page[BloodRequestOut])
def list_blood_requests(
    service: DatasetServiceDep,
    params: PageParamsDep,
    search: Annotated[
        str | None, Query(min_length=1, max_length=24, description="Find requests by code (contains, case-insensitive).")
    ] = None,
) -> Page[BloodRequestOut]:
    return service.list_blood_requests(params, search.strip() if search and search.strip() else None)


@router.get("/{request_code}/digital-twin-context", response_model=DigitalTwinRequestContext, tags=["digital-twin"])
def request_digital_twin_context(request_code: str, service: DigitalTwinServiceDep) -> DigitalTwinRequestContext:
    context = service.request_context(request_code)
    if context is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Request {request_code} not found")
    return context


@router.get("/{request_code}/donor-comparison", response_model=DonorComparison, tags=["donor-state"])
def request_donor_comparison(
    request_code: str,
    engine: DonorStateEngineDep,
    donor_codes: Annotated[
        str | None, Query(description="Comma-separated donor codes. Default: donors this request's cascade contacted.")
    ] = None,
    evaluate_at: Annotated[Literal["auto", "now", "request_start"], Query()] = "auto",
) -> DonorComparison:
    codes = [code.strip() for code in donor_codes.split(",") if code.strip()] if donor_codes else None
    if codes is not None and not 1 <= len(codes) <= MAX_COMPARED_DONORS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Provide 1–{MAX_COMPARED_DONORS} donor codes")
    try:
        return engine.compare_for_request(request_code, codes, evaluate_at)
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get("/{request_code}/matching", response_model=MatchingResult, tags=["matching"])
def request_matching(
    request_code: str,
    engine: MatchingEngineDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Ranked candidates to return.")] = 10,
    include_excluded: Annotated[bool, Query(description="Also list excluded candidates with their reason.")] = False,
    evaluate_at: Annotated[Literal["auto", "now", "request_start"], Query()] = "auto",
) -> MatchingResult:
    try:
        return engine.match(request_code, limit, include_excluded, evaluate_at)
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get("/{request_code}/cascade", response_model=CascadeResult, tags=["cascade"])
def request_cascade(
    request_code: str,
    engine: CascadeEngineDep,
    evaluate_at: Annotated[Literal["auto", "now", "request_start"], Query()] = "auto",
    max_waves: Annotated[int, Query(ge=1, le=MAX_WAVES_LIMIT)] = DEFAULT_MAX_WAVES,
    wave_size: Annotated[int | None, Query(ge=1, le=MAX_WAVE_SIZE, description="Default depends on urgency.")] = None,
    seed: Annotated[int, Query(ge=0, le=2**31 - 1, description="Scenario seed for simulated responses.")] = CASCADE_SEED,
    response_stress: Annotated[Literal["none", "moderate", "severe"], Query()] = "none",
) -> CascadeResult:
    """Deterministic, in-memory simulation. Nothing is persisted and nobody is contacted."""
    try:
        return engine.simulate(
            request_code, evaluate_at=evaluate_at, max_waves=max_waves, wave_size=wave_size,
            seed=seed, response_stress=response_stress,
        )
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get("/{request_code}/self-healing", response_model=SelfHealingReport, tags=["self-healing"])
def request_self_healing(
    request_code: str,
    service: SelfHealingReportServiceDep,
    evaluate_at: Annotated[Literal["auto", "now", "request_start"], Query()] = "auto",
    max_waves: Annotated[int, Query(ge=1, le=MAX_WAVES_LIMIT)] = DEFAULT_MAX_WAVES,
    wave_size: Annotated[int | None, Query(ge=1, le=MAX_WAVE_SIZE, description="Default depends on urgency.")] = None,
    seed: Annotated[int, Query(ge=0, le=2**31 - 1, description="Scenario seed for simulated responses.")] = CASCADE_SEED,
    response_stress: Annotated[Literal["none", "moderate", "severe"], Query()] = "none",
) -> SelfHealingReport:
    """Recovery plans of a deterministic simulated cascade, and the advisory plan for recorded failures.
    Nothing is persisted, executed or sent."""
    try:
        return service.report(
            request_code, evaluate_at=evaluate_at, max_waves=max_waves, wave_size=wave_size, seed=seed,
            response_stress=response_stress,
        )
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get("/{request_code}/learning", response_model=LearningReport, tags=["learning"])
def request_simulation_learning(
    request_code: str,
    service: LearningReportServiceDep,
    evaluate_at: Annotated[Literal["auto", "now", "request_start"], Query()] = "auto",
    max_waves: Annotated[int, Query(ge=1, le=MAX_WAVES_LIMIT)] = DEFAULT_MAX_WAVES,
    wave_size: Annotated[int | None, Query(ge=1, le=MAX_WAVE_SIZE, description="Default depends on urgency.")] = None,
    seed: Annotated[int, Query(ge=0, le=2**31 - 1 - MAX_LEARNING_RUNS, description="First scenario seed.")] = CASCADE_SEED,
    runs: Annotated[int, Query(ge=1, le=MAX_LEARNING_RUNS, description="Consecutive seeds to simulate and pool.")] = 1,
    response_stress: Annotated[Literal["none", "moderate", "severe"], Query()] = "none",
) -> LearningReport:
    """SIMULATED-only insights from deterministic in-memory cascade runs. Nothing is persisted."""
    try:
        return service.simulated(
            request_code, seed=seed, runs=runs, evaluate_at=evaluate_at, max_waves=max_waves, wave_size=wave_size,
            response_stress=response_stress,
        )
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.post(
    "/{request_code}/cascade/notifications", response_model=NotificationDispatchReport, tags=["notifications"],
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Nothing new: every notification for this simulation already existed."}},
)
def notify_cascade_simulation(
    request_code: str,
    notifier: CoordinationNotifierDep,
    response: Response,
    evaluate_at: Annotated[Literal["auto", "now", "request_start"], Query()] = "auto",
    max_waves: Annotated[int, Query(ge=1, le=MAX_WAVES_LIMIT)] = DEFAULT_MAX_WAVES,
    wave_size: Annotated[int | None, Query(ge=1, le=MAX_WAVE_SIZE, description="Default depends on urgency.")] = None,
    seed: Annotated[int, Query(ge=0, le=2**31 - 1, description="Scenario seed for simulated responses.")] = CASCADE_SEED,
    response_stress: Annotated[Literal["none", "moderate", "severe"], Query()] = "none",
) -> NotificationDispatchReport:
    """Runs the same deterministic simulation as GET /cascade and records its events as DEMO notifications
    (SIMULATED). Explicit and idempotent: repeating it with the same parameters creates nothing new. Nobody is
    contacted and nothing is sent. Demo-only, no authentication."""
    try:
        report = notifier.notify_simulation(request_code, SimulationParams(evaluate_at, max_waves, wave_size, seed, response_stress))
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except NotificationBatchRejected as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    if report.created == 0:
        response.status_code = status.HTTP_200_OK
    return report


@router.get("/{request_code}/failures/autopsy", response_model=RequestAutopsy, tags=["failure-autopsy"])
def request_failure_autopsy(
    request_code: str,
    engine: FailureAutopsyEngineDep,
    evaluate_at: Annotated[Literal["auto", "now", "request_start"], Query()] = "auto",
) -> RequestAutopsy:
    """Analyses every RECORDED Failure attached to this request's coordination attempts: what
    actually happened in the synthetic dataset, not the simulated cascade."""
    try:
        return engine.analyze_request(request_code, evaluate_at)
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get(
    "/{request_code}/failures/{failure_code}/autopsy", response_model=IndividualFailureAutopsy, tags=["failure-autopsy"]
)
def request_single_failure_autopsy(
    request_code: str, failure_code: str, engine: FailureAutopsyEngineDep
) -> IndividualFailureAutopsy:
    try:
        return engine.analyze_failure(request_code, failure_code)
    except UnknownCode as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
