"""Adaptive Cascade Engine (simulation).

Answers "who should we contact first, and what happens next when outreach fails?" by simulating
wave-based outreach for a request:

    Matching ranking → wave 1 (top N) → simulated responses → autopsy → healing decision
      → re-matching (contacted donors excluded, healing applied) → wave 2 → … → FULFILLED or ESCALATED

Deterministic and in-memory: donor responses are drawn from each donor's computed state with a
seeded hash (no random(), no clock), nothing is persisted, nobody is contacted. Matching stays the
single source of the candidate ranking; the Donor State Engine (through Matching) stays the single
source of donor state.

The cascade only orchestrates: after a failed wave it asks the Failure Autopsy Engine what happened,
hands that and its own state to the Self-Healing Engine ("what should change?"), applies the returned
plan's safe changes and re-matches. The recovery policy lives in services/self_healing.py. The learning
preview is still a preliminary rule set.
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import DATA_NOTICE
from app.models import BloodRequest, CoordinationAttempt, Donor
from app.models.enums import InteractionChannel, LearningEventType, RecoveryActionType, UrgencyLevel
from app.schemas.cascade import (
    CascadeContact,
    CascadeOutcome,
    CascadeParameters,
    CascadeResult,
    CascadeWave,
    HealingDecision,
    HistoricalAttempt,
    LearningSignal,
    SimulatedResponse,
    WaveAutopsy,
)
from app.schemas.donor_state import CoordinationAvailability
from app.schemas.matching import MatchCandidate
from app.services.failure_autopsy import FailureAutopsyEngine, PatternContext, observation_from_contact
from app.schemas.failure_autopsy import FailurePatternType
from app.schemas.self_healing import BridgePriority, RecoveryPlan
from app.services.matching import MatchingEngine
from app.services.self_healing import (
    HIGH_FATIGUE_SCORE,
    MAX_RADIUS_STEP,
    MAX_WAVE_SIZE,
    CascadeState,
    FailureSignal,
    SelfHealingEngine,
    WaveSettings,
    persisted_action,
)

# ---- demo cascade settings ----------------------------------------------------------------

CASCADE_SEED = 20261008
DEFAULT_MAX_WAVES = 5
MAX_WAVES_LIMIT = 8
RANKING_DEPTH = 50                 # candidates requested from Matching per wave
SETUP_MINUTES = 15                 # from evaluation time to the first outreach
BETWEEN_WAVES_MINUTES = 10         # autopsy + healing before the next wave
SEND_SPACING_MINUTES = 2

WAVE_SIZE = {UrgencyLevel.LOW: 2, UrgencyLevel.MODERATE: 2, UrgencyLevel.HIGH: 3, UrgencyLevel.CRITICAL: 4}
RESPONSE_WINDOW_MINUTES = {
    UrgencyLevel.LOW: 360, UrgencyLevel.MODERATE: 240, UrgencyLevel.HIGH: 120, UrgencyLevel.CRITICAL: 60,
}
CHANNEL_FACTOR = {
    InteractionChannel.SIMULATED_CALL: 1.15,
    InteractionChannel.SIMULATED_SMS: 1.0,
    InteractionChannel.SIMULATED_APP: 0.9,
}
AVAILABILITY_FACTOR = {
    CoordinationAvailability.AVAILABLE: 1.0,
    CoordinationAvailability.RECENTLY_CONTACTED: 0.6,
    CoordinationAvailability.TEMPORARILY_UNAVAILABLE: 0.15,
    CoordinationAvailability.INACTIVE: 0.0,
}
LEARNING_SIGNALS = {
    SimulatedResponse.ACCEPTED: (LearningEventType.SUCCESSFUL_MATCH, 0.8),
    SimulatedResponse.DECLINED: (LearningEventType.DONOR_DECLINED, -0.2),
    SimulatedResponse.UNAVAILABLE: (LearningEventType.FAILED_MATCH, -0.1),
    SimulatedResponse.NO_RESPONSE: (LearningEventType.NO_RESPONSE, -0.35),
}
INITIAL_CHANNEL_POLICY = (
    "Known responsive donors (response rate ≥ 70 %) by simulated SMS; everyone else by simulated call "
    "for HIGH/CRITICAL urgency, or simulated SMS otherwise"
)
# What-if stress test: scales every reply probability. "none" keeps the calibration, which matches the
# synthetic history (about half of real coordination attempts succeed).
RESPONSE_STRESS = {"none": 1.0, "moderate": 0.75, "severe": 0.5}


# ---- pure rules ---------------------------------------------------------------------------------


def unit_draw(seed: int, *parts: str) -> float:
    """Deterministic number in [0, 1) from a seed and labels (SHA-256), replacing random()."""
    digest = hashlib.sha256("|".join([str(seed), *parts]).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _clamp(value: float, low: float = 0.05, high: float = 0.95) -> float:
    return max(low, min(high, value))


def response_probability(candidate: MatchCandidate, channel: InteractionChannel, stress: float = 1.0) -> float:
    """Chance of any reply: smoothed response score × channel factor (call 1.15, SMS 1.0, app 0.9)
    × stress factor, clamped to 5–95 %."""
    return _clamp(candidate.response_score / 100 * CHANNEL_FACTOR[channel] * stress)


def acceptance_probability(candidate: MatchCandidate) -> float:
    """Chance of accepting once replying: reliability × availability factor × (1 − fatigue ÷ 200), 5–95 %."""
    return _clamp(
        candidate.reliability_score / 100
        * AVAILABILITY_FACTOR[candidate.availability_status]
        * (1 - candidate.fatigue_score / 200)
    )


def initial_channel(candidate: MatchCandidate, urgent: bool) -> InteractionChannel:
    if candidate.response_rate is not None and candidate.response_rate >= 70:
        return InteractionChannel.SIMULATED_SMS
    return InteractionChannel.SIMULATED_CALL if urgent else InteractionChannel.SIMULATED_SMS


def wave_autopsy(contacts: Sequence[CascadeContact]) -> WaveAutopsy:
    counts = Counter(c.response for c in contacts)
    failures = {r: counts[r] for r in (SimulatedResponse.NO_RESPONSE, SimulatedResponse.DECLINED,
                                       SimulatedResponse.UNAVAILABLE) if counts[r]}
    # Ties resolve in the order above (no response first: the most actionable cause).
    dominant = max(failures, key=lambda r: failures[r]) if failures else None
    parts = [f"{counts[r]} {r.value.replace('_', ' ').lower()}" for r in SimulatedResponse if counts[r]]
    summary = f"{len(contacts)} contacted: " + ", ".join(parts) + "."
    if dominant:
        summary += f" Dominant cause: {dominant.value.replace('_', ' ').lower()}."
    return WaveAutopsy(
        accepted=counts[SimulatedResponse.ACCEPTED],
        declined=counts[SimulatedResponse.DECLINED],
        unavailable=counts[SimulatedResponse.UNAVAILABLE],
        no_response=counts[SimulatedResponse.NO_RESPONSE],
        dominant_cause=dominant,
        summary=summary,
    )


@dataclass(frozen=True)
class HealingContext:
    wave_number: int
    max_waves: int
    autopsy: WaveAutopsy
    remaining_candidates: int
    radius_step: int
    bridge_members_remaining: bool
    bridge_group_used: bool
    urgency: UrgencyLevel
    wave_size: int
    channel_override: InteractionChannel | None


def choose_healing(ctx: HealingContext) -> HealingDecision:
    """Compatibility adapter for the original placeholder interface. It performs no policy of its own:
    it restates a HealingContext as a Self-Healing state and signal and returns the engine's decision in
    the legacy HealingDecision shape. A WaveAutopsy carries no channel information, so no-response
    dominance counts as a channel response failure only on the first wave."""
    wave = ctx.autopsy
    failures = wave.declined + wave.unavailable + wave.no_response
    pattern = None
    if failures == 1:
        pattern = FailurePatternType.INDIVIDUAL_DONOR_FAILURE
    elif wave.dominant_cause is SimulatedResponse.NO_RESPONSE:
        pattern = (FailurePatternType.CHANNEL_RESPONSE_FAILURE if ctx.wave_number == 1
                   else FailurePatternType.RESPONSE_WINDOW_FAILURE)
    state = CascadeState(
        wave_number=ctx.wave_number, max_waves=ctx.max_waves, urgency=ctx.urgency, wave_size=ctx.wave_size,
        channel_override=ctx.channel_override, radius_step=ctx.radius_step,
        contacted_total=ctx.wave_number * ctx.wave_size, remaining_candidates=ctx.remaining_candidates,
        bridge_remaining=min(1, ctx.remaining_candidates) if ctx.bridge_members_remaining else 0,
        bridge_priority=BridgePriority.BRIDGE_FIRST if ctx.bridge_group_used else BridgePriority.DEFAULT,
        recovery_attempts=ctx.wave_number - 1, channel_switches=1 if ctx.channel_override else 0,
    )
    engine = SelfHealingEngine()
    plan = engine.plan_from_signal("", state, FailureSignal(pattern, None, None, failures, None))
    settings = WaveSettings(ctx.wave_size, ctx.channel_override, ctx.radius_step, state.bridge_priority)
    return decision_from_plan(plan, engine.apply(plan, settings))


def decision_from_plan(plan: RecoveryPlan, settings: WaveSettings) -> HealingDecision:
    """The plan in the cascade's persisted action vocabulary, with the settings it leaves for the next wave."""
    terminal = plan.requires_human_intervention
    return HealingDecision(
        action=persisted_action(plan), rationale=plan.reason,
        next_wave_size=None if terminal else settings.wave_size,
        channel_override=None if terminal else settings.channel_override,
        radius_step=settings.radius_step, bridge_group_first=settings.bridge_priority is BridgePriority.BRIDGE_FIRST,
    )


