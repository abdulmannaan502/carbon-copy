"""Adaptive Cascade: a deterministic, in-memory simulation of wave-based donor outreach.

Nothing is persisted and no real person is contacted. Donor responses are simulated from each
donor's computed coordination state. Synthetic demonstration data — not for clinical use.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.enums import BloodGroup, InteractionChannel, LearningEventType, RecoveryActionType
from app.schemas.donor_state import EvaluationPoint, RequestSummary
from app.schemas.failure_autopsy import RequestAutopsy
from app.schemas.matching import CandidateStrategy
from app.schemas.self_healing import EscalationSummary, EscalationType, RecoveryPlan


class SimulatedResponse(StrEnum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    UNAVAILABLE = "UNAVAILABLE"
    NO_RESPONSE = "NO_RESPONSE"


class CascadeOutcome(StrEnum):
    FULFILLED = "FULFILLED"
    ESCALATED = "ESCALATED"


class CascadeContact(BaseModel):
    donor_code: str
    display_name: str
    blood_group: BloodGroup
    match_rank: int
    match_score: int
    candidate_strategy: CandidateStrategy | None
    bridge_group_member: bool
    channel: InteractionChannel
    sent_at: datetime
    response_probability: int = Field(description="Simulated chance of any reply, percent.")
    acceptance_probability: int = Field(description="Simulated chance of accepting once replying, percent.")
    response: SimulatedResponse
    responded_at: datetime | None
    secured: bool = Field(description="This acceptance counts toward the units required.")
    note: str


class WaveAutopsy(BaseModel):
    """Plain count of a wave's responses. The evidence-based analysis is CascadeWave.failure_autopsy."""

    accepted: int
    declined: int
    unavailable: int
    no_response: int
    dominant_cause: SimulatedResponse | None
    summary: str


class HealingDecision(BaseModel):
    """Compact view of a Self-Healing recovery plan in the cascade's persisted action vocabulary
    (RecoveryActionType). The full plan, with evidence and fallbacks, is CascadeWave.recovery_plan."""

    action: RecoveryActionType
    rationale: str
    next_wave_size: int | None
    channel_override: InteractionChannel | None
    radius_step: int
    bridge_group_first: bool


class CascadeWave(BaseModel):
    wave_number: int
    started_at: datetime
    closed_at: datetime
    response_window_minutes: int
    wave_size: int
    applied_action: RecoveryActionType | None = Field(description="Recovery that shaped this wave; null for wave 1.")
    eligible_candidates: int = Field(description="Eligible donors left after re-matching for this wave.")
    radius_km: float | None
    contacts: list[CascadeContact]
    units_secured_after_wave: int
    autopsy: WaveAutopsy | None
    healing: HealingDecision | None
    failure_autopsy: RequestAutopsy | None = Field(
        default=None, description="Structured Failure Autopsy Engine analysis of this wave's failures."
    )
    recovery_plan: RecoveryPlan | None = Field(
        default=None, description="Self-Healing Engine plan made from the autopsy; applied to the next wave."
    )


class LearningSignal(BaseModel):
    """Preview of the learning events this run would produce (not persisted)."""

    donor_code: str | None
    event_type: LearningEventType
    signal: float
    source: str


class HistoricalAttempt(BaseModel):
    sequence_number: int
    donor_code: str
    status: str
    outcome: str | None


class CascadeParameters(BaseModel):
    wave_size: int
    max_waves: int
    response_window_minutes: int
    seed: int
    initial_channel_policy: str
    response_stress: str = Field(description='What-if scaling of reply chances: "none", "moderate" (×0.75) or "severe" (×0.5).')


class CascadeResult(BaseModel):
    request: RequestSummary
    evaluation_point: EvaluationPoint
    simulation_start: datetime
    parameters: CascadeParameters
    outcome: CascadeOutcome
    units_required: int
    units_secured: int
    waves_used: int
    total_contacts: int
    secured_donor_codes: list[str]
    completed_at: datetime
    elapsed_minutes: int
    deadline_met: bool
    escalation: HealingDecision | None
    requires_human_intervention: bool = False
    escalation_type: EscalationType | None = None
    escalation_summary: EscalationSummary | None = None
    waves: list[CascadeWave]
    learning_preview: list[LearningSignal]
    historical_attempts: list[HistoricalAttempt] = Field(
        description="What actually happened for this request in the synthetic dataset, for comparison."
    )
    notice: str = (
        "Simulated cascade: deterministic, in memory, nothing is persisted and nobody is contacted. "
        "The learning preview is a preliminary rule set."
    )
    data_notice: str
