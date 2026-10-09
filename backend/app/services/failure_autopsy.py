"""Failure Autopsy Engine.

Turns one or more failed coordination attempts into a structured, evidence-based explanation:
what failed, who/what failed, why, whether the cause looks donor-specific, channel-specific,
timing-related or network/context-related, whether it is an isolated failure or part of a pattern,
and what recovery might be worth considering next.

Deterministic rules only — no LLM, no randomness. "rule_confidence" is a deterministic score from
fixed, documented constants, never a machine-learning confidence. This is an operational
coordination analysis; it never makes or implies a medical decision.

Recorded vs simulated
----------------------
`analyze_request` / `analyze_failure` read **recorded** failures from the synthetic dataset
(source=RECORDED): "what actually happened". `analyze_simulated` takes an in-memory batch of
cascade-wave contacts built by the Adaptive Cascade Engine (source=SIMULATED): "what the
simulation produced". The two are never mixed into one autopsy, so the frontend's "what actually
happened" vs "simulated cascade" distinction stays intact.

Reuses, never duplicates
-------------------------
Blood-group compatibility, donor eligibility/state and candidate-pool context all come from the
Matching Engine (which itself delegates donor state to the Donor State Engine) — this module adds
no parallel donor-scoring logic. `FailureAutopsyRepository` reads only the existing `Failure` /
`CoordinationAttempt` / `Donor` / `DonorInteraction` rows.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.models.enums import FailureCategory, FailureSeverity, InteractionChannel, UrgencyLevel
from app.repositories.failure_autopsy_repository import FailureAutopsyRepository, RecordedFailureRow
from app.schemas.cascade import CascadeContact, SimulatedResponse
from app.schemas.failure_autopsy import (
    EvidenceItem,
    EvidenceType,
    FailurePatternType,
    FailureSource,
    IndividualFailureAutopsy,
    PatternFinding,
    RecoveryRecommendation,
    RequestAutopsy,
)
from app.services.donor_state import UnknownCode
from app.services.matching import MatchingEngine

# ---- demo autopsy settings (named constants; nothing scattered inline) -------------------------

MIN_PATTERN_FAILURES = 2                  # a "pattern" needs at least this many failures
LOCAL_POOL_REMAINING_THRESHOLD = 2        # "few" candidates left nearby, triggering LOCAL_POOL_FAILURE
BRIDGE_GROUP_FAILURE_SHARE = 0.5          # bridge-group failures must exceed this share of the batch
RECENT_DONATION_POOL_SHARE = 0.5          # gate-exclusion failures must exceed this share of the batch
CONFIDENCE_STEP_PER_EXTRA_FAILURE = 0.03  # confidence grows with corroborating evidence...
CONFIDENCE_MAX_BONUS = 0.15               # ...capped at this much above the pattern's base confidence
CONFIDENCE_CEILING = 0.97                 # never claim near-certainty; this stays a rule, not proof

GATE_FAILURE_TYPES = frozenset({FailureCategory.RECENT_DONATION, FailureCategory.DEFERRAL})
SYSTEMIC_PATTERNS = frozenset({
    FailurePatternType.CHANNEL_RESPONSE_FAILURE, FailurePatternType.LOCAL_POOL_FAILURE,
    FailurePatternType.BRIDGE_GROUP_FAILURE, FailurePatternType.CANDIDATE_POOL_EXHAUSTION,
    FailurePatternType.RECENT_DONATION_POOL, FailurePatternType.RESPONSE_WINDOW_FAILURE,
})
# First match wins when more than one pattern is detected in the same batch.
PATTERN_PRIORITY = (
    FailurePatternType.CANDIDATE_POOL_EXHAUSTION,
    FailurePatternType.CHANNEL_RESPONSE_FAILURE,
    FailurePatternType.BRIDGE_GROUP_FAILURE,
    FailurePatternType.LOCAL_POOL_FAILURE,
    FailurePatternType.RECENT_DONATION_POOL,
    FailurePatternType.RESPONSE_WINDOW_FAILURE,
)

PATTERN_BASE_CONFIDENCE = {
    FailurePatternType.CANDIDATE_POOL_EXHAUSTION: 0.95,  # directly counted: zero candidates remain
    FailurePatternType.CHANNEL_RESPONSE_FAILURE: 0.75,
    FailurePatternType.BRIDGE_GROUP_FAILURE: 0.70,
    FailurePatternType.LOCAL_POOL_FAILURE: 0.80,
    FailurePatternType.RECENT_DONATION_POOL: 0.85,       # directly counted: a demo eligibility rule, not inferred
    FailurePatternType.RESPONSE_WINDOW_FAILURE: 0.60,
}
PATTERN_SEVERITY = {
    FailurePatternType.CANDIDATE_POOL_EXHAUSTION: FailureSeverity.CRITICAL,
    FailurePatternType.CHANNEL_RESPONSE_FAILURE: FailureSeverity.HIGH,
    FailurePatternType.BRIDGE_GROUP_FAILURE: FailureSeverity.HIGH,
    FailurePatternType.LOCAL_POOL_FAILURE: FailureSeverity.HIGH,
    FailurePatternType.RECENT_DONATION_POOL: FailureSeverity.MEDIUM,
    FailurePatternType.RESPONSE_WINDOW_FAILURE: FailureSeverity.MEDIUM,
}
PATTERN_RECOMMENDATION = {
    FailurePatternType.CANDIDATE_POOL_EXHAUSTION: RecoveryRecommendation.HUMAN_COORDINATOR,
    FailurePatternType.CHANNEL_RESPONSE_FAILURE: RecoveryRecommendation.SWITCH_CHANNEL,
    FailurePatternType.BRIDGE_GROUP_FAILURE: RecoveryRecommendation.TRY_BRIDGE_GROUP,
    FailurePatternType.LOCAL_POOL_FAILURE: RecoveryRecommendation.EXPAND_SEARCH_RADIUS,
    FailurePatternType.RECENT_DONATION_POOL: RecoveryRecommendation.RE_RUN_MATCHING,
    FailurePatternType.RESPONSE_WINDOW_FAILURE: RecoveryRecommendation.INCREASE_WAVE_SIZE,
}
# Isolated (non-pattern) individual failures: recommendation by failure type.
INDIVIDUAL_RECOMMENDATION = {
    FailureCategory.NO_RESPONSE: RecoveryRecommendation.TRY_ALTERNATIVE_DONOR,
    FailureCategory.DECLINED: RecoveryRecommendation.TRY_ALTERNATIVE_DONOR,
    FailureCategory.UNAVAILABLE: RecoveryRecommendation.TRY_ALTERNATIVE_DONOR,
    FailureCategory.CONTACT_FAILURE: RecoveryRecommendation.SWITCH_CHANNEL,
    FailureCategory.FATIGUE: RecoveryRecommendation.TRY_ALTERNATIVE_DONOR,
    FailureCategory.RECENT_DONATION: RecoveryRecommendation.RE_RUN_MATCHING,
    FailureCategory.DEFERRAL: RecoveryRecommendation.RE_RUN_MATCHING,
    FailureCategory.ALREADY_CONTACTED: RecoveryRecommendation.RE_RUN_MATCHING,
    FailureCategory.CASCADE_EXHAUSTED: RecoveryRecommendation.HUMAN_COORDINATOR,
    FailureCategory.OTHER: RecoveryRecommendation.TRY_ALTERNATIVE_DONOR,
}
# Deterministic certainty of the observation itself: an explicit reply (DECLINED/UNAVAILABLE) is
# more certain than an absence of information (NO_RESPONSE); CASCADE_EXHAUSTED is a direct count.
INDIVIDUAL_FAILURE_CONFIDENCE = {
    FailureCategory.NO_RESPONSE: 0.90,
    FailureCategory.DECLINED: 0.95,
    FailureCategory.UNAVAILABLE: 0.90,
    FailureCategory.CONTACT_FAILURE: 0.60,
    FailureCategory.FATIGUE: 0.65,
    FailureCategory.RECENT_DONATION: 0.95,
    FailureCategory.DEFERRAL: 0.95,
    FailureCategory.ALREADY_CONTACTED: 0.90,
    FailureCategory.CASCADE_EXHAUSTED: 0.90,
    FailureCategory.OTHER: 0.40,
}

CHANNEL_LABEL = {
    InteractionChannel.SIMULATED_SMS: "simulated SMS",
    InteractionChannel.SIMULATED_CALL: "simulated call",
    InteractionChannel.SIMULATED_APP: "simulated app notification",
}
FAILURE_LABEL = {
    FailureCategory.NO_RESPONSE: "no response",
    FailureCategory.DECLINED: "declined",
    FailureCategory.UNAVAILABLE: "unavailable",
    FailureCategory.CONTACT_FAILURE: "contact failure",
    FailureCategory.FATIGUE: "coordination fatigue",
    FailureCategory.RECENT_DONATION: "recent donation (demo interval)",
    FailureCategory.DEFERRAL: "registry deferral",
    FailureCategory.ALREADY_CONTACTED: "already contacted",
    FailureCategory.CASCADE_EXHAUSTED: "cascade exhausted",
    FailureCategory.OTHER: "other",
}


# ---- neutral input shared by both sources -------------------------------------------------------


@dataclass(frozen=True)
class FailureObservation:
    """One failed coordination attempt, in a shape that is the same whether it came from the
    database (RECORDED) or from an in-memory cascade wave (SIMULATED)."""

    donor_code: str
    display_name: str
    blood_group: str
    failure_type: FailureCategory
    channel: InteractionChannel | None
    detected_at: datetime
    bridge_group_member: bool
    window_expired: bool
    reference: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class PatternContext:
    """Candidate-pool context for the batch being analysed. Built entirely from values the
    Matching Engine already computes — no extra queries."""

    remaining_in_radius: int
    filtered_outside_radius: int
    radius_known: bool
    urgency: UrgencyLevel


# ---- pure rules (unit-testable without a database) ----------------------------------------------


def _bump_for_urgency(severity: FailureSeverity, urgency: UrgencyLevel) -> FailureSeverity:
    """CRITICAL-urgency requests escalate operational severity by one level: every hour without a
    confirmed donor matters more when the patient's need is critical."""
    if urgency is not UrgencyLevel.CRITICAL:
        return severity
    order = (FailureSeverity.LOW, FailureSeverity.MEDIUM, FailureSeverity.HIGH, FailureSeverity.CRITICAL)
    return order[min(order.index(severity) + 1, len(order) - 1)]


