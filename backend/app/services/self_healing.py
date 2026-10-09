"""Self-Healing Engine: "what should the coordination system change next?"

    Failure Autopsy   "What happened?"          (consumed here, never repeated)
    Self-Healing      "What should change?"     (this file)
    Learning          "What should be remembered?"

Given the cascade state and the Failure Autopsy of the wave that just failed, the engine returns a
RecoveryPlan: ONE primary action, fallback actions, the reason, the evidence and the exact changes to
apply. It is pure and deterministic (no I/O, no clock, no randomness, no LLM) and cheap: the candidate
counts it needs were already computed by the Matching Engine for the wave.

It is coordination recovery only: it never diagnoses, never decides treatment and never promises that a
donor will respond. Escalations hand the request to people; nothing irreversible happens automatically.

POLICY: first matching rule wins (this order is the single source of truth; see POLICY_RULES)

    P1 SAFETY_LIMIT        last allowed wave, MAX_RECOVERY_ATTEMPTS used, or HUMAN_ESCALATION_CONTACTS reached
                           → escalate (BLOOD_BANK_ESCALATION if CRITICAL urgency, else HUMAN_COORDINATOR)
    P2 POOL_EXHAUSTED      no eligible candidate left → EXPAND_SEARCH_RADIUS, or escalate at the widest radius
    P3 CRITICAL_STALL      CRITICAL urgency + CRITICAL failure severity after CRITICAL_ESCALATION_WAVES failed
                           waves → BLOOD_BANK_ESCALATION
    P4 BRIDGE_FAILURE      bridge-group failure pattern → TRY_ALTERNATIVE_BRIDGE_GROUP (non-members first)
    P5 CHANNEL_FAILURE     channel response failure, switches left → SWITCH_CHANNEL (+1 wave size)
    P6 LOCAL_POOL          local-pool pattern, repeated failed waves, or too few non-fatigued candidates left
                           → EXPAND_SEARCH_RADIUS (while a wider radius exists)
    P7 REPEATED_FAILURE    second failed wave, bridge members remain → TRY_ALTERNATIVE_BRIDGE_GROUP (members first)
    P8 WIDEN_WAVE          several failures, plenty of candidates left → INCREASE_WAVE_SIZE
    P9 ISOLATED_FAILURE    one donor-level failure → TRY_ALTERNATIVE_DONOR (failed donor already excluded)
    P10 DEFAULT            otherwise → RE_RUN_MATCHING

Requests with nothing outstanding get NO_CHANGE before any rule runs.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.models.enums import FailureSeverity, InteractionChannel, RecoveryActionType, UrgencyLevel
from app.schemas.failure_autopsy import FailurePatternType, FailureSource, RecoveryRecommendation, RequestAutopsy
from app.schemas.self_healing import (
    BridgePriority,
    CascadeStateSnapshot,
    EscalationSummary,
    EscalationType,
    RecoveryChanges,
    RecoveryPlan,
    RecoveryTrigger,
)
from app.services.matching import RADIUS_STEPS_KM

# ---- safe adaptation limits (configurable constants) ---------------------------------------------

MAX_WAVE_SIZE = 6                    # a wave never grows past this
MAX_RADIUS_STEP = len(RADIUS_STEPS_KM) - 1   # widest search radius (region-wide)
MAX_RECOVERY_ATTEMPTS = 4            # automatic recoveries per request before people take over
MAX_CHANNEL_SWITCHES = 1             # one channel switch; flip-flopping is not a strategy
HUMAN_ESCALATION_CONTACTS = 20       # donors contacted without securing the requirement
CRITICAL_ESCALATION_WAVES = 3        # failed waves before CRITICAL urgency + severity goes to the blood bank
WAVE_SIZE_STEP = 1
URGENT_WAVE_SIZE_STEP = 1            # kept equal to WAVE_SIZE_STEP: one more donor per recovery
HIGH_FATIGUE_SCORE = 60              # donor fatigue score at which a candidate counts as fatigued
REPEATED_FAILURE_WAVES = 2           # failed waves before the bridge group is tried
LOCAL_POOL_WAVES = 3                 # failed waves before the radius is widened regardless of pattern

RULE_STRENGTH = {
    "P1": 0.95, "P2": 0.90, "P3": 0.85, "P4": 0.80, "P5": 0.80, "P6": 0.75, "P7": 0.65, "P8": 0.60,
    "P9": 0.55, "P10": 0.45, "P0": 0.95,
}
MAX_RULE_STRENGTH = 0.95

POLICY_RULES = (
    ("P1", "Safety limit reached"), ("P2", "Candidate pool exhausted"), ("P3", "Critical stall"),
    ("P4", "Bridge-group failure"), ("P5", "Channel response failure"), ("P6", "Local pool failing"),
    ("P7", "Repeated failed waves"), ("P8", "Several failures, enough candidates"),
    ("P9", "Isolated donor failure"), ("P10", "Default: re-run matching"),
)

# RecoveryActionType is the persisted action vocabulary (RecoveryAction.action_type) and the cascade's
# legacy HealingDecision. Plans map onto it so the two never drift.
PERSISTED_ACTION: dict[RecoveryRecommendation, RecoveryActionType] = {
    RecoveryRecommendation.NO_CHANGE: RecoveryActionType.NEXT_DONOR,
    RecoveryRecommendation.RE_RUN_MATCHING: RecoveryActionType.NEXT_DONOR,
    RecoveryRecommendation.TRY_ALTERNATIVE_DONOR: RecoveryActionType.NEXT_DONOR,
    RecoveryRecommendation.INCREASE_WAVE_SIZE: RecoveryActionType.NEXT_DONOR,
    RecoveryRecommendation.SWITCH_CHANNEL: RecoveryActionType.ALTERNATIVE_DONOR,
    RecoveryRecommendation.TRY_ALTERNATIVE_BRIDGE_GROUP: RecoveryActionType.BRIDGE_GROUP_ESCALATION,
    RecoveryRecommendation.EXPAND_SEARCH_RADIUS: RecoveryActionType.EXPANDED_SEARCH,
    RecoveryRecommendation.HUMAN_COORDINATOR: RecoveryActionType.HUMAN_COORDINATOR_REVIEW,
    RecoveryRecommendation.BLOOD_BANK_ESCALATION: RecoveryActionType.BLOOD_BANK_REFERRAL,
}
ESCALATION_ACTIONS = (RecoveryRecommendation.HUMAN_COORDINATOR, RecoveryRecommendation.BLOOD_BANK_ESCALATION)
URGENT = (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL)
RADIUS_LABELS = tuple("region-wide" if km is None else f"{km:g} km" for km in RADIUS_STEPS_KM)


class MalformedStateError(ValueError):
    """The cascade state handed to the engine is internally inconsistent."""


# ---- inputs and outputs ----------------------------------------------------------------------------


@dataclass(frozen=True)
class CascadeState:
    """Everything the policy needs about the cascade right after a failed wave."""

    wave_number: int
    max_waves: int
    urgency: UrgencyLevel
    wave_size: int
    channel_override: InteractionChannel | None
    radius_step: int
    contacted_total: int
    remaining_candidates: int
    fatigued_remaining: int = 0
    bridge_remaining: int = 0
    bridge_priority: BridgePriority = BridgePriority.DEFAULT
    recovery_attempts: int = 0
    channel_switches: int = 0
    units_outstanding: int = 1
    wave_contacted: int = 0
    no_response_channels: tuple[InteractionChannel, ...] = ()
    failure_totals: Mapping[str, int] = field(default_factory=dict)
    applied_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class WaveSettings:
    """The adjustable part of the cascade; plans are applied to it."""

    wave_size: int
    channel_override: InteractionChannel | None = None
    radius_step: int = 0
    bridge_priority: BridgePriority = BridgePriority.DEFAULT
    channel_switches: int = 0


@dataclass(frozen=True)
class FailureSignal:
    """What the policy reads from a Failure Autopsy (or, for the legacy adapter, from a wave summary)."""


    pattern: FailurePatternType | None
    severity: FailureSeverity | None
    confidence: float | None
    failures: int
    recommended: RecoveryRecommendation | None


@dataclass(frozen=True)
class _Outcome:
    rule_id: str
    action: RecoveryRecommendation
    reason: str
    evidence: list[str]
    changes: RecoveryChanges
    escalation: EscalationType | None = None


# ---- state helpers ---------------------------------------------------------------------------------


def validate_state(state: CascadeState) -> None:
    problems = []
    if state.wave_number < 1 or state.max_waves < 1 or state.wave_number > state.max_waves:
        problems.append("wave_number must be within 1..max_waves")
    if not 1 <= state.wave_size <= MAX_WAVE_SIZE:
        problems.append(f"wave_size must be within 1..{MAX_WAVE_SIZE}")
    if not 0 <= state.radius_step <= MAX_RADIUS_STEP:
        problems.append(f"radius_step must be within 0..{MAX_RADIUS_STEP}")
    if min(state.contacted_total, state.remaining_candidates, state.fatigued_remaining, state.bridge_remaining,
           state.recovery_attempts, state.channel_switches, state.units_outstanding, state.wave_contacted) < 0:
        problems.append("counts must not be negative")
    if state.fatigued_remaining > state.remaining_candidates or state.bridge_remaining > state.remaining_candidates:
        problems.append("fatigued/bridge candidates cannot exceed remaining candidates")
    if problems:
        raise MalformedStateError("; ".join(problems))


def signal_from_autopsy(autopsy: RequestAutopsy | None) -> FailureSignal:
    if autopsy is None:
        return FailureSignal(None, None, None, 0, None)
    pattern = autopsy.dominant_pattern
    return FailureSignal(
        pattern.pattern_type if pattern else None, pattern.severity if pattern else None,
        pattern.rule_confidence if pattern else None, autopsy.failures_analyzed, autopsy.recommended_action,
    )


def _label(value: object) -> str:
    if isinstance(value, InteractionChannel):
        return {InteractionChannel.SIMULATED_SMS: "SMS", InteractionChannel.SIMULATED_CALL: "call",
                InteractionChannel.SIMULATED_APP: "app"}[value]
    return str(getattr(value, "value", value)).replace("_", " ").lower()


def _usable(state: CascadeState) -> int:
    return state.remaining_candidates - state.fatigued_remaining


def _can_widen_radius(state: CascadeState) -> bool:
    return state.radius_step < MAX_RADIUS_STEP


def _wave_size_after(state: CascadeState, step: int) -> int:
    return min(state.wave_size + step, MAX_WAVE_SIZE)


def _size_step(state: CascadeState) -> int:
    return URGENT_WAVE_SIZE_STEP if state.urgency in URGENT else WAVE_SIZE_STEP


def _can_switch_channel(state: CascadeState) -> bool:
    """A switch always moves to a simulated call, the strongest channel; once calls are in use there is no
    better channel to move to, and the limit on switches applies as well."""
    in_use = set(state.no_response_channels) or ({state.channel_override} if state.channel_override else set())
    return state.channel_switches < MAX_CHANNEL_SWITCHES and in_use != {InteractionChannel.SIMULATED_CALL}


def _escalation_type(state: CascadeState) -> EscalationType:
    return EscalationType.BLOOD_BANK if state.urgency is UrgencyLevel.CRITICAL else EscalationType.HUMAN_COORDINATOR


def _context_evidence(state: CascadeState, signal: FailureSignal) -> list[str]:
    evidence = [f"{state.urgency.value} urgency", f"Wave {state.wave_number} of {state.max_waves} did not secure the requirement"]
    if state.wave_contacted:
        evidence.append(f"{state.wave_contacted} donors contacted in the last wave; {state.contacted_total} in total")
    if signal.pattern is not None:
        confidence = f", rule confidence {signal.confidence:.2f}" if signal.confidence is not None else ""
        severity = f" · {signal.severity.value} severity" if signal.severity else ""
        evidence.append(f"Failure Autopsy pattern {signal.pattern.value}{severity}{confidence}")
    evidence.append(
        f"{state.remaining_candidates} eligible candidates remain ({state.fatigued_remaining} with high fatigue) "
        f"within {RADIUS_LABELS[state.radius_step]}"
    )
    return evidence


# ---- the policy (first match wins) -----------------------------------------------------------------


def _escalate(state: CascadeState, rule: str, reason: str, evidence: list[str], kind: EscalationType | None = None) -> _Outcome:
    kind = kind or _escalation_type(state)
    action = (RecoveryRecommendation.BLOOD_BANK_ESCALATION if kind is EscalationType.BLOOD_BANK
              else RecoveryRecommendation.HUMAN_COORDINATOR)
    return _Outcome(rule, action, reason, evidence, RecoveryChanges(), kind)


def _p1(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if state.wave_number >= state.max_waves:
        reason = f"The wave limit ({state.max_waves}) was reached without securing the requirement."
    elif state.recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
        reason = f"{state.recovery_attempts} automatic recoveries were already tried (limit {MAX_RECOVERY_ATTEMPTS})."
    elif state.contacted_total >= HUMAN_ESCALATION_CONTACTS:
        reason = f"{state.contacted_total} donors were contacted without securing the requirement (limit {HUMAN_ESCALATION_CONTACTS})."
    else:
        return None
    evidence = _context_evidence(state, signal) + [
        f"Recovery attempts {state.recovery_attempts} of {MAX_RECOVERY_ATTEMPTS}",
    ]
    return _escalate(state, "P1", reason, evidence)


def _p2(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if state.remaining_candidates > 0:
        return None
    evidence = _context_evidence(state, signal)
    if _can_widen_radius(state):
        step = state.radius_step + 1
        return _Outcome("P2", RecoveryRecommendation.EXPAND_SEARCH_RADIUS,
                        f"No eligible candidates are left within {RADIUS_LABELS[state.radius_step]}; the search can still be widened.",
                        evidence, RecoveryChanges(radius_step=step, radius_km=RADIUS_STEPS_KM[step], radius_label=RADIUS_LABELS[step]))
    return _escalate(state, "P2", "No eligible candidates are left anywhere in the searched region.", evidence)


def _p3(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if (state.urgency is UrgencyLevel.CRITICAL and signal.severity is FailureSeverity.CRITICAL
            and state.wave_number >= CRITICAL_ESCALATION_WAVES):
        return _escalate(
            state, "P3",
            f"CRITICAL urgency with CRITICAL failure severity after {state.wave_number} failed waves; "
            "institutional supply is better placed than further outreach.",
            _context_evidence(state, signal), EscalationType.BLOOD_BANK)
    return None


def _p4(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if (signal.pattern is FailurePatternType.BRIDGE_GROUP_FAILURE and state.bridge_priority is not BridgePriority.NON_BRIDGE_FIRST
            and state.remaining_candidates - state.bridge_remaining > 0):
        return _Outcome("P4", RecoveryRecommendation.TRY_ALTERNATIVE_BRIDGE_GROUP,
                        "Bridge-group donors failed repeatedly; the next wave tries donors outside the bridge group first.",
                        _context_evidence(state, signal), RecoveryChanges(bridge_priority=BridgePriority.NON_BRIDGE_FIRST))
    return None


def _p5(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if signal.pattern is not FailurePatternType.CHANNEL_RESPONSE_FAILURE or not _can_switch_channel(state):
        return None
    target = InteractionChannel.SIMULATED_CALL
    size = _wave_size_after(state, WAVE_SIZE_STEP)
    failed_channel = next(iter(set(state.no_response_channels)), None)
    via = f" through {_label(failed_channel)}" if failed_channel and len(set(state.no_response_channels)) == 1 else ""
    reason = (f"{len(state.no_response_channels) or 'Several'} donors contacted{via} did not respond; "
              f"the next wave uses {_label(target)} instead.")
    changes = RecoveryChanges(channel=target, wave_size=size if size != state.wave_size else None)
    evidence = _context_evidence(state, signal) + [
        f"{len(state.no_response_channels)} no-response contacts on one channel",
        f"Channel switches {state.channel_switches} of {MAX_CHANNEL_SWITCHES}",
    ]
    return _Outcome("P5", RecoveryRecommendation.SWITCH_CHANNEL, reason, evidence, changes)


def _p6(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if not _can_widen_radius(state):
        return None
    local = signal.pattern is FailurePatternType.LOCAL_POOL_FAILURE
    repeated = state.wave_number >= LOCAL_POOL_WAVES
    thin = _usable(state) < state.wave_size
    if not (local or repeated or thin):
        return None
    why = ("The local pool is failing" if local else f"{state.wave_number} waves failed in a row" if repeated
           else "Too few non-fatigued candidates remain for another wave")
    step = state.radius_step + 1
    return _Outcome("P6", RecoveryRecommendation.EXPAND_SEARCH_RADIUS,
                    f"{why}; widening the search from {RADIUS_LABELS[state.radius_step]} to {RADIUS_LABELS[step]} for fresh candidates.",
                    _context_evidence(state, signal),
                    RecoveryChanges(radius_step=step, radius_km=RADIUS_STEPS_KM[step], radius_label=RADIUS_LABELS[step]))


def _p7(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if (state.wave_number >= REPEATED_FAILURE_WAVES and state.bridge_remaining > 0
            and state.bridge_priority is BridgePriority.DEFAULT):
        return _Outcome("P7", RecoveryRecommendation.TRY_ALTERNATIVE_BRIDGE_GROUP,
                        f"{state.wave_number} waves failed; the next wave tries the patient's bridge-group donors first.",
                        _context_evidence(state, signal), RecoveryChanges(bridge_priority=BridgePriority.BRIDGE_FIRST))
    return None


def _p8(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if signal.failures >= 2 and state.wave_size < MAX_WAVE_SIZE and _usable(state) >= 2 * state.wave_size:
        size = _wave_size_after(state, _size_step(state))
        silent = len(state.no_response_channels) * 2 >= signal.failures  # mostly unanswered, not declined
        pin_calls = (silent and state.channel_override is not InteractionChannel.SIMULATED_CALL
                     and state.channel_switches < MAX_CHANNEL_SWITCHES)
        no_better_channel = (signal.pattern is FailurePatternType.CHANNEL_RESPONSE_FAILURE
                             and not _can_switch_channel(state))
        reason = ("Unanswered contacts already used simulated calls, the strongest channel, so there is no better "
                  "channel to switch to. " if no_better_channel else "")
        reason += (f"{signal.failures} donors in the last wave did not help, but {_usable(state)} usable candidates remain; "
                  f"contacting more donors per wave ({state.wave_size} → {size})")
        reason += " and reaching all of them by simulated call, since most did not reply." if pin_calls else "."
        return _Outcome("P8", RecoveryRecommendation.INCREASE_WAVE_SIZE, reason, _context_evidence(state, signal),
                        RecoveryChanges(wave_size=size, channel=InteractionChannel.SIMULATED_CALL if pin_calls else None))
    return None


def _p9(state: CascadeState, signal: FailureSignal) -> _Outcome | None:
    if signal.pattern is FailurePatternType.INDIVIDUAL_DONOR_FAILURE or signal.failures == 1:
        return _Outcome("P9", RecoveryRecommendation.TRY_ALTERNATIVE_DONOR,
                        "One donor could not help; the next wave continues with other donors (the failed donor stays excluded).",
                        _context_evidence(state, signal), RecoveryChanges())
    return None


def _p10(state: CascadeState, signal: FailureSignal) -> _Outcome:
    return _Outcome("P10", RecoveryRecommendation.RE_RUN_MATCHING,
                    "No stronger rule applies; matching is re-run without the donors already contacted.",
                    _context_evidence(state, signal), RecoveryChanges())


_RULES = (_p1, _p2, _p3, _p4, _p5, _p6, _p7, _p8, _p9)


def _fallbacks(state: CascadeState, primary: RecoveryRecommendation) -> list[RecoveryRecommendation]:
    """Remaining levers that are still inside the safety limits, in policy order."""
    if primary is RecoveryRecommendation.BLOOD_BANK_ESCALATION:
        return [RecoveryRecommendation.HUMAN_COORDINATOR]
    if primary is RecoveryRecommendation.HUMAN_COORDINATOR:
        return []
    options = []
    if _can_switch_channel(state):
        options.append(RecoveryRecommendation.SWITCH_CHANNEL)
    if state.wave_size < MAX_WAVE_SIZE:
        options.append(RecoveryRecommendation.INCREASE_WAVE_SIZE)
    if state.bridge_remaining > 0 and state.bridge_priority is BridgePriority.DEFAULT:
        options.append(RecoveryRecommendation.TRY_ALTERNATIVE_BRIDGE_GROUP)
    if _can_widen_radius(state):
        options.append(RecoveryRecommendation.EXPAND_SEARCH_RADIUS)
    options.append(RecoveryRecommendation.BLOOD_BANK_ESCALATION if state.urgency is UrgencyLevel.CRITICAL
                   else RecoveryRecommendation.HUMAN_COORDINATOR)
    return [o for o in options if o is not primary][:3]


EXPECTED_EFFECT = {
    RecoveryRecommendation.NO_CHANGE: "Nothing is outstanding, so the coordination strategy stays as it is.",
    RecoveryRecommendation.SWITCH_CHANNEL: "The next wave reaches donors through a different channel, which may improve response; this is not guaranteed.",
    RecoveryRecommendation.INCREASE_WAVE_SIZE: "More donors are contacted at once, which may shorten the wait for a reply; availability is not guaranteed.",
    RecoveryRecommendation.TRY_ALTERNATIVE_DONOR: "Other eligible donors are contacted next; none is guaranteed to be available.",
    RecoveryRecommendation.TRY_ALTERNATIVE_BRIDGE_GROUP: "The bridge-group strategy changes for the next wave, which may reach donors who respond differently.",
    RecoveryRecommendation.EXPAND_SEARCH_RADIUS: "A wider search area adds candidates, usually further from the patient; response is not guaranteed.",
    RecoveryRecommendation.RE_RUN_MATCHING: "The candidate ranking is recalculated without donors already contacted.",
    RecoveryRecommendation.HUMAN_COORDINATOR: "Automated outreach stops so a coordinator can decide the next step.",
    RecoveryRecommendation.BLOOD_BANK_ESCALATION: "Automated outreach stops and institutional supply is recommended for a person to pursue.",
}
HUMAN_ACTION = {
    EscalationType.HUMAN_COORDINATOR: (
        "A coordinator should review this request, reach donors by approved means and decide whether to widen "
        "the donor registry search or adjust the requirement date."
    ),
    EscalationType.BLOOD_BANK: (
        "A coordinator should contact the institutional blood bank about available supply for this request. "
        "This is a human decision; Carbon Copy takes no action on its own."
    ),
}


class SelfHealingEngine:
    """Stateless: all inputs arrive as arguments, so plans are reproducible and trivially testable."""

    def plan(
        self,
        request_code: str,
        state: CascadeState,
        autopsy: RequestAutopsy | None,
        *,
        source: FailureSource = FailureSource.SIMULATED,
    ) -> RecoveryPlan:
        """Raises MalformedStateError for an inconsistent state."""
        return self.plan_from_signal(request_code, state, signal_from_autopsy(autopsy), source=source)

    def plan_from_signal(
        self, request_code: str, state: CascadeState, signal: FailureSignal,
        *, source: FailureSource = FailureSource.SIMULATED,
    ) -> RecoveryPlan:
        validate_state(state)
        if state.units_outstanding == 0:
            outcome = _Outcome("P0", RecoveryRecommendation.NO_CHANGE,
                               "The requirement is already secured; there is nothing to recover.",
                               [f"{state.urgency.value} urgency", "No units outstanding"], RecoveryChanges())
            name = "Nothing outstanding"
        else:
            outcome = next((o for rule in _RULES if (o := rule(state, signal)) is not None), None) or _p10(state, signal)
            name = dict(POLICY_RULES)[outcome.rule_id]
        strength = RULE_STRENGTH[outcome.rule_id]
        if signal.confidence is not None:
            strength = (strength + signal.confidence) / 2
        escalation = self._escalation(state, outcome) if outcome.escalation else None
        return RecoveryPlan(
            request_code=request_code, source=source, wave_number=state.wave_number,
            trigger=RecoveryTrigger(pattern=signal.pattern, severity=signal.severity), urgency=state.urgency,
            autopsy_recommended=signal.recommended, primary_action=outcome.action,
            fallback_actions=_fallbacks(state, outcome.action) if state.units_outstanding else [],
            rule_id=outcome.rule_id, rule_name=name, rule_strength=round(min(strength, MAX_RULE_STRENGTH), 2),
            reason=outcome.reason, evidence=outcome.evidence, current_state=self._snapshot(state),
            changes=outcome.changes, expected_effect=EXPECTED_EFFECT[outcome.action],
            requires_human_intervention=outcome.escalation is not None, escalation_type=outcome.escalation,
            escalation=escalation,
        )

    @staticmethod
    def _snapshot(state: CascadeState) -> CascadeStateSnapshot:
        return CascadeStateSnapshot(
            wave_number=state.wave_number, max_waves=state.max_waves, wave_size=state.wave_size,
            channel=state.channel_override, radius_label=RADIUS_LABELS[state.radius_step],
            donors_contacted=state.contacted_total, consecutive_failed_waves=state.wave_number,
            recovery_attempts=state.recovery_attempts, channel_switches=state.channel_switches,
            eligible_remaining=state.remaining_candidates, fatigued_remaining=state.fatigued_remaining,
            bridge_members_remaining=state.bridge_remaining, bridge_priority=state.bridge_priority,
        )

    @staticmethod
    def _escalation(state: CascadeState, outcome: _Outcome) -> EscalationSummary:
        assert outcome.escalation is not None
        return EscalationSummary(
            escalation_type=outcome.escalation, why_automation_stopped=outcome.reason,
            actions_attempted=list(state.applied_actions) or ["None; automatic recovery was not needed before this point"],
            donors_contacted=state.contacted_total, failures=dict(state.failure_totals),
            recommended_human_action=HUMAN_ACTION[outcome.escalation],
        )

    @staticmethod
    def apply(plan: RecoveryPlan, settings: WaveSettings) -> WaveSettings:
        """Apply a plan's safe changes to the next wave's settings. Escalations change nothing: the
        cascade stops and a person takes over. Nobody is contacted by this method."""
        if plan.requires_human_intervention:
            return settings
        changes = plan.changes
        changed = replace(settings)
        if changes.channel is not None and changes.channel is not settings.channel_override:
            changed = replace(changed, channel_override=changes.channel, channel_switches=settings.channel_switches + 1)
        if changes.wave_size is not None:
            changed = replace(changed, wave_size=min(changes.wave_size, MAX_WAVE_SIZE))
        if changes.radius_step is not None:
            changed = replace(changed, radius_step=min(changes.radius_step, MAX_RADIUS_STEP))
        if changes.bridge_priority is not None:
            changed = replace(changed, bridge_priority=changes.bridge_priority)
        return changed


def persisted_action(plan: RecoveryPlan) -> RecoveryActionType:
    """The RecoveryActionType (persisted vocabulary) that corresponds to a plan's primary action."""
    if plan.primary_action is RecoveryRecommendation.INCREASE_WAVE_SIZE and plan.changes.channel is not None:
        return RecoveryActionType.ALTERNATIVE_DONOR  # a wider wave reached by a different channel
    return PERSISTED_ACTION[plan.primary_action]


def failure_totals(counts: Sequence[tuple[str, int]]) -> dict[str, int]:
    return {name: count for name, count in counts if count}
