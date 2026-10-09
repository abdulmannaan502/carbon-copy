"""Living Digital Twin: calculation rules, service and API."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db.synthetic import DEMO_PATIENT_CODE, DEMO_REQUEST_CODE, REQUESTS_PER_PATIENT, TARGET_COUNTS
from app.schemas.digital_twin import NetworkStrengthBand, OperationalState, RecurrenceStatus
from app.services.digital_twin import (
    StateSignals,
    calculate_network_strength,
    calculate_recurrence,
    determine_operational_state,
)

TWIN_URL = "/api/v1/patients/{}/digital-twin"


@pytest.fixture
def demo_twin(client: TestClient, seeded_app_database: None) -> dict:
    response = client.get(TWIN_URL.format(DEMO_PATIENT_CODE))
    assert response.status_code == 200
    return response.json()


# ---- pure rules -------------------------------------------------------------


@pytest.mark.parametrize(
    ("days_ahead", "expected"),
    [(-1, RecurrenceStatus.OVERDUE), (0, RecurrenceStatus.DUE), (2, RecurrenceStatus.DUE),
     (3, RecurrenceStatus.APPROACHING), (7, RecurrenceStatus.APPROACHING), (8, RecurrenceStatus.STABLE)],
)
def test_recurrence_windows_scale_with_cadence(days_ahead: int, expected: RecurrenceStatus) -> None:
    today = date(2026, 10, 8)
    next_expected = date.fromordinal(today.toordinal() + days_ahead)
    # 21-day cadence: DUE within 2 days, APPROACHING within 7.
    assert calculate_recurrence(next_expected, 21, today) == (days_ahead, expected)


def test_recurrence_unknown_without_cadence() -> None:
    assert calculate_recurrence(None, 21, date(2026, 10, 8)) == (None, RecurrenceStatus.UNKNOWN)
    assert calculate_recurrence(date(2026, 10, 9), None, date(2026, 10, 8)) == (None, RecurrenceStatus.UNKNOWN)


def test_network_strength_is_bounded() -> None:
    empty = calculate_network_strength(available=0, active=0, fatigued=0, mean_reliability=None, mean_response_rate=None)
    full = calculate_network_strength(available=500, active=500, fatigued=0, mean_reliability=1.0, mean_response_rate=1.0)
    assert empty[0] == 0 and empty[1] is NetworkStrengthBand.WEAK
    assert full[0] == 100 and full[1] is NetworkStrengthBand.STRONG


def _signals(**overrides: object) -> StateSignals:
    base = dict(
        patient_active=True, active_request_code=None, active_request_status=None,
        recurrence=RecurrenceStatus.STABLE, days_until=15, requirement_covered=False, covering_request_code=None,
        network_band=NetworkStrengthBand.STRONG, network_score=85, recent_failures=0, fatigue_share=0.1,
    )
    return StateSignals(**{**base, **overrides})  # type: ignore[arg-type]


def test_operational_state_rules_and_precedence() -> None:
    from app.models.enums import RequestStatus

    assert determine_operational_state(_signals())[0] is OperationalState.HEALTHY
    assert determine_operational_state(_signals(recent_failures=2))[0] is OperationalState.WATCH
    assert determine_operational_state(_signals(network_band=NetworkStrengthBand.WEAK, network_score=40))[0] \
        is OperationalState.ATTENTION
    approaching = _signals(recurrence=RecurrenceStatus.APPROACHING, days_until=4)
    assert determine_operational_state(approaching)[0] is OperationalState.ATTENTION
    # A covered requirement is not a reason for attention.
    covered = _signals(recurrence=RecurrenceStatus.APPROACHING, requirement_covered=True, covering_request_code="R")
    assert determine_operational_state(covered)[0] is OperationalState.HEALTHY
    active = _signals(active_request_code="REQ-1", active_request_status=RequestStatus.COORDINATING,
                      network_band=NetworkStrengthBand.WEAK, network_score=40)
    assert determine_operational_state(active)[0] is OperationalState.ACTIVE_COORDINATION


# ---- PAT-0001 -----------------------------------------------------------------


def test_demo_twin_identity(demo_twin: dict) -> None:
    patient = demo_twin["patient"]
    assert patient["patient_code"] == DEMO_PATIENT_CODE
    assert patient["display_name"] == "Meera S."
    assert patient["blood_group"] == "B-"
    assert (patient["city"], patient["bridge_group_code"]) == ("Hyderabad", "BG-0001")


def test_demo_twin_transfusion_profile(demo_twin: dict) -> None:
    profile = demo_twin["transfusion_profile"]
    assert profile["transfusion_frequency_days"] == 21
    assert profile["next_expected_requirement"] == "2026-10-11"
    assert profile["days_until_expected_requirement"] == 3
    assert profile["recurrence_status"] == "APPROACHING"


def test_demo_twin_requirement_is_covered_by_demo_request(demo_twin: dict) -> None:
    requirement = demo_twin["requirement_state"]
    assert requirement["active_request"] is False
    assert requirement["active_request_code"] is None
    assert requirement["current_request_code"] == DEMO_REQUEST_CODE
    assert requirement["requirement_covered"] is True
    assert (requirement["units_required"], requirement["request_urgency"]) == (1, "HIGH")
    assert (requirement["attempts_made"], requirement["failed_attempts"]) == (2, 1)
    assert requirement["latest_attempt_status"] == "SUCCESS"


def test_demo_twin_history_counts(demo_twin: dict) -> None:
    history = demo_twin["coordination_history"]
    assert history["total_requests"] == REQUESTS_PER_PATIENT
    assert len(history["requests"]) == REQUESTS_PER_PATIENT
    assert history["requests"][-1]["request_code"] == DEMO_REQUEST_CODE


def test_demo_twin_state_and_summary(demo_twin: dict) -> None:
    assert demo_twin["operational_state"] == "WATCH"
    assert any("failed coordination attempt" in reason for reason in demo_twin["operational_state_reasons"])
    summary = demo_twin["summary"]
    assert summary.startswith("Patient PAT-0001 has a recurring B- requirement every 21 days.")
    assert DEMO_REQUEST_CODE in summary
    assert demo_twin["summary_source"] == "deterministic"


def test_demo_timeline_tells_failure_recovery_success(demo_twin: dict) -> None:
    activity = demo_twin["recent_activity"]
    assert activity["window_days"] == 30
    assert activity["focus_request_code"] == DEMO_REQUEST_CODE
    kinds = [event["kind"] for event in activity["timeline"]]
    assert kinds == [
        "REQUEST_CREATED", "AVAILABILITY_CHECKS",
        "DONOR_CONTACTED", "ATTEMPT_FAILED", "FAILURE_DETECTED", "RECOVERY_INITIATED",
        "DONOR_CONTACTED", "DONOR_ACCEPTED", "REQUEST_FULFILLED",
    ]
    assert "DON-00002" in activity["timeline"][5]["title"]


def test_twin_is_deterministic(client: TestClient, demo_twin: dict) -> None:
    assert client.get(TWIN_URL.format(DEMO_PATIENT_CODE)).json() == demo_twin


# ---- every patient ----------------------------------------------------------------


@pytest.fixture(scope="module")
def all_twins(seeded_app_database: None) -> list[dict]:
    from app.main import create_app

    with TestClient(create_app()) as client:
        return [client.get(TWIN_URL.format(f"PAT-{n:04d}")).json() for n in range(1, TARGET_COUNTS["patients"] + 1)]


def test_history_metrics_are_internally_consistent(all_twins: list[dict]) -> None:
    for twin in all_twins:
        h = twin["coordination_history"]
        assert h["fulfilled_requests"] + h["cancelled_requests"] + h["active_requests"] == h["total_requests"]
        assert h["recovering_requests"] <= h["active_requests"]
        assert h["requests_with_failures"] <= h["total_requests"]
        assert sum(r["attempts"] for r in h["requests"]) == h["total_coordination_attempts"]
        assert sum(r["failed_attempts"] for r in h["requests"]) == h["total_failures"]
        assert h["successful_recoveries"] <= h["total_recovery_actions"] <= h["total_failures"]
        for rate in (h["historical_success_rate"], h["first_attempt_success_rate"]):
            assert rate is None or 0 <= rate <= 100


def test_network_metrics_are_bounded(all_twins: list[dict]) -> None:
    for twin in all_twins:
        n = twin["network_state"]
        assert 0 <= n["available_donor_count"] <= n["active_donor_count"] <= n["known_donor_count"]
        for key in ("high_reliability_donor_count", "fatigued_donor_count"):
            assert 0 <= n[key] <= n["active_donor_count"]
        for key in ("recently_contacted_donor_count", "bridge_group_donor_count"):
            assert 0 <= n[key] <= n["known_donor_count"]
        assert 0 <= n["network_strength_score"] <= 100
        assert all(0 <= value <= 100 for value in n["strength_components"].values())


def test_active_coordination_matches_active_requests(all_twins: list[dict]) -> None:
    states = {twin["operational_state"] for twin in all_twins}
    assert "ACTIVE_COORDINATION" in states and len(states) > 1
    for twin in all_twins:
        is_active = twin["operational_state"] == "ACTIVE_COORDINATION"
        assert is_active == twin["requirement_state"]["active_request"]


# ---- request context & errors -----------------------------------------------------


def test_demo_request_context(client: TestClient, seeded_app_database: None) -> None:
    response = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/digital-twin-context")
    assert response.status_code == 200
    body = response.json()
    request = body["request"]
    assert request["request_code"] == DEMO_REQUEST_CODE
    assert request["status"] == "FULFILLED" and request["is_current_request"] is True
    assert request["compatible_donor_groups"] == ["B-", "O-"]
    assert (request["attempts"], request["failed_attempts"]) == (2, 1)
    assert request["latest_attempt_outcome"] == "DONOR_ACCEPTED"
    assert (request["latest_recovery_action"], request["latest_recovery_status"]) == ("ALTERNATIVE_DONOR", "COMPLETED")
    assert body["digital_twin"]["patient"]["patient_code"] == DEMO_PATIENT_CODE


@pytest.mark.parametrize(
    "url", ["/api/v1/patients/PAT-9999/digital-twin", "/api/v1/requests/REQ-99999/digital-twin-context"]
)
def test_unknown_codes_return_404(client: TestClient, seeded_app_database: None, url: str) -> None:
    response = client.get(url)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
