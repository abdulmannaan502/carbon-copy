"""Living Digital Twin Engine.

Computes a recurring patient's current *coordination* state from existing
records: profile, cadence, request history, coordination outcomes, donor
network and recent activity. Nothing is persisted; the twin is recalculated on
every call, so it always reflects the latest data.

Everything here is deterministic and rule-based. The thresholds below are demo
operational settings, not medical thresholds, and the twin never assesses the
patient's health.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.core.blood import COMPATIBLE_DONORS
from app.core.config import DATA_NOTICE
from app.models import BloodRequest, CoordinationAttempt, Patient, RecoveryAction
from app.models.enums import (
    CoordinationOutcome,
    CoordinationStatus,
    InteractionChannel,
    RecoveryActionType,
    RecoveryStatus,
    RequestStatus,
)
from app.repositories.digital_twin_repository import CheckStats, DigitalTwinRepository
from app.schemas.donor_state import CoordinationAvailability, FatigueBand, ScoreBand
from app.schemas.digital_twin import (
    CoordinationHistory,
    DigitalTwinRequestContext,
    DigitalTwinState,
    NetworkState,
    NetworkStrengthBand,
    NetworkStrengthComponents,
    OperationalState,
    PatientIdentity,
    RecentActivity,
    RecurrenceStatus,
    RequestCoordinationContext,
    RequestOutcomeSummary,
    RequirementState,
    TimelineEvent,
    TimelineEventKind,
    TimelineTone,
    TransfusionProfile,
)
from app.services.digital_twin_summary import deterministic_summary
from app.services.donor_state import DonorStateEngine

# ---- demo operational settings ------------------------------------------------

RECENT_WINDOW_DAYS = 30
# Donor-level thresholds (high reliability, high fatigue) come from the Donor State Engine's bands.
# Available donors at which the depth component is full: roughly two broadcast waves of
# compatible donors. Demo calibration against the synthetic dataset, like the band cut-offs.
TARGET_AVAILABLE_DONORS = 50
STRENGTH_WEIGHTS = {"depth": 0.40, "reliability": 0.25, "responsiveness": 0.15, "freshness": 0.20}
STRONG_NETWORK_MIN = 75
MODERATE_NETWORK_MIN = 55
FATIGUE_SHARE_WATCH = 0.25

ACTIVE_STATUSES = frozenset(
    {RequestStatus.OPEN, RequestStatus.MATCHING, RequestStatus.COORDINATING, RequestStatus.RECOVERING}
)
OPEN_RECOVERY_STATUSES = frozenset({RecoveryStatus.PENDING, RecoveryStatus.IN_PROGRESS})

FAILED_ATTEMPT_TITLES = {
    CoordinationOutcome.NO_RESPONSE: "No response from {donor}",
    CoordinationOutcome.DONOR_UNAVAILABLE: "{donor} unavailable",
    CoordinationOutcome.DONOR_DECLINED: "{donor} declined",
    CoordinationOutcome.OTHER: "Attempt with {donor} unsuccessful",
}
RECOVERY_LABELS = {
    RecoveryActionType.NEXT_DONOR: "Next donor",
    RecoveryActionType.ALTERNATIVE_DONOR: "Alternative donor",
    RecoveryActionType.BRIDGE_GROUP_ESCALATION: "Bridge group escalation",
    RecoveryActionType.EXPANDED_SEARCH: "Expanded search",
    RecoveryActionType.BLOOD_BANK_REFERRAL: "Blood bank referral",
    RecoveryActionType.HUMAN_COORDINATOR_REVIEW: "Coordinator review",
}
CHANNEL_LABELS = {
    InteractionChannel.SIMULATED_SMS: "simulated SMS",
    InteractionChannel.SIMULATED_CALL: "simulated call",
    InteractionChannel.SIMULATED_APP: "simulated app notification",
}


# ---- pure calculation rules -------------------------------------------------------


def recurrence_windows(frequency_days: int) -> tuple[int, int]:
    """(due_window, approaching_window) in days, as fractions of the patient's own cadence:
    DUE within 10 % of the cycle (min 1 day), APPROACHING within a third of it (min 3 days).
    These are coordination lead-time windows, not medical thresholds."""
    return max(1, round(frequency_days * 0.10)), max(3, round(frequency_days / 3))


def calculate_recurrence(
    next_expected: date | None, frequency_days: int | None, today: date
) -> tuple[int | None, RecurrenceStatus]:
    if next_expected is None or not frequency_days:
        return None, RecurrenceStatus.UNKNOWN
    days_until = (next_expected - today).days
    due_window, approaching_window = recurrence_windows(frequency_days)
    if days_until < 0:
        return days_until, RecurrenceStatus.OVERDUE
    if days_until <= due_window:
        return days_until, RecurrenceStatus.DUE
    if days_until <= approaching_window:
        return days_until, RecurrenceStatus.APPROACHING
    return days_until, RecurrenceStatus.STABLE


def calculate_network_strength(
    *,
    available: int,
    active: int,
    fatigued: int,
    mean_reliability: float | None,
    mean_response_rate: float | None,
) -> tuple[int, NetworkStrengthBand, NetworkStrengthComponents]:
    """Demo operational metric (0–100), not a clinical score.

    score = 100 × (0.40·depth + 0.25·reliability + 0.15·responsiveness + 0.20·freshness)
      depth          = min(available / 50, 1)
      reliability    = mean reliability score of available donors
      responsiveness = mean response rate of available donors
      freshness      = 1 − fatigued / active
    """
    parts = {
        "depth": min(available / TARGET_AVAILABLE_DONORS, 1.0),
        "reliability": mean_reliability or 0.0,
        "responsiveness": mean_response_rate or 0.0,
        "freshness": 1 - fatigued / active if active else 0.0,
    }
    raw = sum(STRENGTH_WEIGHTS[name] * value for name, value in parts.items())
    score = max(0, min(100, round(100 * raw)))
    if score >= STRONG_NETWORK_MIN:
        band = NetworkStrengthBand.STRONG
    elif score >= MODERATE_NETWORK_MIN:
        band = NetworkStrengthBand.MODERATE
    else:
        band = NetworkStrengthBand.WEAK
    components = NetworkStrengthComponents(**{name: round(100 * value) for name, value in parts.items()})
    return score, band, components


@dataclass(frozen=True)
class StateSignals:
    patient_active: bool
    active_request_code: str | None
    active_request_status: RequestStatus | None
    recurrence: RecurrenceStatus
    days_until: int | None
    requirement_covered: bool
    covering_request_code: str | None
    network_band: NetworkStrengthBand
    network_score: int
    recent_failures: int
    fatigue_share: float


def determine_operational_state(s: StateSignals) -> tuple[OperationalState, list[str]]:
    """First matching rule wins: ACTIVE_COORDINATION → ATTENTION → WATCH → HEALTHY."""
    info = []
    if s.requirement_covered and s.covering_request_code:
        info.append(f"Upcoming requirement already has a confirmed donor ({s.covering_request_code}).")

    if s.active_request_code and s.active_request_status:
        return OperationalState.ACTIVE_COORDINATION, [
            f"Request {s.active_request_code} is being coordinated ({s.active_request_status.value})."
        ]

    attention = []
    if not s.requirement_covered:
        if s.recurrence is RecurrenceStatus.OVERDUE:
            attention.append("Expected requirement date has passed with no donor confirmed.")
        elif s.recurrence is RecurrenceStatus.DUE:
            attention.append("Requirement is due with no donor confirmed yet.")
        elif s.recurrence is RecurrenceStatus.APPROACHING:
            attention.append(f"Next requirement in {s.days_until} days with no donor confirmed yet.")
    if s.network_band is NetworkStrengthBand.WEAK:
        attention.append(f"Donor network strength is weak ({s.network_score}/100).")
    if attention:
        return OperationalState.ATTENTION, attention + info

    watch = []
    if s.recent_failures:
        watch.append(f"{s.recent_failures} failed coordination attempt(s) in the last {RECENT_WINDOW_DAYS} days.")
    if s.network_band is NetworkStrengthBand.MODERATE:
        watch.append(f"Donor network strength is moderate ({s.network_score}/100).")
    if s.fatigue_share >= FATIGUE_SHARE_WATCH:
        watch.append(f"{round(s.fatigue_share * 100)}% of active network donors show elevated fatigue.")
    if s.recurrence is RecurrenceStatus.UNKNOWN:
        watch.append("Transfusion cadence is unknown.")
    if not s.patient_active:
        watch.append("Patient record is inactive.")
    if watch:
        return OperationalState.WATCH, watch + info

    return OperationalState.HEALTHY, ["No immediate coordination concern detected."] + info


def _percent(numerator: int, denominator: int) -> int | None:
    return round(100 * numerator / denominator) if denominator else None


def _latest_recovery(request: BloodRequest) -> RecoveryAction | None:
    recoveries = [r for a in request.coordination_attempts if a.failure for r in a.failure.recovery_actions]
    return max(recoveries, key=lambda r: (r.initiated_at, r.id), default=None)


def _attempt_channel(attempt: CoordinationAttempt) -> InteractionChannel | None:
    first = min(attempt.interactions, key=lambda i: (i.initiated_at, i.id), default=None)
    return first.channel if first else None


def build_timeline(request: BloodRequest, checks: CheckStats) -> list[TimelineEvent]:
    """Chronological story of one request, from creation to its current outcome."""
    events: list[tuple[datetime, int, TimelineEvent]] = []

    def add(at: datetime, kind: TimelineEventKind, title: str, detail: str | None, tone: TimelineTone) -> None:
        events.append((at, len(events), TimelineEvent(at=at, kind=kind, title=title, detail=detail, tone=tone)))

    add(
        request.requested_at, TimelineEventKind.REQUEST_CREATED, "Request created",
        f"{request.units_required} unit(s) {request.blood_group.value} · {request.urgency_level.value} urgency · "
        f"required by {request.required_by:%d %b %Y}",
        TimelineTone.NEUTRAL,
    )
    if checks.total and checks.first_sent_at:
        detail = f"{checks.total} compatible donors pinged · {checks.responded} replied available"
        if checks.pending:
            detail += f" · {checks.pending} awaiting reply"
        add(checks.first_sent_at, TimelineEventKind.AVAILABILITY_CHECKS, "Availability checks sent", detail,
            TimelineTone.NEUTRAL)

    last_success: datetime | None = None
    for attempt in request.coordination_attempts:
        donor = attempt.donor.donor_code
        channel = _attempt_channel(attempt)
        via = f" via {CHANNEL_LABELS[channel]}" if channel else ""
        add(attempt.started_at, TimelineEventKind.DONOR_CONTACTED, f"Donor {donor} contacted",
            f"Cascade position {attempt.sequence_number}{via} · priority {attempt.priority_score:.2f}",
            TimelineTone.NEUTRAL)

        if attempt.status is CoordinationStatus.SUCCESS and attempt.completed_at:
            last_success = attempt.completed_at
            add(attempt.completed_at, TimelineEventKind.DONOR_ACCEPTED, f"Donor {donor} accepted",
                "Donation confirmed (simulated)", TimelineTone.POSITIVE)
        elif attempt.status is CoordinationStatus.FAILED and attempt.completed_at:
            title = FAILED_ATTEMPT_TITLES.get(attempt.outcome, "Attempt with {donor} failed") if attempt.outcome else "Attempt with {donor} failed"
            add(attempt.completed_at, TimelineEventKind.ATTEMPT_FAILED, title.format(donor=donor),
                attempt.failure_reason, TimelineTone.NEGATIVE)
            if attempt.failure:
                failure = attempt.failure
                add(failure.detected_at, TimelineEventKind.FAILURE_DETECTED,
                    f"Failure recorded: {failure.failure_category.value.replace('_', ' ').lower()}",
                    f"Severity {failure.severity.value.lower()} · {failure.recommended_action}",
                    TimelineTone.NEGATIVE)
                for recovery in failure.recovery_actions:
                    target = f" → {recovery.target_donor.donor_code}" if recovery.target_donor else ""
                    open_ = recovery.status in OPEN_RECOVERY_STATUSES
                    add(recovery.initiated_at, TimelineEventKind.RECOVERY_INITIATED,
                        f"Recovery: {RECOVERY_LABELS[recovery.action_type]}{target}",
                        recovery.description + (f" ({recovery.status.value.replace('_', ' ').lower()})" if open_ else ""),
                        TimelineTone.PENDING if open_ else TimelineTone.NEUTRAL)
        elif attempt.status in (CoordinationStatus.WAITING, CoordinationStatus.OUTREACH_SENT):
            add(attempt.started_at, TimelineEventKind.AWAITING_RESPONSE, f"Awaiting response from {donor}",
                "Outreach sent; response window open", TimelineTone.PENDING)

    if request.status is RequestStatus.FULFILLED and last_success:
        add(last_success, TimelineEventKind.REQUEST_FULFILLED, "Requirement secured",
            f"{request.units_required} unit(s) confirmed for {request.required_by:%d %b %Y}", TimelineTone.POSITIVE)
    elif request.status is RequestStatus.CANCELLED:
        add(request.requested_at, TimelineEventKind.REQUEST_CANCELLED, "Request cancelled", None, TimelineTone.NEUTRAL)

    return [event for _, _, event in sorted(events, key=lambda e: (e[0], e[1]))]


# ---- service --------------------------------------------------------------------

Summarizer = Callable[[DigitalTwinState], str]


class DigitalTwinService:
    """Builds DigitalTwinState objects. `summarize` is the seam for AI-assisted
    summaries later; today it is the deterministic template."""

    summary_source = "deterministic"

    def __init__(
        self,
        repository: DigitalTwinRepository,
        donor_states: DonorStateEngine,
        now: datetime,
        summarize: Summarizer = deterministic_summary,
    ) -> None:
        self._repo = repository
        self._donor_states = donor_states
        self._now = now
        self._summarize = summarize

    def build(self, patient_code: str) -> DigitalTwinState | None:
        patient = self._repo.get_patient(patient_code)
        return self._build(patient)[0] if patient else None

    def request_context(self, request_code: str) -> DigitalTwinRequestContext | None:
        request = self._repo.get_request(request_code)
        if request is None:
            return None
        twin, requests = self._build(request.patient)
        loaded = next(r for r in requests if r.id == request.id)
        attempts = loaded.coordination_attempts
        latest = attempts[-1] if attempts else None
        recovery = _latest_recovery(loaded)
        return DigitalTwinRequestContext(
            request=RequestCoordinationContext(
                request_code=loaded.request_code,
                status=loaded.status,
                blood_group=loaded.blood_group,
                compatible_donor_groups=list(COMPATIBLE_DONORS[loaded.blood_group]),
                units_required=loaded.units_required,
                urgency_level=loaded.urgency_level,
                requested_at=loaded.requested_at,
                required_by=loaded.required_by,
                is_active=loaded.status in ACTIVE_STATUSES,
                is_current_request=twin.requirement_state.current_request_code == loaded.request_code,
                attempts=len(attempts),
                failed_attempts=sum(a.status is CoordinationStatus.FAILED for a in attempts),
                latest_attempt_status=latest.status if latest else None,
                latest_attempt_outcome=latest.outcome if latest else None,
                latest_recovery_action=recovery.action_type if recovery else None,
                latest_recovery_status=recovery.status if recovery else None,
                timeline=build_timeline(loaded, self._repo.check_stats(loaded.id)),
            ),
            digital_twin=twin,
        )

    # -- assembly ---------------------------------------------------------------------

    def _build(self, patient: Patient) -> tuple[DigitalTwinState, Sequence[BloodRequest]]:
        now = self._now
        window_start = now - timedelta(days=RECENT_WINDOW_DAYS)
        requests = [r for r in self._repo.patient_requests(patient.id) if r.requested_at <= now]

        active = max((r for r in requests if r.status in ACTIVE_STATUSES), key=lambda r: r.requested_at, default=None)
        covering = max(
            (r for r in requests if r.status is RequestStatus.FULFILLED and r.required_by >= now),
            key=lambda r: r.requested_at, default=None,
        )
        current = active or covering
        focus = current or (requests[-1] if requests else None)

        days_until, recurrence = calculate_recurrence(
            patient.next_expected_requirement, patient.transfusion_frequency_days, now.date()
        )
        network = self._network(patient)
        history = self._history(requests)
        activity = self._activity(patient.id, requests, focus, window_start)

        fatigue_share = network.fatigued_donor_count / network.active_donor_count if network.active_donor_count else 0.0
        state, reasons = determine_operational_state(StateSignals(
            patient_active=patient.active,
            active_request_code=active.request_code if active else None,
            active_request_status=active.status if active else None,
            recurrence=recurrence,
            days_until=days_until,
            requirement_covered=covering is not None and active is None,
            covering_request_code=covering.request_code if covering else None,
            network_band=network.network_strength_band,
            network_score=network.network_strength_score,
            recent_failures=activity.recent_failure_count,
            fatigue_share=fatigue_share,
        ))

        twin = DigitalTwinState(
            as_of=now,
            patient=PatientIdentity(
                patient_code=patient.patient_code,
                display_name=patient.display_name,
                blood_group=patient.blood_group,
                city=patient.city, district=patient.district, state=patient.state,
                urgency_level=patient.urgency_level,
                bridge_group_code=patient.bridge_group.group_code if patient.bridge_group else None,
                bridge_group_name=patient.bridge_group.name if patient.bridge_group else None,
                active=patient.active,
            ),
            transfusion_profile=TransfusionProfile(
                transfusion_frequency_days=patient.transfusion_frequency_days,
                last_transfusion_date=patient.last_transfusion_date,
                next_expected_requirement=patient.next_expected_requirement,
                days_until_expected_requirement=days_until,
                recurrence_status=recurrence,
            ),
            requirement_state=self._requirement(active, current),
            coordination_history=history,
            network_state=network,
            recent_activity=activity,
            operational_state=state,
            operational_state_reasons=reasons,
            summary="",
            summary_source=self.summary_source,
            data_notice=DATA_NOTICE,
        )
        return twin.model_copy(update={"summary": self._summarize(twin)}), requests

    @staticmethod
    def _requirement(active: BloodRequest | None, current: BloodRequest | None) -> RequirementState:
        attempts = current.coordination_attempts if current else []
        recovery = _latest_recovery(current) if current else None
        return RequirementState(
            active_request=active is not None,
            active_request_code=active.request_code if active else None,
            current_request_code=current.request_code if current else None,
            requirement_covered=current is not None and active is None,
            units_required=current.units_required if current else None,
            request_status=current.status if current else None,
            request_urgency=current.urgency_level if current else None,
            requested_at=current.requested_at if current else None,
            required_by=current.required_by if current else None,
            attempts_made=len(attempts),
            failed_attempts=sum(a.status is CoordinationStatus.FAILED for a in attempts),
            latest_attempt_status=attempts[-1].status if attempts else None,
            pending_recovery_action=(
                recovery.action_type if recovery and recovery.status in OPEN_RECOVERY_STATUSES else None
            ),
        )

    @staticmethod
    def _history(requests: Sequence[BloodRequest]) -> CoordinationHistory:
        def count(status: RequestStatus) -> int:
            return sum(r.status is status for r in requests)

        attempts = [a for r in requests for a in r.coordination_attempts]
        failed = [a for a in attempts if a.status is CoordinationStatus.FAILED]
        recoveries = [rec for a in failed if a.failure for rec in a.failure.recovery_actions]
        successful_donors = {(a.blood_request_id, a.donor_id) for a in attempts if a.status is CoordinationStatus.SUCCESS}
        fulfilled = [r for r in requests if r.status is RequestStatus.FULFILLED]
        with_attempts = [r for r in requests if r.coordination_attempts]

        return CoordinationHistory(
            total_requests=len(requests),
            fulfilled_requests=len(fulfilled),
            requests_with_failures=sum(
                any(a.status is CoordinationStatus.FAILED for a in r.coordination_attempts) for r in requests
            ),
            recovering_requests=count(RequestStatus.RECOVERING),
            cancelled_requests=count(RequestStatus.CANCELLED),
            active_requests=sum(r.status in ACTIVE_STATUSES for r in requests),
            historical_success_rate=_percent(len(fulfilled), len(fulfilled) + count(RequestStatus.CANCELLED)),
            first_attempt_success_rate=_percent(
                sum(bool(r.coordination_attempts) and r.coordination_attempts[0].status is CoordinationStatus.SUCCESS
                    for r in fulfilled),
                len(fulfilled),
            ),
            average_coordination_attempts=round(len(attempts) / len(with_attempts), 1) if with_attempts else None,
            total_coordination_attempts=len(attempts),
            total_failures=len(failed),
            total_recovery_actions=len(recoveries),
            successful_recoveries=sum(
                rec.target_donor_id is not None and (rec.blood_request_id, rec.target_donor_id) in successful_donors
                for rec in recoveries
            ),
            requests=[
                RequestOutcomeSummary(
                    request_code=r.request_code,
                    requested_at=r.requested_at,
                    status=r.status,
                    attempts=len(r.coordination_attempts),
                    failed_attempts=sum(a.status is CoordinationStatus.FAILED for a in r.coordination_attempts),
                    successful_attempts=sum(a.status is CoordinationStatus.SUCCESS for a in r.coordination_attempts),
                )
                for r in requests
            ],
        )

    def _network(self, patient: Patient) -> NetworkState:
        """Network counts come from the Donor State Engine, so a donor's state is the same
        on the twin as on the donor page."""
        donor_ids = self._repo.network_donor_ids(
            patient.id, patient.bridge_group_id, COMPATIBLE_DONORS[patient.blood_group]
        )
        states = list(self._donor_states.assess_ids(donor_ids).values())
        active = [s for s in states if s.donor.active]
        # Network capacity: eligible donors who can be approached now or once a recent contact cools down.
        reachable = (CoordinationAvailability.AVAILABLE, CoordinationAvailability.RECENTLY_CONTACTED)
        available = [s for s in active if s.eligibility.eligible and s.availability.availability_status in reachable]
        fatigued = sum(s.fatigue.fatigue_band is FatigueBand.HIGH for s in active)
        group_code = patient.bridge_group.group_code if patient.bridge_group else None
        score, band, components = calculate_network_strength(
            available=len(available),
            active=len(active),
            fatigued=fatigued,
            mean_reliability=(
                sum(s.reliability.reliability_score for s in available) / len(available) / 100 if available else None
            ),
            mean_response_rate=(
                sum(s.response.response_score for s in available) / len(available) / 100 if available else None
            ),
        )
        return NetworkState(
            known_donor_count=len(states),
            active_donor_count=len(active),
            available_donor_count=len(available),
            high_reliability_donor_count=sum(s.reliability.reliability_band is ScoreBand.HIGH for s in active),
            recently_contacted_donor_count=sum(s.fatigue.contacts_last_30_days > 0 for s in states),
            fatigued_donor_count=fatigued,
            bridge_group_donor_count=sum(
                group_code is not None and s.donor.bridge_group_code == group_code for s in states
            ),
            network_strength_score=score,
            network_strength_band=band,
            strength_components=components,
            strength_weights=NetworkStrengthComponents(
                **{name: round(100 * weight) for name, weight in STRENGTH_WEIGHTS.items()}
            ),
        )

    def _activity(
        self, patient_id: int, requests: Sequence[BloodRequest], focus: BloodRequest | None, window_start: datetime
    ) -> RecentActivity:
        now = self._now
        attempts = [a for r in requests for a in r.coordination_attempts if a.completed_at and a.completed_at <= now]
        successes = [a.completed_at for a in attempts if a.status is CoordinationStatus.SUCCESS and a.completed_at]
        failures = [a.completed_at for a in attempts if a.status is CoordinationStatus.FAILED and a.completed_at]
        return RecentActivity(
            window_days=RECENT_WINDOW_DAYS,
            last_request_date=requests[-1].requested_at if requests else None,
            last_successful_coordination=max(successes, default=None),
            last_failed_coordination=max(failures, default=None),
            recent_interaction_count=self._repo.interaction_count(patient_id, window_start, now),
            recent_failure_count=sum(t > window_start for t in failures),
            recent_success_count=sum(t > window_start for t in successes),
            focus_request_code=focus.request_code if focus else None,
            timeline=build_timeline(focus, self._repo.check_stats(focus.id)) if focus else [],
        )
