"""Natural-language summary of a Digital Twin.

Today the summary is a deterministic template over the twin's computed fields.
This is the integration point for AI assistance: a later summarizer can send the
twin (as structured context) to an AIProvider with AITask.SUMMARIZE and fall back
to this function when AI is disabled or fails. The AI would only *describe*
these figures; it never computes them.
"""

from app.schemas.digital_twin import DigitalTwinState, OperationalState, RecurrenceStatus

STATE_LABELS = {
    OperationalState.HEALTHY: "healthy",
    OperationalState.WATCH: "watch",
    OperationalState.ATTENTION: "attention",
    OperationalState.ACTIVE_COORDINATION: "active coordination",
}


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def deterministic_summary(twin: DigitalTwinState) -> str:
    patient = twin.patient
    profile = twin.transfusion_profile
    requirement = twin.requirement_state
    network = twin.network_state
    history = twin.coordination_history
    activity = twin.recent_activity
    sentences: list[str] = []

    if profile.transfusion_frequency_days:
        sentences.append(
            f"Patient {patient.patient_code} has a recurring {patient.blood_group.value} requirement "
            f"every {profile.transfusion_frequency_days} days."
        )
    else:
        sentences.append(f"Patient {patient.patient_code} has a {patient.blood_group.value} requirement with no recorded cadence.")

    expected, days = profile.next_expected_requirement, profile.days_until_expected_requirement
    if expected is not None and days is not None:
        when = f"{expected:%d %b}"
        sentences.append({
            RecurrenceStatus.STABLE: f"The next expected requirement is on {when}, {_plural(days, 'day')} away.",
            RecurrenceStatus.APPROACHING: f"The next expected requirement is approaching: {when}, in {_plural(days, 'day')}.",
            RecurrenceStatus.DUE: f"The next requirement is due on {when}.",
            RecurrenceStatus.OVERDUE: f"The requirement expected on {when} is {_plural(-days, 'day')} past its expected date.",
            RecurrenceStatus.UNKNOWN: "",
        }[profile.recurrence_status])

    if requirement.active_request:
        sentences.append(
            f"Request {requirement.active_request_code} is in active coordination "
            f"({requirement.request_status.value.lower() if requirement.request_status else 'open'}) with "
            f"{_plural(requirement.attempts_made, 'attempt')} so far"
            + (f", {requirement.failed_attempts} unsuccessful." if requirement.failed_attempts else ".")
        )
    elif requirement.requirement_covered:
        sentences.append(f"A donor has already been confirmed for it under {requirement.current_request_code}.")
    else:
        sentences.append("No request has been raised for it yet.")

    sentences.append(
        f"The donor network is {network.network_strength_band.value.lower()} ({network.network_strength_score}/100): "
        f"{network.available_donor_count} of {network.known_donor_count} known donors are currently available, "
        f"{network.high_reliability_donor_count} with high reliability and "
        f"{network.fatigued_donor_count} showing elevated fatigue."
    )

    resolved = history.fulfilled_requests + history.cancelled_requests
    if resolved and history.historical_success_rate is not None:
        attempts = (
            f", averaging {history.average_coordination_attempts} attempts per request"
            if history.average_coordination_attempts is not None else ""
        )
        sentences.append(
            f"{history.fulfilled_requests} of {resolved} resolved requests were fulfilled "
            f"({history.historical_success_rate}%){attempts}."
        )

    if activity.recent_failure_count:
        sentences.append(
            f"There {'was' if activity.recent_failure_count == 1 else 'were'} "
            f"{_plural(activity.recent_failure_count, 'unsuccessful coordination attempt')} "
            f"in the last {activity.window_days} days."
        )

    sentences.append(f"Operational state: {STATE_LABELS[twin.operational_state]}.")
    return " ".join(s for s in sentences if s)