def _pattern_confidence(pattern_type: FailurePatternType, supporting_failures: int) -> float:
    base = PATTERN_BASE_CONFIDENCE[pattern_type]
    bonus = min(CONFIDENCE_MAX_BONUS, CONFIDENCE_STEP_PER_EXTRA_FAILURE * max(0, supporting_failures - MIN_PATTERN_FAILURES))
    return round(min(CONFIDENCE_CEILING, base + bonus), 2)


def detect_patterns(observations: Sequence[FailureObservation], context: PatternContext) -> list[PatternFinding]:
    """Every pattern the evidence supports, most specific/certain first. Returns [] when nothing
    beyond a single isolated failure (or no clear pattern) is supported — never forces a pattern.

    With zero failures there is nothing to explain, so this returns [] immediately: a placeholder
    "nothing computed" context (e.g. remaining_in_radius=0 because no failures meant no context was
    fetched) must never be misread as evidence of CANDIDATE_POOL_EXHAUSTION."""
    if not observations:
        return []
    findings: dict[FailurePatternType, PatternFinding] = {}

    def add(pattern_type: FailurePatternType, supporting: Sequence[FailureObservation], channel, evidence, interpretation):  # type: ignore[no-untyped-def]
        severity = _bump_for_urgency(PATTERN_SEVERITY[pattern_type], context.urgency)
        findings[pattern_type] = PatternFinding(
            pattern_type=pattern_type, severity=severity,
            rule_confidence=_pattern_confidence(pattern_type, len(supporting)),
            supporting_failures=len(supporting), affected_donors=[o.donor_code for o in supporting],
            affected_channel=channel, donor_specific=False,
            channel_specific=pattern_type is FailurePatternType.CHANNEL_RESPONSE_FAILURE,
            timing_related=pattern_type in (FailurePatternType.RESPONSE_WINDOW_FAILURE, FailurePatternType.CHANNEL_RESPONSE_FAILURE),
            network_related=pattern_type in (
                FailurePatternType.LOCAL_POOL_FAILURE, FailurePatternType.BRIDGE_GROUP_FAILURE,
                FailurePatternType.CANDIDATE_POOL_EXHAUSTION, FailurePatternType.RECENT_DONATION_POOL,
            ),
            evidence=evidence, interpretation=interpretation, recommended_action=PATTERN_RECOMMENDATION[pattern_type],
        )

    # Context-based: no candidates left anywhere reachable right now.
    if context.remaining_in_radius == 0 and (not context.radius_known or context.filtered_outside_radius == 0):
        add(
            FailurePatternType.CANDIDATE_POOL_EXHAUSTION, observations, None,
            [
                EvidenceItem(type=EvidenceType.CONTEXT, description="No eligible candidates remain in the current search area."),
                EvidenceItem(
                    type=EvidenceType.CONTEXT,
                    description="No further compatible, active donors exist beyond the search radius either."
                    if context.radius_known else "The search already covers the whole dataset region.",
                ),
            ],
            "Evidence suggests the candidate pool for this request is exhausted: no reachable donor remains.",
        )

    no_response = [o for o in observations if o.failure_type is FailureCategory.NO_RESPONSE]
    if len(no_response) >= MIN_PATTERN_FAILURES:
        channels = {o.channel for o in no_response if o.channel is not None}
        if len(channels) == 1:
            (channel,) = channels
            add(
                FailurePatternType.CHANNEL_RESPONSE_FAILURE, no_response, channel,
                [
                    EvidenceItem(
                        type=EvidenceType.PATTERN,
                        description=f"{len(no_response)} donor(s) contacted via {CHANNEL_LABEL[channel]} all received no response.",
                    ),
                    *[
                        EvidenceItem(type=EvidenceType.OUTCOME, description="No response recorded for this contact.", reference=o.reference)
                        for o in no_response
                    ],
                ],
                f"Pattern indicates a {CHANNEL_LABEL[channel]} response failure: multiple donors failed to "
                "respond through the same channel.",
            )
        elif len(channels) > 1:
            add(
                FailurePatternType.RESPONSE_WINDOW_FAILURE, no_response, None,
                [EvidenceItem(
                    type=EvidenceType.PATTERN,
                    description=f"{len(no_response)} donor(s) across {len(channels)} channels all received no "
                    "response before their response window closed.",
                )],
                "Pattern indicates a response-window failure: donors are not replying in time, across more than "
                "one channel, so the window itself — not one channel — looks like the likely operational cause.",
            )

    bridge = [o for o in observations if o.bridge_group_member]
    if len(bridge) >= MIN_PATTERN_FAILURES and len(bridge) > len(observations) * BRIDGE_GROUP_FAILURE_SHARE:
        add(
            FailurePatternType.BRIDGE_GROUP_FAILURE, bridge, None,
            [EvidenceItem(
                type=EvidenceType.PATTERN,
                description=f"{len(bridge)} of {len(observations)} failure(s) involve donors from the patient's bridge group.",
            )],
            "Pattern indicates a bridge-group failure: multiple donors from the same bridge group failed to help.",
        )

    if (
        FailurePatternType.CANDIDATE_POOL_EXHAUSTION not in findings
        and context.radius_known
        and 0 < context.remaining_in_radius <= LOCAL_POOL_REMAINING_THRESHOLD
        and context.filtered_outside_radius > 0
    ):
        add(
            FailurePatternType.LOCAL_POOL_FAILURE, observations, None,
            [
                EvidenceItem(
                    type=EvidenceType.CONTEXT,
                    description=f"Only {context.remaining_in_radius} eligible candidate(s) remain in the current search area.",
                ),
                EvidenceItem(
                    type=EvidenceType.CONTEXT,
                    description=f"{context.filtered_outside_radius} more compatible, active donor(s) exist outside it.",
                ),
            ],
            "Evidence suggests a local pool failure: nearby donors are nearly exhausted while the wider region "
            "still has eligible candidates.",
        )

    gated = [o for o in observations if o.failure_type in GATE_FAILURE_TYPES]
    if len(gated) >= MIN_PATTERN_FAILURES and len(gated) > len(observations) * RECENT_DONATION_POOL_SHARE:
        add(
            FailurePatternType.RECENT_DONATION_POOL, gated, None,
            [EvidenceItem(
                type=EvidenceType.PATTERN,
                description=f"{len(gated)} of {len(observations)} candidate(s) are excluded by the recent-donation "
                "or registry-deferral demo rule.",
            )],
            "Pattern indicates a recent-donation pool effect: much of the nearby pool is temporarily ineligible "
            "under the demo donation-interval rule.",
        )

    return [findings[p] for p in PATTERN_PRIORITY if p in findings]


