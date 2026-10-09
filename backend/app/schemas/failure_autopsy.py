"""Failure Autopsy: a deterministic operational analysis of why coordination attempts failed.

Answers "why did this fail, is it a pattern, and what should be considered next?" for one failure
or for a batch of failures from the same request. It is an **operational coordination analysis**,
not a medical diagnosis, and it does not make medical decisions.

Strict separation of responsibility:
    Adaptive Cascade    "who did we contact, and what happened?"
    Failure Autopsy      "why did it fail, and what pattern does the evidence suggest?" (this file)
    Self-Healing (hook)  "what should the system actually change?" — decides, using the recommendation
                         below as one input; it is never bound by it.
Failure Autopsy only recommends. It never decides or executes recovery.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.enums import FailureCategory, FailureSeverity, InteractionChannel, UrgencyLevel


class FailureSource(StrEnum):
    """Keeps "what actually happened" (RECORDED, from the synthetic dataset) distinct from
    "simulated cascade" (SIMULATED, from an in-memory Adaptive Cascade run). Never mixed in one autopsy."""

    RECORDED = "RECORDED"
    SIMULATED = "SIMULATED"


class FailurePatternType(StrEnum):
    INDIVIDUAL_DONOR_FAILURE = "INDIVIDUAL_DONOR_FAILURE"
    CHANNEL_RESPONSE_FAILURE = "CHANNEL_RESPONSE_FAILURE"
    LOCAL_POOL_FAILURE = "LOCAL_POOL_FAILURE"
    BRIDGE_GROUP_FAILURE = "BRIDGE_GROUP_FAILURE"
    CANDIDATE_POOL_EXHAUSTION = "CANDIDATE_POOL_EXHAUSTION"
    RESPONSE_WINDOW_FAILURE = "RESPONSE_WINDOW_FAILURE"
    RECENT_DONATION_POOL = "RECENT_DONATION_POOL"
    UNKNOWN_PATTERN = "UNKNOWN_PATTERN"


class EvidenceType(StrEnum):
    ATTEMPT = "ATTEMPT"
    INTERACTION = "INTERACTION"
    OUTCOME = "OUTCOME"
    PATTERN = "PATTERN"
    CONTEXT = "CONTEXT"


class EvidenceItem(BaseModel):
    type: EvidenceType
    description: str
    reference: str | None = Field(default=None, description="attempt_code, failure_code or donor_code, when available.")


class RecoveryRecommendation(StrEnum):
    """The shared recovery vocabulary. The Failure Autopsy *recommends* one of these; the Self-Healing
    Engine *decides* with the same names (plus NO_CHANGE) and the cascade applies the plan. Each engine
    owns its own responsibility; they share one set of action names so none is duplicated.
    TRY_BRIDGE_GROUP is the autopsy's original spelling of TRY_ALTERNATIVE_BRIDGE_GROUP (an alias)."""

    NO_CHANGE = "NO_CHANGE"
    TRY_ALTERNATIVE_DONOR = "TRY_ALTERNATIVE_DONOR"
    SWITCH_CHANNEL = "SWITCH_CHANNEL"
    INCREASE_WAVE_SIZE = "INCREASE_WAVE_SIZE"
    TRY_ALTERNATIVE_BRIDGE_GROUP = "TRY_ALTERNATIVE_BRIDGE_GROUP"
    TRY_BRIDGE_GROUP = "TRY_ALTERNATIVE_BRIDGE_GROUP"  # alias
    EXPAND_SEARCH_RADIUS = "EXPAND_SEARCH_RADIUS"
    RE_RUN_MATCHING = "RE_RUN_MATCHING"
    HUMAN_COORDINATOR = "HUMAN_COORDINATOR"
    BLOOD_BANK_ESCALATION = "BLOOD_BANK_ESCALATION"


class IndividualFailureAutopsy(BaseModel):
    """Analysis of one failed coordination attempt. Answers: what failed, who, why, and is this
    failure donor-specific, channel-specific, timing-related or network/context-related."""

    source: FailureSource
    failure_type: FailureCategory
    severity: FailureSeverity
    rule_confidence: float = Field(ge=0, le=1, description="Deterministic rule confidence, not a machine-learning score.")
    summary: str
    evidence: list[EvidenceItem]
    affected_donor: str
    affected_request: str
    affected_channel: InteractionChannel | None
    detected_at: datetime
    reference: str | None = Field(default=None, description="attempt_code or failure_code, when recorded.")
    donor_specific: bool = Field(description="The cause is specific to this donor rather than a shared, systemic cause.")
    channel_specific: bool = Field(description="Part of a same-channel non-response pattern in its batch.")
    timing_related: bool = Field(description="The response window elapsing is a material part of the cause.")
    network_related: bool = Field(description="Part of a donor-network/context pattern (local pool, bridge group, exhaustion).")
    recommended_next_action: RecoveryRecommendation


class PatternFinding(BaseModel):
    """Analysis across multiple failures in the same batch: a symptom restated as an operational
    interpretation, e.g. "Three consecutive donors contacted through SMS failed to respond."
    Never claims a cause the evidence does not support."""

    pattern_type: FailurePatternType
    severity: FailureSeverity
    rule_confidence: float = Field(ge=0, le=1)
    supporting_failures: int
    affected_donors: list[str]
    affected_channel: InteractionChannel | None
    donor_specific: bool
    channel_specific: bool
    timing_related: bool
    network_related: bool
    evidence: list[EvidenceItem]
    interpretation: str
    recommended_action: RecoveryRecommendation


class RequestAutopsy(BaseModel):
    """Request-level (or wave-level) failure analysis: individual failures plus any pattern found
    across them, with one recommendation to consider next."""

    request_code: str
    analysis_time: datetime
    source: FailureSource
    failures_analyzed: int
    individual_failures: list[IndividualFailureAutopsy]
    patterns: list[PatternFinding]
    pattern_detected: bool = Field(description="True only for a genuine multi-failure pattern (not isolated/unknown).")
    dominant_pattern: PatternFinding | None
    recommended_action: RecoveryRecommendation | None
    explanation: str
    notice: str = (
        "Deterministic operational coordination analysis. Not a medical diagnosis and not a "
        "medical decision. The Failure Autopsy Engine recommends; Self-Healing decides."
    )
    data_notice: str
