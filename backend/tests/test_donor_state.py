"""Donor State Intelligence Engine: rules, service and API."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.blood import COMPATIBLE_DONORS
from app.core.clock import DATASET_REFERENCE_TIME
from app.db.session import SessionLocal
from app.db.synthetic import DEMO_DONOR_CODES, DEMO_REQUEST_CODE
from app.models import BloodRequest, Donor
from app.models.enums import BloodGroup, RequestStatus
from app.repositories.donor_state_repository import DonorObservations, DonorStateRepository
from app.schemas.donor_state import DataSufficiency, FatigueBand, ScoreBand
from app.services.donor_state import (
    WEIGHT_PROFILES,
    DonationRecord,
    DonorStateEngine,
    assess_fatigue,
    assess_freshness,
    assess_reliability,
    assess_response,
)

DON_1, DON_2 = DEMO_DONOR_CODES
NOW = DATASET_REFERENCE_TIME
pytestmark = pytest.mark.usefixtures("seeded_app_database")


def _state(client: TestClient, donor: str) -> dict:
    response = client.get(f"/api/v1/donors/{donor}/state")
    assert response.status_code == 200
    return response.json()


def _for_request(client: TestClient, donor: str, request: str = DEMO_REQUEST_CODE, **params: str) -> dict:
    response = client.get(f"/api/v1/donors/{donor}/state-for-request/{request}", params=params)
    assert response.status_code == 200
    return response.json()


def _first_donor_code(*groups: BloodGroup) -> str:
    with SessionLocal() as session:
        return session.scalar(
            select(Donor.donor_code).where(Donor.blood_group.in_(groups), Donor.active.is_(True)).order_by(Donor.id)
        )


# ---- pure rules ---------------------------------------------------------------------


def test_reliability_is_smoothed_and_weighted_by_failure_type() -> None:
    nothing = assess_reliability(DonorObservations(), DonationRecord(0, None))
    assert nothing.reliability_score == 50  # neutral starting point
    one_no_response = assess_reliability(DonorObservations(no_response_failures=1), DonationRecord(0, None))
    one_decline = assess_reliability(DonorObservations(declined_failures=1), DonationRecord(0, None))
    proven = assess_reliability(DonorObservations(successes=3), DonationRecord(3, None))
    assert one_no_response.reliability_score == 33  # 100 × 1 / 3
    assert one_no_response.reliability_score < one_decline.reliability_score < 50
    assert proven.reliability_score == 80 and proven.reliability_band is ScoreBand.HIGH
    # Prior registry donations count, but are capped.
    capped = assess_reliability(DonorObservations(), DonationRecord(40, None))
    assert capped.prior_donations_counted == 10 and capped.reliability_score == 75


def test_response_requires_sufficient_history() -> None:
    thin = assess_response(DonorObservations(interactions=2, no_response=2))
    assert thin.data_sufficiency is DataSufficiency.INSUFFICIENT_DATA
    assert thin.response_rate is None and thin.no_response_rate is None
    assert thin.response_score == 25  # (0 + 1) / (2 + 2)
    rich = assess_response(DonorObservations(interactions=4, responded=2, accepted=1, no_response=1, donation_requests=2))
    assert rich.data_sufficiency is DataSufficiency.SUFFICIENT
    assert (rich.response_rate, rich.acceptance_rate, rich.no_response_rate) == (75, 50, 25)


def test_fatigue_formula_and_bands() -> None:
    assert assess_fatigue(DonorObservations(), None).fatigue_score == 0
    busy = assess_fatigue(DonorObservations(contacts_in_window=3, requests_in_window=3), days_since_donation=100)
    assert busy.fatigue_score == 30 + 30 + 20 and busy.fatigue_band is FatigueBand.HIGH
    assert assess_fatigue(DonorObservations(contacts_in_window=9), None).fatigue_score == 50  # contact points capped


def test_freshness_rises_linearly_to_thirty_days() -> None:
    assert assess_freshness(DonorObservations(), NOW).contact_freshness_score == 100
    for days, expected in ((0, 0), (3, 10), (15, 50), (45, 100)):
        obs = DonorObservations(last_contact_at=NOW - timedelta(days=days))
        assert assess_freshness(obs, NOW).contact_freshness_score == expected


def test_weight_profiles_sum_to_one_hundred() -> None:
    assert all(sum(weights.values()) == 100 for weights in WEIGHT_PROFILES.values())


# ---- demo donors -----------------------------------------------------------------------


@pytest.mark.parametrize("donor", DEMO_DONOR_CODES)
def test_demo_donor_state_exists(client: TestClient, donor: str) -> None:
    body = _state(client, donor)
    assert body["donor"]["donor_code"] == donor
    assert body["donor"]["blood_group"] == "B-"
    assert body["evaluation_point"] == "CURRENT"
    assert body["eligibility"]["rule_set"] == "demo coordination eligibility rules"
    assert body["data_notice"] == "Synthetic demonstration data — not for clinical use."
    assert body["priority"]["priority_reasons"] and body["priority"]["priority_factors"]


def test_current_state_reflects_real_demo_history(client: TestClient) -> None:
    first, second = _state(client, DON_1), _state(client, DON_2)
    # DON-00001 never answered the demo outreach: that history is now evidence.
    assert first["response"]["no_responses"] == 2 and first["response"]["total_responses"] == 0
    assert first["reliability"]["no_response_failures"] == 1
    assert first["response"]["data_sufficiency"] == "INSUFFICIENT_DATA"
    # DON-00002 accepted and donated hours ago, so the demo interval rule now defers them.
    assert second["reliability"]["successful_attempts"] == 1
    assert second["eligibility"]["eligible"] is False
    assert [c["rule"] for c in second["eligibility"]["checks"] if not c["passed"]] == ["donation_interval"]
    assert second["priority"]["priority_score"] == 0
    assert second["reliability"]["reliability_score"] > first["reliability"]["reliability_score"]


def test_demo_request_is_assessed_at_its_decision_point(client: TestClient) -> None:
    for donor in DEMO_DONOR_CODES:
        body = _for_request(client, donor)
        assert body["request"]["request_code"] == DEMO_REQUEST_CODE
        state = body["state"]
        assert state["evaluation_point"] == "REQUEST_START"
        assert state["assessed_at"] == body["request"]["requested_at"]
        # Nothing from the demo request itself is visible at its start.
        assert state["response"]["total_interactions"] == 0
        assert state["eligibility"]["eligible"] is True
        assert body["compatibility"] == {
            "request_blood_group": "B-", "donor_blood_group": "B-", "compatible": True, "exact_match": True,
            "compatible_donor_groups": ["B-", "O-"], "rule_set": "simplified ABO/Rh demo table",
        }
        assert state["priority"]["weight_profile"] == "URGENT"  # HIGH urgency request
        assert 0 < state["priority"]["priority_score"] <= 100


def test_evaluate_at_now_overrides_the_decision_point(client: TestClient) -> None:
    body = _for_request(client, DON_2, evaluate_at="now")
    assert body["state"]["evaluation_point"] == "CURRENT"
    assert body["state"]["priority"]["priority_band"] == "NOT_ELIGIBLE"


def test_demo_comparison_defaults_to_the_cascade_donors(client: TestClient) -> None:
    response = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/donor-comparison")
    assert response.status_code == 200
    body = response.json()
    scores = [c["state"]["priority"]["priority_score"] for c in body["candidates"]]
    assert {c["state"]["donor"]["donor_code"] for c in body["candidates"]} == set(DEMO_DONOR_CODES)
    assert scores == sorted(scores, reverse=True)
    assert body["recommended_donor_code"] == body["candidates"][0]["state"]["donor"]["donor_code"]
    assert body["recommendation_reason"]
    assert "not the Matching Engine" in body["notice"]


# ---- compatibility gate ----------------------------------------------------------------


def test_compatible_substitute_is_eligible_but_not_exact(client: TestClient) -> None:
    body = _for_request(client, _first_donor_code(BloodGroup.O_NEG))
    assert body["compatibility"]["compatible"] is True and body["compatibility"]["exact_match"] is False
    assert any("Compatible substitute" in r["text"] for r in body["state"]["priority"]["priority_reasons"])


def test_incompatible_donor_is_gated_to_zero(client: TestClient) -> None:
    incompatible = [g for g in BloodGroup if g not in COMPATIBLE_DONORS[BloodGroup.B_NEG]]
    body = _for_request(client, _first_donor_code(*incompatible))
    state = body["state"]
    assert body["compatibility"]["compatible"] is False
    assert state["eligibility"]["eligible"] is False
    assert state["priority"]["priority_score"] == 0
    assert state["priority"]["priority_band"] == "NOT_ELIGIBLE" and state["priority"]["gated"] is True
    assert all(f["contribution"] == 0 for f in state["priority"]["priority_factors"])
    assert state["priority"]["priority_reasons"][0]["text"].startswith("Not eligible:")


def test_incompatible_donor_never_outranks_compatible(client: TestClient) -> None:
    incompatible = _first_donor_code(BloodGroup.A_POS)
    response = client.get(
        f"/api/v1/requests/{DEMO_REQUEST_CODE}/donor-comparison",
        params={"donor_codes": f"{incompatible},{DON_1}"},
    )
    body = response.json()
    assert body["candidates"][-1]["state"]["donor"]["donor_code"] == incompatible
    assert body["recommended_donor_code"] == DON_1
    assert "not eligible" in body["recommendation_reason"]


# ---- determinism, bounds and active requests ------------------------------------------


@pytest.mark.parametrize("donor", DEMO_DONOR_CODES)
def test_assessment_is_deterministic(client: TestClient, donor: str) -> None:
    assert _state(client, donor) == _state(client, donor)
    assert _for_request(client, donor) == _for_request(client, donor)


def test_scores_are_bounded_and_explained_across_many_donors() -> None:
    with SessionLocal() as session:
        engine = DonorStateEngine(DonorStateRepository(session), NOW)
        ids = list(session.scalars(select(Donor.id).order_by(Donor.id).limit(1000)))
        states = engine.assess_ids(ids)
    assert len(states) == 1000
    for state in states.values():
        priority = state.priority
        assert 0 <= priority.priority_score <= 100
        for score in (state.reliability.reliability_score, state.response.response_score,
                      state.fatigue.fatigue_score, state.freshness.contact_freshness_score):
            assert 0 <= score <= 100
        assert sum(f.weight for f in priority.priority_factors) == 100
        assert priority.priority_reasons
        if not state.eligibility.eligible:
            assert priority.priority_score == 0
    assert {s.priority.priority_band.value for s in states.values()} >= {"HIGH", "MEDIUM", "NOT_ELIGIBLE"}


def test_active_request_is_assessed_now(client: TestClient) -> None:
    with SessionLocal() as session:
        request = session.scalar(
            select(BloodRequest).where(BloodRequest.status == RequestStatus.COORDINATING).order_by(BloodRequest.id)
        )
        code = request.request_code
        group = request.blood_group
    donor = _first_donor_code(*COMPATIBLE_DONORS[group])
    body = _for_request(client, donor, code)
    assert body["state"]["evaluation_point"] == "CURRENT"
    assert datetime.fromisoformat(body["state"]["assessed_at"]) == NOW
    assert {f["key"] for f in body["state"]["priority"]["priority_factors"]} == {
        "availability", "reliability", "response", "fatigue", "freshness", "context",
    }


# ---- errors ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("/api/v1/donors/DON-99999/state", "Donor DON-99999 not found"),
        (f"/api/v1/donors/DON-99999/state-for-request/{DEMO_REQUEST_CODE}", "Donor DON-99999 not found"),
        (f"/api/v1/donors/{DON_1}/state-for-request/REQ-99999", "Request REQ-99999 not found"),
        ("/api/v1/requests/REQ-99999/donor-comparison", "Request REQ-99999 not found"),
        (f"/api/v1/requests/{DEMO_REQUEST_CODE}/donor-comparison?donor_codes=DON-99999", "Donor DON-99999 not found"),
    ],
)
def test_unknown_codes_return_404(client: TestClient, url: str, message: str) -> None:
    response = client.get(url)
    assert response.status_code == 404
    assert response.json()["detail"] == message


def test_invalid_evaluation_point_is_rejected(client: TestClient) -> None:
    response = client.get(f"/api/v1/donors/{DON_1}/state-for-request/{DEMO_REQUEST_CODE}?evaluate_at=yesterday")
    assert response.status_code == 422
