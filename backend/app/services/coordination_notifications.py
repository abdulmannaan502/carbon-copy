"""Turns the events of a simulated cascade into DEMO notifications (Phase 10B).

The notification layer OBSERVES a finished simulation; it never influences it. `build_notifications` is a
pure function of a CascadeResult, so the same simulation always yields the same notifications. The
dispatcher hands each one to the demo provider, which records it as SIMULATED. Nothing is sent and nobody is
contacted: the cascade itself is a simulation, and every message says so.

It runs only when explicitly asked (POST), never as a side effect of viewing a report.

EVENTS
    wave outreach       DONOR_OUTREACH     → each contacted donor        (one per donor per wave)
    wave started        REQUEST_UPDATE     → patient, first wave only    (generic coordination status)
    wave failed         REQUEST_UPDATE     → coordinator
    recovery selected   RECOVERY_ACTION    → coordinator                 (automatic recoveries only)
    escalation          ESCALATION         → coordinator                 (human coordinator or blood bank)
    requirement secured REQUEST_FULFILLED  → coordinator and patient

Request-status changes are not emitted: the simulation does not change a request's stored status.

IDEMPOTENCY KEY  <request>:<simulation id>:<event>:w<wave>:<recipient>
The simulation id is a hash of every simulation parameter (evaluate_at, max_waves, wave_size, seed, response
stress), so distinct simulations never share a key and repeating one never duplicates.
"""

import hashlib
from dataclasses import dataclass

from pydantic import ValidationError

from app.models.enums import (
    InteractionChannel,
    NotificationChannel,
    NotificationEventType,
    NotificationRecipientRole,
)
from app.schemas.cascade import CascadeOutcome, CascadeResult, CascadeWave, SimulatedResponse
from app.schemas.notification import NotificationCreate, NotificationDispatchItem, NotificationDispatchReport
from app.schemas.self_healing import RecoveryPlan
from app.services.cascade import AdaptiveCascadeEngine
from app.services.notification_provider import DeliveryOutcome, NotificationProvider

COORDINATOR_REF = "Duty coordinator"
LABEL = "Synthetic demonstration, not for clinical use."
# A simulated call has no counterpart among notification channels; it is recorded in-app and the text says so.
CHANNEL_MAP = {
    InteractionChannel.SIMULATED_SMS: NotificationChannel.SMS,
    InteractionChannel.SIMULATED_APP: NotificationChannel.IN_APP,
    InteractionChannel.SIMULATED_CALL: NotificationChannel.IN_APP,
}
CHANNEL_WORDS = {
    InteractionChannel.SIMULATED_SMS: "SMS", InteractionChannel.SIMULATED_APP: "app message",
    InteractionChannel.SIMULATED_CALL: "call",
}
MAX_BODY = 500


@dataclass(frozen=True)
class SimulationParams:
    evaluate_at: str
    max_waves: int
    wave_size: int | None
    seed: int
    response_stress: str

    def simulation_id(self, request_code: str) -> str:
        raw = "|".join([request_code, self.evaluate_at, str(self.max_waves), str(self.wave_size or "auto"),
                        str(self.seed), self.response_stress])
        return "SIM-" + hashlib.sha256(raw.encode()).hexdigest()[:12].upper()

    def as_dict(self) -> dict[str, str | int]:
        return {"evaluate_at": self.evaluate_at, "max_waves": self.max_waves,
                "wave_size": self.wave_size if self.wave_size is not None else "auto", "seed": self.seed,
                "response_stress": self.response_stress}


@dataclass(frozen=True)
class PlannedNotification:
    wave_number: int | None
    event_type: NotificationEventType
    recipient_role: NotificationRecipientRole
    data: NotificationCreate | None
    error: str | None = None


def _clip(text: str, limit: int = MAX_BODY) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _change_summary(plan: RecoveryPlan) -> str:
    changes, parts = plan.changes, []
    if changes.channel:
        parts.append(f"contact donors by {CHANNEL_WORDS[changes.channel]}")
    if changes.wave_size is not None:
        parts.append(f"wave size {plan.current_state.wave_size} to {changes.wave_size}")
    if changes.radius_label:
        parts.append(f"search radius {plan.current_state.radius_label} to {changes.radius_label}")
    if changes.bridge_priority is not None:
        parts.append("bridge-group handling " + changes.bridge_priority.value.lower().replace("_", " "))
    return ", ".join(parts) or "re-run matching without the donors already contacted"


