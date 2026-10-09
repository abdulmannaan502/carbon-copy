"""Matching Engine: which eligible donors are the best candidates for a request, and why.

Deterministic coordination recommendations from synthetic demonstration data.
Not a medical recommendation or a clinical suitability assessment.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.enums import BloodGroup
from app.schemas.digital_twin import NetworkStrengthBand, OperationalState
from app.schemas.donor_state import (
    CoordinationAvailability,
    DataSufficiency,
    EvaluationPoint,
    Impact,
    RequestSummary,
    WeightProfile,
)


class CandidateStrategy(StrEnum):
    RELIABLE = "RELIABLE"
    BALANCED = "BALANCED"
    EXPLORATION = "EXPLORATION"


class MatchReason(BaseModel):
    text: str
    impact: Impact


class ScoreComponent(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    weight: int = Field(description="Percent of the match score.")
    points: float


class MatchCandidate(BaseModel):
    rank: int | None = Field(description="1-based rank among eligible candidates; null when excluded.")
    donor_code: str
    display_name: str
    blood_group: BloodGroup
    city: str
    distance_km: float | None
    eligible: bool
    availability_status: CoordinationAvailability
    reliability_score: int
    response_rate: int | None
    response_score: int
    response_data_sufficiency: DataSufficiency
    fatigue_score: int
    freshness_score: int
    donor_priority_score: int = Field(description="From the Donor State Engine (single source of truth).")
    request_fit_score: int
    geographic_fit_score: int
    context_score: int
    strategy_adjustment: int = Field(
        description="Exploration bonus (+) or urgent uncertainty discount (−) added to the weighted score."
    )
    match_score: int = Field(ge=0, le=100)
    candidate_strategy: CandidateStrategy | None
    strategy_reason: str | None
    score_breakdown: list[ScoreComponent]
    reasons: list[MatchReason]
    exclusion_reason: str | None
    bridge_group_member: bool = False


class EvaluationInfo(BaseModel):
    evaluation_point: EvaluationPoint
    assessed_at: datetime
    note: str


class DiscoveryInfo(BaseModel):
    total_donors: int
    request_location_known: bool
    radius_km: float | None = Field(description="Search radius used; null means the whole dataset region.")
    radius_expanded: bool
    filtered_inactive: int
    filtered_incompatible: int
    filtered_outside_radius: int
    pool_cap: int
    pool_capped: bool
    compatible_donor_groups: list[BloodGroup]


class TwinContext(BaseModel):
    """Current Digital Twin context for the request's patient (consumed, not recomputed)."""

    patient_code: str
    operational_state: OperationalState
    active_request_code: str | None
    requirement_covered: bool
    network_strength_score: int
    network_strength_band: NetworkStrengthBand


class MatchingWeights(BaseModel):
    profile: WeightProfile
    components: dict[str, int]
    exploration_bonus: int
    uncertainty_discount: int


class ExclusionCount(BaseModel):
    reason: str
    count: int
    stage: str = Field(description='"discovery" (filtered in SQL) or "gate" (failed eligibility).')


class MatchingSummary(BaseModel):
    top_candidate: str | None
    average_match_score: float | None = Field(description="Across all eligible candidates, one decimal.")
    candidates_by_strategy: dict[CandidateStrategy, int]
    top_exclusion_reasons: list[ExclusionCount]


class MatchingResult(BaseModel):
    request: RequestSummary
    evaluation: EvaluationInfo
    digital_twin_context: TwinContext
    discovery: DiscoveryInfo
    candidate_pool_size: int
    eligible_candidate_count: int
    excluded_candidate_count: int
    weights: MatchingWeights
    ranking: list[MatchCandidate]
    excluded: list[MatchCandidate]
    matching_summary: MatchingSummary
    notice: str = "Ranks candidates only. Contact order and recovery belong to the future Adaptive Cascade."
    data_notice: str
