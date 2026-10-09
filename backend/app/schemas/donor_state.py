"""Donor State Intelligence: computed operational coordination state of a donor.

Every value here is a demo coordination metric computed by deterministic rules.
None of it is a medical eligibility or suitability determination.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.enums import AvailabilityStatus, BloodGroup, RequestStatus, UrgencyLevel


class CoordinationAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    RECENTLY_CONTACTED = "RECENTLY_CONTACTED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INACTIVE = "INACTIVE"


class ScoreBand(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FatigueBand(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class PriorityBand(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class DataSufficiency(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class EvaluationPoint(StrEnum):
    CURRENT = "CURRENT"
    REQUEST_START = "REQUEST_START"


class WeightProfile(StrEnum):
    GENERAL = "GENERAL"
    STANDARD = "STANDARD"
    URGENT = "URGENT"


class Impact(StrEnum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class DonorIdentity(BaseModel):
    donor_code: str
    display_name: str
    blood_group: BloodGroup
    city: str
    district: str
    state: str
    bridge_group_code: str | None
    active: bool


class AvailabilityAssessment(BaseModel):
    availability_status: CoordinationAvailability
    availability_reason: str
    declared_availability: AvailabilityStatus | None = Field(description="Registry input from the donor record.")
    last_contacted_at: datetime | None
    days_since_last_contact: int | None
    awaiting_reply: bool


class EligibilityCheck(BaseModel):
    rule: str
    passed: bool
    detail: str


class EligibilityAssessment(BaseModel):
    eligible: bool
    rule_set: str = "demo coordination eligibility rules"
    checks: list[EligibilityCheck]
    eligibility_reasons: list[str]
    donation_count: int
    last_donation_at: datetime | None
    days_since_last_donation: int | None


class ReliabilityAssessment(BaseModel):
    reliability_score: int = Field(ge=0, le=100)
    reliability_band: ScoreBand
    successful_attempts: int
    failed_attempts: int
    no_response_failures: int
    declined_or_unavailable_failures: int
    other_failures: int
    prior_donations_counted: int
    evidence_weight: float
    reliability_factors: list[str]


class ResponseBehavior(BaseModel):
    total_interactions: int
    total_responses: int
    acceptances: int
    declines: int
    unavailable_replies: int
    no_responses: int
    pending: int
    donation_requests: int
    data_sufficiency: DataSufficiency
    response_rate: int | None = Field(description="Whole percent; null when history is insufficient.")
    acceptance_rate: int | None = Field(description="Accepted donation requests, whole percent; null when insufficient.")
    no_response_rate: int | None
    response_score: int = Field(ge=0, le=100, description="Smoothed response rate used for priority.")


class FatigueAssessment(BaseModel):
    fatigue_score: int = Field(ge=0, le=100, description="Coordination fatigue (outreach load), not medical fatigue.")
    fatigue_band: FatigueBand
    contacts_last_30_days: int
    requests_last_30_days: int
    fatigue_reasons: list[str]


class FreshnessAssessment(BaseModel):
    days_since_last_contact: int | None
    contact_freshness_score: int = Field(ge=0, le=100)


class PriorityFactor(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    weight: int = Field(description="Percent of the priority score.")
    contribution: float = Field(description="Points contributed to the priority score.")


class PriorityReason(BaseModel):
    text: str
    impact: Impact


class PriorityAssessment(BaseModel):
    priority_score: int = Field(ge=0, le=100, description="Operational ranking score, not a clinical recommendation.")
    priority_band: PriorityBand
    gated: bool = Field(description="True when an eligibility rule failed, forcing the score to 0.")
    weight_profile: WeightProfile
    priority_factors: list[PriorityFactor]
    priority_reasons: list[PriorityReason]


class DonorStateAssessment(BaseModel):
    assessed_at: datetime
    evaluation_point: EvaluationPoint
    donor: DonorIdentity
    availability: AvailabilityAssessment
    eligibility: EligibilityAssessment
    reliability: ReliabilityAssessment
    response: ResponseBehavior
    fatigue: FatigueAssessment
    freshness: FreshnessAssessment
    priority: PriorityAssessment
    data_notice: str


class RequestSummary(BaseModel):
    request_code: str
    patient_code: str
    blood_group: BloodGroup
    urgency_level: UrgencyLevel
    status: RequestStatus
    city: str
    requested_at: datetime
    required_by: datetime


class CompatibilityAssessment(BaseModel):
    request_blood_group: BloodGroup
    donor_blood_group: BloodGroup
    compatible: bool
    exact_match: bool
    compatible_donor_groups: list[BloodGroup]
    rule_set: str = "simplified ABO/Rh demo table"


class DonorRequestAssessment(BaseModel):
    request: RequestSummary
    compatibility: CompatibilityAssessment
    evaluation_note: str
    state: DonorStateAssessment


class DonorComparison(BaseModel):
    request: RequestSummary
    evaluation_point: EvaluationPoint
    assessed_at: datetime
    candidates: list[DonorRequestAssessment] = Field(description="Highest priority first.")
    recommended_donor_code: str | None
    recommendation_reason: str
    notice: str = "Compares only the listed donors on their current state. This is not the Matching Engine."