def _make(
    request_code: str, simulation: str, wave: int | None, event: NotificationEventType,
    role: NotificationRecipientRole, ref: str | None, title: str, body: str,
    channel: NotificationChannel = NotificationChannel.IN_APP,
) -> PlannedNotification:
    person = ref if role in (NotificationRecipientRole.DONOR, NotificationRecipientRole.PATIENT) else role.value
    key = f"{request_code}:{simulation}:{event.value}:w{wave if wave is not None else 0}:{person}"
    try:
        data = NotificationCreate(
            event_type=event, recipient_role=role, recipient_ref=ref, blood_request_code=request_code,
            channel=channel, title=title, body=_clip(f"{LABEL} {body}"), idempotency_key=key,
        )
        return PlannedNotification(wave, event, role, data)
    except ValidationError as error:  # a template that breaks the privacy rules is reported, not sent
        return PlannedNotification(wave, event, role, None, error=error.errors()[0]["msg"])


def _wave_notifications(result: CascadeResult, wave: CascadeWave, simulation: str) -> list[PlannedNotification]:
    code, n = result.request.request_code, wave.wave_number
    out: list[PlannedNotification] = []
    for contact in wave.contacts:
        out.append(_make(
            code, simulation, n, NotificationEventType.DONOR_OUTREACH, NotificationRecipientRole.DONOR,
            contact.donor_code, "[DEMO] Blood request outreach (simulation)",
            f"In this simulation, request {code} reached wave {n} and you were selected as a candidate, "
            f"with a simulated {CHANNEL_WORDS[contact.channel]}. No real message was sent to any phone and "
            "nothing is being asked of you.",
            CHANNEL_MAP[contact.channel],
        ))
    if n == 1:
        out.append(_make(
            code, simulation, n, NotificationEventType.REQUEST_UPDATE, NotificationRecipientRole.PATIENT,
            result.request.patient_code, "[DEMO] Request status update",
            f"Demo update for request {code}: coordination is in progress. This is a simulation and says "
            "nothing about availability or outcomes.",
        ))
    if wave.units_secured_after_wave >= result.units_required:
        return out
    counts = {r: sum(c.response is r for c in wave.contacts) for r in SimulatedResponse}
    pattern = wave.failure_autopsy.dominant_pattern.pattern_type.value if wave.failure_autopsy and wave.failure_autopsy.dominant_pattern else "none"
    out.append(_make(
        code, simulation, n, NotificationEventType.REQUEST_UPDATE, NotificationRecipientRole.COORDINATOR, COORDINATOR_REF,
        f"[DEMO] Wave {n} did not secure request {code}",
        f"Simulated wave {n} contacted {len(wave.contacts)} donor(s): {counts[SimulatedResponse.NO_RESPONSE]} no response, "
        f"{counts[SimulatedResponse.DECLINED]} declined, {counts[SimulatedResponse.UNAVAILABLE]} unavailable; "
        f"{wave.units_secured_after_wave} of {result.units_required} unit(s) secured. Failure pattern: {pattern}. "
        "Next action: review the recovery decision for this wave.",
    ))
    plan = wave.recovery_plan
    if plan and not plan.requires_human_intervention:
        out.append(_make(
            code, simulation, n, NotificationEventType.RECOVERY_ACTION, NotificationRecipientRole.COORDINATOR, COORDINATOR_REF,
            f"[DEMO] Recovery selected for request {code}",
            f"After wave {n}, self-healing selected {plan.primary_action.value.replace('_', ' ').lower()}: {plan.reason} "
            f"Next action: the next simulated wave will {_change_summary(plan)}.",
        ))
    return out


