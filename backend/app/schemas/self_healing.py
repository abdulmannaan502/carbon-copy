"""Self-Healing: a deterministic recovery plan answering "what should the coordination system change next?"

Coordination recovery only: it changes how outreach is organised (channel, wave size, search radius,
bridge-group priority) or hands the request to people. It never diagnoses, never decides treatment and
never promises that a donor will respond. Synthetic demonstration data — not for clinical use.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.enums import FailureSeverity, InteractionChannel, UrgencyLevel
from app.schemas.failure_autopsy import FailurePatternType, FailureSource, RecoveryRecommendation


class EscalationType(StrEnum):
    HUMAN_COORDINATOR = "HUMAN_COORDINATOR"
    BLOOD_BANK = "BLOOD_BANK"


class BridgePriority(StrEnum):
    """How the next wave treats members of the patient's bridge group."""

    DEFAULT = "DEFAULT"
    BRIDGE_FIRST = "BRIDGE_FIRST"
    NON_BRIDGE_FIRST = "NON_BRIDGE_FIRST"


class RecoveryTrigger(BaseModel):
    pattern: FailurePatternType | None = Field(description="Dominant Failure Autopsy pattern, if any.")
    severity: FailureSeverity | None


class RecoveryChanges(BaseModel):
    """Only the settings the plan actually changes are non-null."""

    channel: InteractionChannel | None = None
    wave_size: int | None = None
    radius_step: int | None = None
    radius_km: float | None = Field(default=None, description="Null with radius_step set means region-wide.")
    radius_label: str | None = None
    bridge_priority: BridgePriority | None = None


class CascadeStateSnapshot(BaseModel):
    """The state the plan was decided from, so every decision can be audited."""

    wave_number: int
    max_waves: int
    wave_size: int
    channel: InteractionChannel | None = Field(description="Channel forced on the last wave; null = per-donor default.")
    radius_label: str
    donors_contacted: int
    consecutive_failed_waves: int
    recovery_attempts: int
    channel_switches: int
    eligible_remaining: int
    fatigued_remaining: int
    bridge_members_remaining: int
    bridge_priority: BridgePriority


class EscalationSummary(BaseModel):
    """Why automation stopped and what a person should consider doing (always a human decision)."""

    escalation_type: EscalationType
    why_automation_stopped: str
    actions_attempted: list[str]
    donors_contacted: int
    failures: dict[str, int]
    recommended_human_action: str


class RecoveryPlan(BaseModel):
    request_code: str
    source: FailureSource
    wave_number: int = Field(description="The failed wave this plan responds to.")
    trigger: RecoveryTrigger
    urgency: UrgencyLevel
    autopsy_recommended: RecoveryRecommendation | None = Field(
        description="What the Failure Autopsy recommended; Self-Healing decides independently."
    )
    primary_action: RecoveryRecommendation
    fallback_actions: list[RecoveryRecommendation]
    rule_id: str = Field(description="Policy rule that matched, e.g. P3. First match wins.")
    rule_name: str
    rule_strength: float = Field(ge=0, le=1, description="Strength of the matched rule. Not a probability of success.")
    reason: str
    evidence: list[str]
    current_state: CascadeStateSnapshot
    changes: RecoveryChanges
    expected_effect: str
    requires_human_intervention: bool
    escalation_type: EscalationType | None = None
    escalation: EscalationSummary | None = None
    notice: str = (
        "Deterministic coordination recovery. It adapts outreach and never guarantees that any donor will "
        "respond. Not a medical decision."
    )


class WavePlan(BaseModel):
    wave_number: int
    plan: RecoveryPlan


class SelfHealingReport(BaseModel):
    """GET /requests/{code}/self-healing: the recovery plans of a simulated cascade run, plus what the
    engine would do about the failures that actually happened in the synthetic dataset. The two
    sources are never mixed."""

    request_code: str
    simulated_plans: list[WavePlan]
    simulated_outcome: str
    automatic_recovery_attempts: int
    requires_human_intervention: bool
    escalation_type: EscalationType | None
    recorded_plan: RecoveryPlan | None = Field(
        description="Plan the engine would make for the RECORDED failures; null when none were recorded."
    )
    parameters: dict[str, str | int]
    notice: str = (
        "Simulated plans come from an in-memory cascade run (nothing persisted, nobody contacted). "
        "The recorded plan is advisory and is not executed."
    )
    data_notice: str