def _evidence_for(observation: FailureObservation) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if observation.channel is not None:
        items.append(EvidenceItem(
            type=EvidenceType.ATTEMPT, description=f"{CHANNEL_LABEL[observation.channel]} contact was recorded.",
            reference=observation.reference,
        ))
    outcome = f"{FAILURE_LABEL[observation.failure_type]} was recorded."
    if observation.failure_type is FailureCategory.NO_RESPONSE and observation.window_expired:
        outcome = "No response was recorded, and the response window expired."
    items.append(EvidenceItem(type=EvidenceType.OUTCOME, description=outcome, reference=observation.reference))
    if observation.detail:
        items.append(EvidenceItem(type=EvidenceType.OUTCOME, description=observation.detail, reference=observation.reference))
    return items


def analyze_individual(
    observation: FailureObservation, request_code: str, source: FailureSource, pattern: PatternFinding | None
) -> IndividualFailureAutopsy:
    """One failure, in isolation, plus whether it belongs to a batch pattern (if one was found)."""
    in_pattern = pattern is not None and observation.donor_code in pattern.affected_donors
    severity = (
        FailureSeverity.CRITICAL if observation.failure_type is FailureCategory.CASCADE_EXHAUSTED
        else FailureSeverity.HIGH if in_pattern
        else FailureSeverity.LOW if observation.failure_type is FailureCategory.DECLINED
        else FailureSeverity.MEDIUM
    )
    recommendation = pattern.recommended_action if in_pattern else INDIVIDUAL_RECOMMENDATION[observation.failure_type]
    timing_related = observation.failure_type is FailureCategory.NO_RESPONSE or (
        pattern is not None and in_pattern and pattern.timing_related
    )
    summary = (
        f"{observation.display_name} ({observation.donor_code}): {FAILURE_LABEL[observation.failure_type]}."
        if observation.failure_type is not FailureCategory.NO_RESPONSE
        else f"{observation.display_name} ({observation.donor_code}) did not respond within the configured response window."
    )
    return IndividualFailureAutopsy(
        source=source, failure_type=observation.failure_type,
        severity=severity,  # urgency-bumped once, consistently, by build_autopsy
        rule_confidence=INDIVIDUAL_FAILURE_CONFIDENCE[observation.failure_type],
        summary=summary, evidence=_evidence_for(observation), affected_donor=observation.donor_code,
        affected_request=request_code, affected_channel=observation.channel, detected_at=observation.detected_at,
        reference=observation.reference, donor_specific=not in_pattern,
        channel_specific=in_pattern and pattern.channel_specific,
        timing_related=timing_related, network_related=in_pattern and pattern.network_related,
        recommended_next_action=recommendation,
    )