# ---- engine --------------------------------------------------------------------------------------


class AdaptiveCascadeEngine:
    def __init__(
        self, session: Session, matching: MatchingEngine, failure_autopsy: FailureAutopsyEngine,
        self_healing: SelfHealingEngine | None = None,
    ) -> None:
        self._session = session
        self._matching = matching
        self._failure_autopsy = failure_autopsy
        self._self_healing = self_healing or SelfHealingEngine()

    def _historical_attempts(self, request_code: str) -> list[HistoricalAttempt]:
        rows = self._session.execute(
            select(CoordinationAttempt.sequence_number, Donor.donor_code, CoordinationAttempt.status,
                   CoordinationAttempt.outcome)
            .join(Donor, Donor.id == CoordinationAttempt.donor_id)
            .join(BloodRequest, BloodRequest.id == CoordinationAttempt.blood_request_id)
            .where(BloodRequest.request_code == request_code)
            .order_by(CoordinationAttempt.sequence_number)
        ).all()
        return [
            HistoricalAttempt(sequence_number=seq, donor_code=code, status=status.value,
                              outcome=outcome.value if outcome else None)
            for seq, code, status, outcome in rows
        ]

    def simulate(
        self,
        request_code: str,
        *,
        evaluate_at: str = "auto",
        max_waves: int = DEFAULT_MAX_WAVES,
        wave_size: int | None = None,
        seed: int = CASCADE_SEED,
        response_stress: str = "none",
    ) -> CascadeResult:
        """Raises UnknownCode (from Matching) for an unknown request."""
        first = self._matching.match(request_code, RANKING_DEPTH, evaluate_at=evaluate_at)
        request = first.request
        urgency = request.urgency_level
        urgent = urgency in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL)
        window = RESPONSE_WINDOW_MINUTES[urgency]
        settings = WaveSettings(wave_size=min(wave_size or WAVE_SIZE[urgency], MAX_WAVE_SIZE))
        units_required = self._units_required(request_code)

        start = first.evaluation.assessed_at
        clock = start + timedelta(minutes=SETUP_MINUTES)
        contacted: list[str] = []
        secured: list[str] = []
        waves: list[CascadeWave] = []
        learning: list[LearningSignal] = []
        applied: RecoveryActionType | None = None
        plans: list[RecoveryPlan] = []
        escalation: HealingDecision | None = None
        escalation_plan: RecoveryPlan | None = None
        responses: Counter[str] = Counter()
        result = first

        for wave_number in range(1, max_waves + 1):
            if wave_number > 1:
                result = self._matching.match(
                    request_code, RANKING_DEPTH, evaluate_at=evaluate_at,
                    exclude_donor_codes=frozenset(contacted), radius_step=settings.radius_step,
                )
            pool = list(result.ranking)
            if settings.bridge_priority is BridgePriority.BRIDGE_FIRST:  # stable: ranking order kept within groups
                pool.sort(key=lambda c: not c.bridge_group_member)
            elif settings.bridge_priority is BridgePriority.NON_BRIDGE_FIRST:
                pool.sort(key=lambda c: c.bridge_group_member)
            picks = pool[:settings.wave_size]
            if not picks:
                # Nothing left to contact: the engine decides (widest radius, nothing remaining) and escalates.
                escalation_plan = self._self_healing.plan(request_code, CascadeState(
                    wave_number=min(max(wave_number - 1, 1), max_waves), max_waves=max_waves, urgency=urgency,
                    wave_size=settings.wave_size, channel_override=settings.channel_override,
                    radius_step=MAX_RADIUS_STEP, contacted_total=len(contacted), remaining_candidates=0,
                    bridge_priority=settings.bridge_priority, recovery_attempts=len(plans),
                    channel_switches=settings.channel_switches, units_outstanding=units_required - len(secured),
                    failure_totals=dict(responses), applied_actions=tuple(p.primary_action.value for p in plans),
                ), None)
                escalation = decision_from_plan(escalation_plan, settings)
                break

            contacts = self._run_wave(picks, clock, window, settings.channel_override, urgent, request_code, seed,
                                      units_required - len(secured), RESPONSE_STRESS[response_stress])
            secured += [c.donor_code for c in contacts if c.secured]
            contacted += [c.donor_code for c in contacts]
            responses.update(c.response.value for c in contacts if c.response is not SimulatedResponse.ACCEPTED)
            responded = [c.responded_at for c in contacts if c.responded_at]
            fulfilled = len(secured) >= units_required
            if fulfilled:
                closed = max(c.responded_at for c in contacts if c.secured)  # type: ignore[type-var]
            elif len(responded) == len(contacts):
                closed = max(responded)  # type: ignore[type-var]
            else:
                closed = contacts[-1].sent_at + timedelta(minutes=window)

            for c in contacts:
                event, signal = LEARNING_SIGNALS[c.response]
                learning.append(LearningSignal(
                    donor_code=c.donor_code, event_type=event,
                    signal=signal if c.secured or c.response is not SimulatedResponse.ACCEPTED else 0.4,
                    source=f"wave {wave_number}",
                ))
            if applied is not None:
                helped = any(c.secured for c in contacts)
                learning.append(LearningSignal(
                    donor_code=None,
                    event_type=LearningEventType.RECOVERY_SUCCESS if helped else LearningEventType.RECOVERY_FAILURE,
                    signal=0.6 if helped else -0.3,
                    source=f"{applied.value.replace('_', ' ').lower()} recovery before wave {wave_number}",
                ))

            autopsy = healing = failure_autopsy = plan = None
            if not fulfilled:
                autopsy = wave_autopsy(contacts)
                remaining = [c for c in pool if c.donor_code not in contacted]
                # Failure Autopsy: an evidence-based analysis of this wave's failed contacts, built from
                # data already computed above (no extra queries). It explains; it decides nothing.
                failure_autopsy = self._failure_autopsy.analyze_simulated(
                    request_code=request_code,
                    observations=[observation_from_contact(c) for c in contacts if c.response is not SimulatedResponse.ACCEPTED],
                    context=PatternContext(
                        remaining_in_radius=len(remaining),
                        filtered_outside_radius=result.discovery.filtered_outside_radius,
                        radius_known=result.discovery.radius_km is not None,
                        urgency=urgency,
                    ),
                )
                # Self-Healing decides what should change, from the autopsy and the cascade state.
                plan = self._self_healing.plan(request_code, CascadeState(
                    wave_number=wave_number, max_waves=max_waves, urgency=urgency, wave_size=settings.wave_size,
                    channel_override=settings.channel_override, radius_step=settings.radius_step,
                    contacted_total=len(contacted), remaining_candidates=len(remaining),
                    fatigued_remaining=sum(c.fatigue_score >= HIGH_FATIGUE_SCORE for c in remaining),
                    bridge_remaining=sum(c.bridge_group_member for c in remaining),
                    bridge_priority=settings.bridge_priority, recovery_attempts=len(plans),
                    channel_switches=settings.channel_switches, units_outstanding=units_required - len(secured),
                    wave_contacted=len(contacts),
                    no_response_channels=tuple(c.channel for c in contacts if c.response is SimulatedResponse.NO_RESPONSE),
                    failure_totals=dict(responses), applied_actions=tuple(p.primary_action.value for p in plans),
                ), failure_autopsy)
                next_settings = self._self_healing.apply(plan, settings)
                healing = decision_from_plan(plan, next_settings)
            waves.append(CascadeWave(
                wave_number=wave_number, started_at=clock, closed_at=closed, response_window_minutes=window,
                wave_size=len(picks), applied_action=applied, eligible_candidates=result.eligible_candidate_count,
                radius_km=result.discovery.radius_km, contacts=contacts,
                units_secured_after_wave=len(secured), autopsy=autopsy, healing=healing,
                failure_autopsy=failure_autopsy, recovery_plan=plan,
            ))
            clock = closed
            if fulfilled:
                break
            assert healing is not None and plan is not None
            plans.append(plan)
            if plan.requires_human_intervention:
                escalation, escalation_plan = healing, plan
                break
            applied = healing.action
            settings = next_settings
            clock = closed + timedelta(minutes=BETWEEN_WAVES_MINUTES)

        outcome = CascadeOutcome.FULFILLED if len(secured) >= units_required else CascadeOutcome.ESCALATED
        if outcome is CascadeOutcome.ESCALATED and escalation is None:  # defensive: loop ended without a decision
            escalation = waves[-1].healing if waves else None
            escalation_plan = escalation_plan or (waves[-1].recovery_plan if waves else None)
        completed = waves[-1].closed_at if waves else clock
        return CascadeResult(
            request=request,
            evaluation_point=first.evaluation.evaluation_point,
            simulation_start=start,
            parameters=CascadeParameters(
                wave_size=min(wave_size or WAVE_SIZE[urgency], MAX_WAVE_SIZE), max_waves=max_waves,
                response_window_minutes=window, seed=seed, initial_channel_policy=INITIAL_CHANNEL_POLICY,
                response_stress=response_stress,
            ),
            outcome=outcome,
            units_required=units_required,
            units_secured=len(secured),
            waves_used=len(waves),
            total_contacts=len(contacted),
            secured_donor_codes=secured,
            completed_at=completed,
            elapsed_minutes=round((completed - start).total_seconds() / 60),
            deadline_met=outcome is CascadeOutcome.FULFILLED and completed <= request.required_by,
            escalation=escalation if outcome is CascadeOutcome.ESCALATED else None,
            requires_human_intervention=outcome is CascadeOutcome.ESCALATED and escalation_plan is not None
            and escalation_plan.requires_human_intervention,
            escalation_type=escalation_plan.escalation_type if outcome is CascadeOutcome.ESCALATED and escalation_plan else None,
            escalation_summary=escalation_plan.escalation if outcome is CascadeOutcome.ESCALATED and escalation_plan else None,
            waves=waves,
            learning_preview=learning,
            historical_attempts=self._historical_attempts(request_code),
            data_notice=DATA_NOTICE,
        )

    def _units_required(self, request_code: str) -> int:
        return self._session.scalar(
            select(BloodRequest.units_required).where(BloodRequest.request_code == request_code)
        ) or 1

    @staticmethod
    def _run_wave(
        picks: Sequence[MatchCandidate],
        start: datetime,
        window: int,
        channel_override: InteractionChannel | None,
        urgent: bool,
        request_code: str,
        seed: int,
        units_needed: int,
        stress: float = 1.0,
    ) -> list[CascadeContact]:
        drafts = []
        for index, candidate in enumerate(picks):
            channel = channel_override or initial_channel(candidate, urgent)
            sent = start + timedelta(minutes=SEND_SPACING_MINUTES * index)
            p_reply = response_probability(candidate, channel, stress)
            p_accept = acceptance_probability(candidate)

            def draw(purpose: str) -> float:
                return unit_draw(seed, request_code, candidate.donor_code, purpose)

            if draw("reply") < p_reply:
                if draw("accept") < p_accept:
                    response = SimulatedResponse.ACCEPTED
                else:
                    response = SimulatedResponse.UNAVAILABLE if draw("decline") < 0.5 else SimulatedResponse.DECLINED
                responded_at = sent + timedelta(minutes=round(window * (0.1 + 0.8 * draw("time"))))
            else:
                response, responded_at = SimulatedResponse.NO_RESPONSE, None
            drafts.append((candidate, channel, sent, p_reply, p_accept, response, responded_at))

        # Acceptances secure units in the order they arrive; later ones are kept on standby.
        accepted = sorted(
            (d for d in drafts if d[5] is SimulatedResponse.ACCEPTED), key=lambda d: (d[6], d[0].donor_code)
        )
        secured_codes = {d[0].donor_code for d in accepted[:max(units_needed, 0)]}

        notes = {
            SimulatedResponse.NO_RESPONSE: "No reply within the response window",
            SimulatedResponse.DECLINED: "Replied: not able to donate this time",
            SimulatedResponse.UNAVAILABLE: "Replied: unavailable on the required dates",
        }
        contacts = []
        for candidate, channel, sent, p_reply, p_accept, response, responded_at in drafts:
            is_secured = candidate.donor_code in secured_codes
            if response is SimulatedResponse.ACCEPTED:
                note = "Accepted; unit secured" if is_secured else "Accepted after the requirement was met; on standby"
            else:
                note = notes[response]
            contacts.append(CascadeContact(
                donor_code=candidate.donor_code, display_name=candidate.display_name,
                blood_group=candidate.blood_group, match_rank=candidate.rank or 0, match_score=candidate.match_score,
                candidate_strategy=candidate.candidate_strategy, bridge_group_member=candidate.bridge_group_member,
                channel=channel, sent_at=sent, response_probability=round(100 * p_reply),
                acceptance_probability=round(100 * p_accept), response=response, responded_at=responded_at,
                secured=is_secured, note=note,
            ))
        return contacts
