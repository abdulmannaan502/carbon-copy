"""Living Digital Twin: a computed (not persisted) view of a recurring patient's
coordination state. Every field is operational information, never a medical assessment."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.enums import (
    BloodGroup,
    CoordinationOutcome,
    CoordinationStatus,
    RecoveryActionType,
    RecoveryStatus,
    RequestStatus,
    UrgencyLevel,
)


class RecurrenceStatus(StrEnum):
    STABLE = "STABLE"
    APPROACHING = "APPROACHING"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    UNKNOWN = "UNKNOWN"


class OperationalState(StrEnum):
    """Coordination/network state only. Does not describe the patient's health."""

    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    ATTENTION = "ATTENTION"
    ACTIVE_COORDINATION = "ACTIVE_COORDINATION"


class NetworkStrengthBand(StrEnum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class TimelineEventKind(StrEnum):
    REQUEST_CREATED = "REQUEST_CREATED"
    AVAILABILITY_CHECKS = "AVAILABILITY_CHECKS"
    DONOR_CONTACTED = "DONOR_CONTACTED"
    DONOR_ACCEPTED = "DONOR_ACCEPTED"
    ATTEMPT_FAILED = "ATTEMPT_FAILED"
    FAILURE_DETECTED = "FAILURE_DETECTED"
    RECOVERY_INITIATED = "RECOVERY_INITIATED"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    REQUEST_FULFILLED = "REQUEST_FULFILLED"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"


class TimelineTone(StrEnum):
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    PENDING = "PENDING"


class PatientIdentity(BaseModel):
    patient_code: str
    display_name: str
    blood_group: BloodGroup
    city: str
    district: str
    state: str
    urgency_level: UrgencyLevel
    bridge_group_code: str | None
    bridge_group_name: str | None
    active: bool


class TransfusionProfile(BaseModel):
    transfusion_frequency_days: int | None
    last_transfusion_date: date | None
    next_expected_requirement: date | None
    days_until_expected_requirement: int | None
    recurrence_status: RecurrenceStatus


class RequirementState(BaseModel):
    active_request: bool = Field(description="A request is OPEN, MATCHING, COORDINATING or RECOVERING.")
    active_request_code: str | None
    current_request_code: str | None = Field(
        description="The active request, otherwise the fulfilled request covering the upcoming requirement."
    )
    requirement_covered: bool = Field(
        description="The upcoming requirement already has a confirmed donor (fulfilled request not yet due)."
    )
    units_required: int | None
    request_status: RequestStatus | None
    request_urgency: UrgencyLevel | None
    requested_at: datetime | None
    required_by: datetime | None
    attempts_made: int
    failed_attempts: int
    latest_attempt_status: CoordinationStatus | None
    pending_recovery_action: RecoveryActionType | None


class RequestOutcomeSummary(BaseModel):
    request_code: str
    requested_at: datetime
    status: RequestStatus
    attempts: int
    failed_attempts: int
    successful_attempts: int


class CoordinationHistory(BaseModel):
    total_requests: int
    fulfilled_requests: int
    requests_with_failures: int = Field(description="Requests that had at least one failed coordination attempt.")
    recovering_requests: int
    cancelled_requests: int
    active_requests: int
    historical_success_rate: int | None = Field(
        description="Whole percent of resolved requests (fulfilled + cancelled) that were fulfilled."
    )
    first_attempt_success_rate: int | None = Field(
        description="Whole percent of fulfilled requests whose first attempt succeeded."
    )
    average_coordination_attempts: float | None = Field(description="Per request with attempts, one decimal.")
    total_coordination_attempts: int
    total_failures: int
    total_recovery_actions: int
    successful_recoveries: int = Field(description="Recovery actions whose target donor then accepted.")
    requests: list[RequestOutcomeSummary]


class NetworkStrengthComponents(BaseModel):
    depth: int
    reliability: int
    responsiveness: int
    freshness: int


class NetworkState(BaseModel):
    known_donor_count: int
    active_donor_count: int
    available_donor_count: int = Field(description="Active, AVAILABLE and ELIGIBLE under demo rules.")
    high_reliability_donor_count: int
    recently_contacted_donor_count: int
    fatigued_donor_count: int
    bridge_group_donor_count: int
    network_strength_score: int = Field(ge=0, le=100, description="Demo operational metric, not a clinical score.")
    network_strength_band: NetworkStrengthBand
    strength_components: NetworkStrengthComponents = Field(description="Each component scaled 0–100.")
    strength_weights: NetworkStrengthComponents = Field(description="Weight of each component in percent.")


class TimelineEvent(BaseModel):
    at: datetime
    kind: TimelineEventKind
    title: str
    detail: str | None = None
    tone: TimelineTone


class RecentActivity(BaseModel):
    window_days: int
    last_request_date: datetime | None
    last_successful_coordination: datetime | None
    last_failed_coordination: datetime | None
    recent_interaction_count: int
    recent_failure_count: int
    recent_success_count: int
    focus_request_code: str | None = Field(description="Request the timeline describes.")
    timeline: list[TimelineEvent]


class DigitalTwinState(BaseModel):
    as_of: datetime
    patient: PatientIdentity
    transfusion_profile: TransfusionProfile
    requirement_state: RequirementState
    coordination_history: CoordinationHistory
    network_state: NetworkState
    recent_activity: RecentActivity
    operational_state: OperationalState
    operational_state_reasons: list[str]
    summary: str
    summary_source: str = Field(description='"deterministic" today; an AI provider may supply it later.')
    data_notice: str


class RequestCoordinationContext(BaseModel):
    request_code: str
    status: RequestStatus
    blood_group: BloodGroup
    compatible_donor_groups: list[BloodGroup]
    units_required: int
    urgency_level: UrgencyLevel
    requested_at: datetime
    required_by: datetime
    is_active: bool
    is_current_request: bool = Field(description="This is the patient's current (active or covering) request.")
    attempts: int
    failed_attempts: int
    latest_attempt_status: CoordinationStatus | None
    latest_attempt_outcome: CoordinationOutcome | None
    latest_recovery_action: RecoveryActionType | None
    latest_recovery_status: RecoveryStatus | None
    timeline: list[TimelineEvent]


class DigitalTwinRequestContext(BaseModel):
    request: RequestCoordinationContext
    digital_twin: DigitalTwinState