def _choose_recommendation(patterns: Sequence[PatternFinding], individuals: Sequence[IndividualFailureAutopsy]) -> RecoveryRecommendation | None:
    if patterns:
        return patterns[0].recommended_action
    if individuals:
        return individuals[0].recommended_next_action
    return None


_SEVERITY_ORDER = (FailureSeverity.LOW, FailureSeverity.MEDIUM, FailureSeverity.HIGH, FailureSeverity.CRITICAL)


def _marker_pattern(individuals: Sequence[IndividualFailureAutopsy]) -> PatternFinding | None:
    """When no genuine multi-failure pattern is found, `dominant_pattern` still carries a
    `pattern_type` (per the taxonomy): INDIVIDUAL_DONOR_FAILURE for one isolated failure,
    UNKNOWN_PATTERN for several failures whose causes do not match any specific pattern rule.
    `pattern_detected` stays false for both — this never claims a pattern the evidence doesn't support."""
    if not individuals:
        return None
    pattern_type = FailurePatternType.INDIVIDUAL_DONOR_FAILURE if len(individuals) == 1 else FailurePatternType.UNKNOWN_PATTERN
    severity = max((i.severity for i in individuals), key=_SEVERITY_ORDER.index)
    interpretation = (
        "Only one failure was analysed; a single data point does not support any operational pattern."
        if pattern_type is FailurePatternType.INDIVIDUAL_DONOR_FAILURE
        else "The failure causes are mixed and do not match a recognised operational pattern."
    )
    return PatternFinding(
        pattern_type=pattern_type, severity=severity, rule_confidence=0.0, supporting_failures=len(individuals),
        affected_donors=[i.affected_donor for i in individuals], affected_channel=None,
        donor_specific=pattern_type is FailurePatternType.INDIVIDUAL_DONOR_FAILURE, channel_specific=False,
        timing_related=False, network_related=False, evidence=[
            EvidenceItem(type=EvidenceType.CONTEXT, description=interpretation)
        ], interpretation=interpretation, recommended_action=individuals[0].recommended_next_action,
    )


