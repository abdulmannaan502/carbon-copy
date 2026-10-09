"""Matching Engine: discovery, gates, Donor State integration, ranking, explanations and API."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.blood import COMPATIBLE_DONORS
from app.core.clock import DATASET_REFERENCE_TIME
from app.core.geo import haversine_km
from app.db.session import SessionLocal
from app.db.synthetic import DEMO_DONOR_CODES, DEMO_REQUEST_CODE
from app.models import BloodRequest
from app.models.enums import BloodGroup, UrgencyLevel
from app.repositories.donor_state_repository import DonorStateRepository
from app.services.donor_state import DonorStateEngine
from app.services.matching import (
    MATCH_WEIGHTS,
    MAX_LIMIT,
    POOL_CAP,
    geographic_fit,
    request_fit,
)

pytestmark = pytest.mark.usefixtures("seeded_app_database")
URL = "/api/v1/requests/{}/matching"


def _match(client: TestClient, code: str = DEMO_REQUEST_CODE, **params: object) -> dict:
    response = client.get(URL.format(code), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _sort_key(c: dict) -> tuple:
    return (-c["match_score"], -c["donor_priority_score"],
            c["distance_km"] if c["distance_km"] is not None else float("inf"), c["donor_code"])


def _first_request(urgency: UrgencyLevel) -> str:
    with SessionLocal() as session:
        return session.scalar(
            select(BloodRequest.request_code).where(BloodRequest.urgency_level == urgency).order_by(BloodRequest.id)
        )


# ---- pure rules ---------------------------------------------------------------------------


def test_haversine_is_correct_and_deterministic() -> None:
    hyderabad, warangal = (17.3850, 78.4867), (17.9689, 79.5941)
    distance = haversine_km(*hyderabad, *warangal)
    assert 130 < distance < 140
    assert distance == haversine_km(*hyderabad, *warangal)
    assert haversine_km(*hyderabad, *hyderabad) == 0


def test_geographic_and_request_fit_rules() -> None:
    assert [geographic_fit(d) for d in (0, 25, 50, 80)] == [100, 50, 0, 0]
    assert geographic_fit(None) == 50
    assert request_fit(True, True, False) == 100
    assert request_fit(True, False, True) == 92
    assert request_fit(False, False, False) == 56  # substitute without patient link
    assert all(sum(w.values()) == 100 for w in MATCH_WEIGHTS.values())


# ---- DEMO-REQUEST-001 ----------------------------------------------------------------------


def test_demo_matching_returns_a_ranked_list(client: TestClient) -> None:
    body = _match(client, limit=10)
    assert body["request"]["request_code"] == DEMO_REQUEST_CODE
    assert body["request"]["patient_code"] == "PAT-0001"
    assert body["evaluation"]["evaluation_point"] == "REQUEST_START"  # fulfilled request, auto
    assert body["digital_twin_context"]["patient_code"] == "PAT-0001"
    assert len(body["ranking"]) == 10
    assert [c["rank"] for c in body["ranking"]] == list(range(1, 11))
    assert body["candidate_pool_size"] == body["eligible_candidate_count"] + body["excluded_candidate_count"]
    assert body["matching_summary"]["top_candidate"] == body["ranking"][0]["donor_code"]
    assert body["weights"]["profile"] == "URGENT"
    assert "Adaptive Cascade" in body["notice"]
    assert body["data_notice"] == "Synthetic demonstration data — not for clinical use."


def test_candidate_discovery_is_narrowed_in_sql(client: TestClient) -> None:
    body = _match(client)
    discovery = body["discovery"]
    assert 0 < body["candidate_pool_size"] <= POOL_CAP
    assert discovery["total_donors"] == 6946
    assert discovery["request_location_known"] is True
    assert discovery["radius_km"] == 30
    assert discovery["compatible_donor_groups"] == ["B-", "O-"]
    assert discovery["filtered_incompatible"] > 6000
    assert discovery["filtered_inactive"] > 0
    assert discovery["filtered_outside_radius"] > 0


def test_incompatible_donors_never_enter_the_ranking(client: TestClient) -> None:
    body = _match(client, limit=MAX_LIMIT, include_excluded=True)
    allowed = {g.value for g in COMPATIBLE_DONORS[BloodGroup.B_NEG]}
    for candidate in body["ranking"] + body["excluded"]:
        assert candidate["blood_group"] in allowed
    reasons = {r["reason"]: r for r in body["matching_summary"]["top_exclusion_reasons"]}
    assert reasons["Incompatible blood group"]["stage"] == "discovery"


def test_ineligible_donors_are_excluded_with_reasons(client: TestClient) -> None:
    body = _match(client, limit=MAX_LIMIT, include_excluded=True)
    assert body["excluded"] and len(body["excluded"]) == min(MAX_LIMIT, body["excluded_candidate_count"])
    for candidate in body["excluded"]:
        assert candidate["eligible"] is False
        assert candidate["rank"] is None and candidate["match_score"] == 0
        assert candidate["exclusion_reason"]
        assert candidate["reasons"][0]["text"] == f"Excluded: {candidate['exclusion_reason']}"
    gate = [r for r in body["matching_summary"]["top_exclusion_reasons"] if r["stage"] == "gate"]
    assert sum(r["count"] for r in gate) == body["excluded_candidate_count"]
    assert any(r["reason"].startswith("Recent donation") for r in gate)


def test_ranking_uses_the_donor_state_engine(client: TestClient) -> None:
    body = _match(client, limit=5)
    with SessionLocal() as session:
        engine = DonorStateEngine(DonorStateRepository(session), DATASET_REFERENCE_TIME)
        for candidate in body["ranking"]:
            state = engine.assess_for_request(candidate["donor_code"], DEMO_REQUEST_CODE).state
            assert candidate["donor_priority_score"] == state.priority.priority_score
            assert candidate["reliability_score"] == state.reliability.reliability_score
            assert candidate["fatigue_score"] == state.fatigue.fatigue_score
            assert candidate["freshness_score"] == state.freshness.contact_freshness_score
            assert candidate["availability_status"] == state.availability.availability_status.value
            assert state.eligibility.eligible is True
            breakdown = {c["key"]: c["score"] for c in candidate["score_breakdown"]}
            assert breakdown["donor_state"] == state.priority.priority_score


def test_demo_donors_are_ranked_from_real_data(client: TestClient) -> None:
    ranking = _match(client, limit=MAX_LIMIT)["ranking"]
    ranks = {c["donor_code"]: c for c in ranking if c["donor_code"] in DEMO_DONOR_CODES}
    assert set(ranks) == set(DEMO_DONOR_CODES)  # both are eligible candidates at the request's start
    for candidate in ranks.values():
        assert candidate["response_data_sufficiency"] == "INSUFFICIENT_DATA"


# ---- scores, determinism, ties -----------------------------------------------------------


def test_scores_are_bounded_and_explained(client: TestClient) -> None:
    body = _match(client, limit=MAX_LIMIT, include_excluded=True)
    for candidate in body["ranking"]:
        for key in ("match_score", "donor_priority_score", "request_fit_score", "geographic_fit_score", "context_score"):
            assert 0 <= candidate[key] <= 100
        assert candidate["reasons"][0]["text"] == "Eligible under demo coordination rules"
        assert candidate["candidate_strategy"] and candidate["strategy_reason"]
        assert sum(c["weight"] for c in candidate["score_breakdown"]) == 100
        weighted = sum(c["points"] for c in candidate["score_breakdown"])
        expected = max(0, min(100, round(weighted) + candidate["strategy_adjustment"]))
        assert abs(candidate["match_score"] - expected) <= 1


def test_matching_is_deterministic(client: TestClient) -> None:
    assert _match(client, limit=MAX_LIMIT, include_excluded=True) == _match(client, limit=MAX_LIMIT, include_excluded=True)


def test_ties_are_broken_deterministically(client: TestClient) -> None:
    ranking = _match(client, limit=MAX_LIMIT)["ranking"]
    assert ranking == sorted(ranking, key=_sort_key)
    scores = [c["match_score"] for c in ranking]
    assert len(scores) != len(set(scores))  # the demo request really has tied match scores


def test_distances_are_reported_and_ordered_for_ties(client: TestClient) -> None:
    ranking = _match(client, limit=MAX_LIMIT)["ranking"]
    assert all(c["distance_km"] is not None and c["distance_km"] <= 45 for c in ranking)  # 30 km box corners
    assert any("km from the request location" in r["text"] for r in ranking[0]["reasons"])


# ---- urgency, exploration, recent contact ------------------------------------------------


def test_high_urgency_discounts_unproven_donors(client: TestClient) -> None:
    body = _match(client, limit=MAX_LIMIT)
    assert body["weights"] == {
        "profile": "URGENT",
        "components": MATCH_WEIGHTS["URGENT"],  # type: ignore[index]
        "exploration_bonus": 0,
        "uncertainty_discount": 5,
    }
    assert body["ranking"][0]["candidate_strategy"] == "RELIABLE"
    for candidate in body["ranking"]:
        assert candidate["strategy_adjustment"] <= 0
        if candidate["strategy_adjustment"] < 0:
            assert any("uncertainty discount" in r["text"] for r in candidate["reasons"])


def test_low_urgency_rewards_controlled_exploration(client: TestClient) -> None:
    body = _match(client, _first_request(UrgencyLevel.LOW), limit=MAX_LIMIT)
    assert body["weights"]["profile"] == "STANDARD"
    assert body["weights"]["exploration_bonus"] == 5
    explorers = [c for c in body["ranking"] if c["candidate_strategy"] == "EXPLORATION"]
    assert explorers
    for candidate in explorers:
        assert candidate["strategy_adjustment"] == 5
        assert "exploration" in candidate["strategy_reason"]
        assert any(r["text"] == "Selected for controlled exploration (+5)" for r in candidate["reasons"])
        assert candidate["response_data_sufficiency"] == "INSUFFICIENT_DATA"


def test_contacted_donors_are_handled_when_evaluated_now(client: TestClient) -> None:
    at_start = _match(client, limit=MAX_LIMIT, include_excluded=True, evaluate_at="request_start")
    now = _match(client, limit=MAX_LIMIT, include_excluded=True, evaluate_at="now")
    assert at_start["evaluation"]["evaluation_point"] == "REQUEST_START"
    assert now["evaluation"]["evaluation_point"] == "CURRENT"

    excluded_now = {c["donor_code"]: c["exclusion_reason"] for c in now["excluded"]}
    assert excluded_now[DEMO_DONOR_CODES[0]] == "Already contacted for this request without success"
    assert excluded_now[DEMO_DONOR_CODES[1]].startswith("Recent donation")
    assert "Declined or unavailable for this request" in excluded_now.values()
    for candidate in now["ranking"]:
        if candidate["availability_status"] == "RECENTLY_CONTACTED":
            assert candidate["context_score"] <= 80
            assert any("Contacted within the last few days" in r["text"] for r in candidate["reasons"])
    assert now["excluded_candidate_count"] > at_start["excluded_candidate_count"]


# ---- API parameters ----------------------------------------------------------------------


@pytest.mark.parametrize("limit", [1, 3, MAX_LIMIT])
def test_limit_controls_ranking_length(client: TestClient, limit: int) -> None:
    body = _match(client, limit=limit)
    assert len(body["ranking"]) == min(limit, body["eligible_candidate_count"])
    assert body["excluded"] == []  # include_excluded defaults to false


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": MAX_LIMIT + 1}, {"limit": "ten"}, {"evaluate_at": "later"}])
def test_invalid_parameters_are_rejected(client: TestClient, params: dict) -> None:
    assert client.get(URL.format(DEMO_REQUEST_CODE), params=params).status_code == 422


def test_missing_request_returns_404(client: TestClient) -> None:
    response = client.get(URL.format("REQ-99999"))
    assert response.status_code == 404
    assert response.json()["detail"] == "Request REQ-99999 not found"