def build_notifications(result: CascadeResult, params: SimulationParams) -> list[PlannedNotification]:
    """Pure: the demo notifications that describe this simulation, in event order."""
    code = result.request.request_code
    simulation = params.simulation_id(code)
    planned: list[PlannedNotification] = []
    for wave in result.waves:
        planned += _wave_notifications(result, wave, simulation)
    if result.outcome is CascadeOutcome.FULFILLED:
        wave_no = result.waves_used
        planned.append(_make(
            code, simulation, wave_no, NotificationEventType.REQUEST_FULFILLED, NotificationRecipientRole.COORDINATOR,
            COORDINATOR_REF, f"[DEMO] Simulation secured request {code}",
            f"The simulation secured {result.units_secured} of {result.units_required} unit(s) in {result.waves_used} "
            f"wave(s) with {result.total_contacts} donor(s) contacted. Next action: none in the simulation; a real "
            "request would still need human confirmation.",
        ))
        planned.append(_make(
            code, simulation, wave_no, NotificationEventType.REQUEST_FULFILLED, NotificationRecipientRole.PATIENT,
            result.request.patient_code, "[DEMO] Request status update",
            f"Demo update for request {code}: the simulation reached a secured outcome. This is not a confirmation "
            "of real availability or of any clinical outcome.",
        ))
    elif result.requires_human_intervention and result.escalation_summary is not None:
        summary = result.escalation_summary
        who = "the institutional blood bank" if summary.escalation_type.value == "BLOOD_BANK" else "a human coordinator"
        planned.append(_make(
            code, simulation, result.waves_used, NotificationEventType.ESCALATION, NotificationRecipientRole.COORDINATOR,
            COORDINATOR_REF, f"[DEMO] Human attention needed for request {code}",
            f"Automation stopped after {result.waves_used} simulated wave(s) with {summary.donors_contacted} donor(s) "
            f"contacted: {summary.why_automation_stopped} Escalation to {who}. Next action: {summary.recommended_human_action}",
        ))
    return planned


class NotificationBatchRejected(Exception):
    """A simulation's notifications were not stored because at least one was rejected. All-or-nothing:
    nothing from that simulation was kept, so there is never a partial event set."""

    def __init__(self, items: list[NotificationDispatchItem]) -> None:
        self.items = items
        rejected = [i for i in items if i.outcome == DeliveryOutcome.REJECTED.value]
        first = rejected[0].error if rejected else "unknown reason"
        super().__init__(
            f"No notifications were stored for this simulation: {len(rejected)} of {len(items)} were rejected (first: {first})."
        )


class CoordinationNotifier:
    """Runs a simulation and records its events through the provider. Only called on an explicit request.

    The whole event set is stored in ONE transaction: it is committed only if every notification was recorded or
    already existed. Any rejection or database error rolls the set back, so a failure never leaves a partial set."""

    def __init__(self, cascade: AdaptiveCascadeEngine, provider: NotificationProvider) -> None:
        self._cascade = cascade
        self._provider = provider

    def notify_simulation(self, request_code: str, params: SimulationParams) -> NotificationDispatchReport:
        """Raises UnknownCode for an unknown request. The simulation is run exactly as GET /cascade runs it."""
        result = self._cascade.simulate(
            request_code, evaluate_at=params.evaluate_at, max_waves=params.max_waves, wave_size=params.wave_size,
            seed=params.seed, response_stress=params.response_stress,
        )
        items: list[NotificationDispatchItem] = []
        try:
            for planned in build_notifications(result, params):
                if planned.data is None:
                    items.append(NotificationDispatchItem(
                        event_type=planned.event_type, recipient_role=planned.recipient_role,
                        wave_number=planned.wave_number, outcome=DeliveryOutcome.REJECTED.value, error=planned.error))
                    continue
                delivered = self._provider.deliver(planned.data, commit=False)
                items.append(NotificationDispatchItem(
                    event_type=planned.event_type, recipient_role=planned.recipient_role, wave_number=planned.wave_number,
                    outcome=delivered.outcome.value,
                    notification_id=delivered.notification.notification_id if delivered.notification else None,
                    error=delivered.error,
                ))
            if any(i.outcome == DeliveryOutcome.REJECTED.value for i in items):
                self._provider.rollback()
                raise NotificationBatchRejected(items)
            self._provider.commit()
        except NotificationBatchRejected:
            raise
        except Exception:
            self._provider.rollback()
            raise
        count = lambda outcome: sum(i.outcome == outcome.value for i in items)  # noqa: E731
        return NotificationDispatchReport(
            request_code=request_code, simulation_id=params.simulation_id(request_code), parameters=params.as_dict(),
            cascade_outcome=result.outcome.value, created=count(DeliveryOutcome.RECORDED),
            duplicates=count(DeliveryOutcome.DUPLICATE), rejected=count(DeliveryOutcome.REJECTED), items=items,
        )