def _explanation(
    request_code: str, individuals: Sequence[IndividualFailureAutopsy], patterns: Sequence[PatternFinding], source: FailureSource
) -> str:
    if not individuals:
        return f"No {source.value.lower()} failures to analyse for {request_code}."
    if patterns:
        dominant = patterns[0]
        return (
            f"{len(individuals)} failure(s) analysed for {request_code}. {dominant.interpretation} "
            f"Recommended to consider: {dominant.recommended_action.value.replace('_', ' ').lower()}."
        )
    if len(individuals) == 1:
        only = individuals[0]
        return f"{only.summary} This looks like an isolated, donor-specific failure, not a pattern."
    return (
        f"{len(individuals)} failure(s) analysed for {request_code}. The causes are mixed and do not point to a "
        "single operational pattern; each failure is explained individually."
    )


def build_autopsy(
    request_code: str, source: FailureSource, observations: Sequence[FailureObservation],
    context: PatternContext, data_notice: str, analysis_time: datetime,
) -> RequestAutopsy:
    """Pure assembly: individual analyses + pattern detection + one recommendation. No I/O."""
    patterns = detect_patterns(observations, context)
    dominant = patterns[0] if patterns else None
    individuals = [analyze_individual(o, request_code, source, dominant) for o in observations]
    individuals = [i.model_copy(update={"severity": _bump_for_urgency(i.severity, context.urgency)}) for i in individuals]
    dominant_or_marker = dominant or _marker_pattern(individuals)
    return RequestAutopsy(
        request_code=request_code, analysis_time=analysis_time, source=source, failures_analyzed=len(observations),
        individual_failures=individuals, patterns=patterns, pattern_detected=bool(patterns), dominant_pattern=dominant_or_marker,
        recommended_action=_choose_recommendation(patterns, individuals), explanation=_explanation(request_code, individuals, patterns, source),
        data_notice=data_notice,
    )


