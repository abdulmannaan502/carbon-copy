"""Learning: deterministic, evidence-backed insights from coordination outcomes.

Descriptive and observational only. Insights describe what the data shows, say how much evidence
supports them and state their limits; they never claim causation and never prove real-world
effectiveness. RECORDED and SIMULATED populations are never mixed.
Synthetic demonstration data — not for clinical use.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.failure_autopsy import FailureSource


class EvidenceStrength(StrEnum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class InsightCategory(StrEnum):
    CHANNEL_EFFECTIVENESS = "CHANNEL_EFFECTIVENESS"
    FAILURE_PATTERN = "FAILURE_PATTERN"
    RECOVERY_EFFECTIVENESS = "RECOVERY_EFFECTIVENESS"
    DONOR_FATIGUE = "DONOR_FATIGUE"
    COORDINATION_BOTTLENECK = "COORDINATION_BOTTLENECK"


class InsightGroup(BaseModel):
    """One compared group: a channel, a recovery action, a contact-load band, a failure category…"""

    label: str
    numerator: int | None = None
    denominator: int | None = None
    rate: float | None = Field(default=None, description="numerator / denominator, 0–1.")
    ci_low: float | None = Field(default=None, description="95% Wilson interval, lower bound.")
    ci_high: float | None = None
    value: float | None = Field(default=None, description="A measured value, e.g. median minutes.")
    unit: str | None = None


class TimeWindow(BaseModel):
    start: datetime | None
    end: datetime | None


class Insight(BaseModel):
    insight_id: str
    category: InsightCategory
    source: FailureSource
    provenance: str = Field(description="Where the numbers come from, in plain words.")
    title: str
    finding: str
    numerator: int | None = Field(description="Events behind the headline figure, when it is a proportion.")
    denominator: int | None
    sample_size: int
    time_window: TimeWindow
    strength: EvidenceStrength
    strength_reason: str
    reason: str = Field(description="Why this conclusion follows from the numbers (or why none can be drawn).")
    limitations: list[str]
    consideration: str = Field(description="Suggested operational consideration, never an implemented change.")
    groups: list[InsightGroup] = []


class BoundedAdjustment(BaseModel):
    """What a recommendation could shift if adjustments were enabled. Always bounded; the deterministic
    rules stay the fallback."""

    target: str
    value: float
    bound: float


class Recommendation(BaseModel):
    recommendation_id: str
    insight_ids: list[str]
    text: str
    strength: EvidenceStrength
    implemented: bool = Field(default=False, description="Always false: recommendations change nothing by themselves.")
    adjustment: BoundedAdjustment | None = Field(
        default=None, description="Only present when learning adjustments are enabled in configuration."
    )


class SufficiencyEntry(BaseModel):
    capability: str
    status: EvidenceStrength
    reason: str


class LearningReport(BaseModel):
    source: FailureSource
    provenance: str
    population: str = Field(description="What was analysed, e.g. record counts or simulated seeds.")
    time_window: TimeWindow
    insights: list[Insight]
    recommendations: list[Recommendation]
    sufficiency: list[SufficiencyEntry]
    thresholds: dict[str, int | float | str]
    adjustments_enabled: bool
    operational_effect: str = (
        "None. This report does not change matching, donor state, recovery or any safety limit."
    )
    notice: str = (
        "Insights are descriptive and observational, from synthetic data. They are not evidence of "
        "real-world effectiveness, not causal conclusions and not medical or clinical findings."
    )
    data_notice: str