# ---- engine (DB-backed RECORDED path; pure SIMULATED path) --------------------------------------


class FailureAutopsyEngine:
    def __init__(
        self, repository: FailureAutopsyRepository, matching: MatchingEngine, now: datetime, data_notice: str
    ) -> None:
        self._repo = repository
        self._matching = matching
        self._now = now
        self._data_notice = data_notice

    def _context(self, request_code: str, evaluate_at: str) -> PatternContext:
        """Candidate-pool context for the whole request, reusing the Matching Engine (no duplicate query)."""
        result = self._matching.match(request_code, limit=1, evaluate_at=evaluate_at)
        return PatternContext(
            remaining_in_radius=result.eligible_candidate_count,
            filtered_outside_radius=result.discovery.filtered_outside_radius,
            radius_known=result.discovery.radius_km is not None,
            urgency=result.request.urgency_level,
        )

    @staticmethod
    def _observation(row: RecordedFailureRow, bridge_group_id: int | None) -> FailureObservation:
        return FailureObservation(
            donor_code=row.donor_code, display_name=row.display_name, blood_group=row.blood_group,
            failure_type=row.failure_category, channel=row.channel, detected_at=row.detected_at,
            bridge_group_member=bridge_group_id is not None and row.bridge_group_id == bridge_group_id,
            window_expired=row.window_expired, reference=row.failure_code, detail=row.failure_reason,
        )

    def analyze_request(self, request_code: str, evaluate_at: str = "auto") -> RequestAutopsy:
        """RECORDED: analyse every Failure row attached to this request's coordination attempts."""
        request = self._repo.get_request(request_code)
        if request is None:
            raise UnknownCode("Request", request_code)
        rows = self._repo.recorded_failures(request.id)
        context = self._context(request_code, evaluate_at) if rows else PatternContext(0, 0, True, request.urgency_level)
        observations = [self._observation(row, request.patient.bridge_group_id) for row in rows]
        return build_autopsy(request_code, FailureSource.RECORDED, observations, context, self._data_notice, self._now)

    def analyze_failure(self, request_code: str, failure_code: str) -> IndividualFailureAutopsy:
        """RECORDED: analyse exactly one failure by its failure_code."""
        request = self._repo.get_request(request_code)
        if request is None:
            raise UnknownCode("Request", request_code)
        row = self._repo.get_failure(request.id, failure_code)
        if row is None:
            raise UnknownCode("Failure", failure_code)
        observation = self._observation(row, request.patient.bridge_group_id)
        result = analyze_individual(observation, request_code, FailureSource.RECORDED, pattern=None)
        return result.model_copy(update={"severity": _bump_for_urgency(result.severity, request.urgency_level)})

    def analyze_simulated(
        self, request_code: str, observations: Sequence[FailureObservation], context: PatternContext,
    ) -> RequestAutopsy:
        """SIMULATED: analyse a batch of failed contacts from one Adaptive Cascade wave. Pure —
        the caller (the cascade engine) already has everything needed; no DB access here."""
        return build_autopsy(request_code, FailureSource.SIMULATED, observations, context, self._data_notice, self._now)


def observation_from_contact(contact: CascadeContact) -> FailureObservation:
    """Adapts one failed Adaptive Cascade contact into a FailureObservation. `contact.response` must
    not be ACCEPTED — the caller filters to failed contacts before calling this."""
    failure_type = {
        SimulatedResponse.NO_RESPONSE: FailureCategory.NO_RESPONSE,
        SimulatedResponse.DECLINED: FailureCategory.DECLINED,
        SimulatedResponse.UNAVAILABLE: FailureCategory.UNAVAILABLE,
    }[contact.response]
    return FailureObservation(
        donor_code=contact.donor_code, display_name=contact.display_name, blood_group=contact.blood_group.value,
        failure_type=failure_type, channel=contact.channel,
        detected_at=contact.responded_at or contact.sent_at,
        bridge_group_member=contact.bridge_group_member,
        window_expired=contact.response is SimulatedResponse.NO_RESPONSE,
        reference=contact.donor_code, detail=contact.note,
    )
