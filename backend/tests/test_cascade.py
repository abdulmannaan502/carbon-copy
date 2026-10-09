"""Adaptive Cascade (simulation): rules, waves, re-matching, healing, escalation and API."""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.clock import DATASET_REFERENCE_TIME
from app.core.config import DATA_NOTICE
from app.db.session import SessionLocal
from app.db.synthetic import DEMO_REQUEST_CODE
from app.models.enums import InteractionChannel, RecoveryActionType, UrgencyLevel
from app.repositories.digital_twin_repository import DigitalTwinRepository
from app.repositories.donor_state_repository import DonorStateRepository
from app.repositories.failure_autopsy_repository import FailureAutopsyRepository
from app.repositories.matching_repository import MatchingRepository
from app.schemas.cascade import CascadeContact, CascadeOutcome, CascadeResult, SimulatedResponse
from app.schemas.matching import MatchCandidate
from app.services.cascade import (
    CASCADE_SEED,
    MAX_WAVE_SIZE,
    HealingContext,
    AdaptiveCascadeEngine,
    acceptance_probability,
    choose_healing,
    response_probability,
    unit_draw,
    wave_autopsy,
)
from app.services.digital_twin import DigitalTwinService
from app.services.donor_state import DonorStateEngine
from app.services.failure_autopsy import FailureAutopsyEngine
from app.services.matching import CONTACTED_IN_CASCADE, MatchingEngine

pytestmark = pytest.mark.usefixtures("seeded_app_database")
URL = "/api/v1/requests/{}/cascade"


@pytest.fixture
def engine() -> Iterator[AdaptiveCascadeEngine]:
    with SessionLocal() as session:
        donor_states = DonorStateEngine(DonorStateRepository(session), DATASET_REFERENCE_TIME)
        twins = DigitalTwinService(DigitalTwinRepository(session), donor_states, DATASET_REFERENCE_TIME)
        matching = MatchingEngine(MatchingRepository(session), donor_states, twins)
        failure_autopsy = FailureAutopsyEngine(
            FailureAutopsyRepository(session), matching, DATASET_REFERENCE_TIME, DATA_NOTICE
        )
        yield AdaptiveCascadeEngine(session, matching, failure_autopsy)


def _find(engine: AdaptiveCascadeEngine, predicate: Callable[[CascadeResult], bool], **kwargs: object) -> CascadeResult:
    """Search scenario seeds for one that exercises a given path (keeps tests independent of hash details)."""
    for seed in range(1, 200):
        result = engine.simulate(DEMO_REQUEST_CODE, seed=seed, **kwargs)  # type: ignore[arg-type]
        if predicate(result):
            return result
    raise AssertionError("no seed produced the scenario")


def _contacts(result: CascadeResult) -> list[CascadeContact]:
    return [c for wave in result.waves for c in wave.contacts]


def _candidate(client: TestClient) -> MatchCandidate:
    body = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/matching", params={"limit": 1}).json()
    return MatchCandidate.model_validate(body["ranking"][0])


# ---- pure rules -------------------------------------------------------------------------------


def test_unit_draw_is_deterministic_and_bounded() -> None:
    a = unit_draw(1, "REQ", "DON-1", "reply")
    assert a == unit_draw(1, "REQ", "DON-1", "reply")
    assert 0 <= a < 1
    assert a != unit_draw(2, "REQ", "DON-1", "reply") != unit_draw(1, "REQ", "DON-1", "accept")


def test_response_and_acceptance_probabilities(client: TestClient) -> None:
    candidate = _candidate(client)
    sms = response_probability(candidate, InteractionChannel.SIMULATED_SMS)
    call = response_probability(candidate, InteractionChannel.SIMULATED_CALL)
    stressed = response_probability(candidate, InteractionChannel.SIMULATED_SMS, 0.5)
    assert 0.05 <= stressed < sms <= call <= 0.95
    assert sms == pytest.approx(min(0.95, max(0.05, candidate.response_score / 100)))
    assert 0.05 <= acceptance_probability(candidate) <= 0.95


def _ctx(**overrides: object) -> HealingContext:
    base = dict(
        wave_number=1, max_waves=5, autopsy=wave_autopsy([]), remaining_candidates=20, radius_step=0,
        bridge_members_remaining=True, bridge_group_used=False, urgency=UrgencyLevel.HIGH, wave_size=3,
        channel_override=None,
    )
    return HealingContext(**{**base, **overrides})  # type: ignore[arg-type]


def test_healing_rules_in_order() -> None:
    no_reply = wave_autopsy([
        CascadeContact.model_construct(response=SimulatedResponse.NO_RESPONSE),
        CascadeContact.model_construct(response=SimulatedResponse.NO_RESPONSE),
        CascadeContact.model_construct(response=SimulatedResponse.DECLINED),
    ])
    assert no_reply.dominant_cause is SimulatedResponse.NO_RESPONSE
    declined = wave_autopsy([CascadeContact.model_construct(response=SimulatedResponse.DECLINED)])

    alternative = choose_healing(_ctx(autopsy=no_reply))
    assert alternative.action is RecoveryActionType.ALTERNATIVE_DONOR
    assert alternative.channel_override is InteractionChannel.SIMULATED_CALL and alternative.next_wave_size == 4
    assert choose_healing(_ctx(autopsy=declined)).action is RecoveryActionType.NEXT_DONOR
    bridge = choose_healing(_ctx(wave_number=2, autopsy=no_reply))
    assert bridge.action is RecoveryActionType.BRIDGE_GROUP_ESCALATION and bridge.bridge_group_first
    expand = choose_healing(_ctx(wave_number=3, bridge_group_used=True))
    assert expand.action is RecoveryActionType.EXPANDED_SEARCH and expand.radius_step == 1
    assert choose_healing(_ctx(remaining_candidates=0)).action is RecoveryActionType.EXPANDED_SEARCH
    assert choose_healing(_ctx(remaining_candidates=0, radius_step=2)).action is RecoveryActionType.HUMAN_COORDINATOR_REVIEW
    final = choose_healing(_ctx(wave_number=5, urgency=UrgencyLevel.CRITICAL))
    assert final.action is RecoveryActionType.BLOOD_BANK_REFERRAL and final.next_wave_size is None
    assert choose_healing(_ctx(autopsy=no_reply, wave_size=MAX_WAVE_SIZE)).next_wave_size == MAX_WAVE_SIZE


def test_matching_can_exclude_cascade_contacts(engine: AdaptiveCascadeEngine) -> None:
    matching = engine._matching
    top = matching.match(DEMO_REQUEST_CODE, 1).ranking[0].donor_code
    rerun = matching.match(DEMO_REQUEST_CODE, 50, include_excluded=True, exclude_donor_codes=frozenset({top}))
    assert top not in {c.donor_code for c in rerun.ranking}
    assert {c.donor_code: c.exclusion_reason for c in rerun.excluded}[top] == CONTACTED_IN_CASCADE


# ---- simulation ---------------------------------------------------------------------------------


def test_demo_cascade_default(client: TestClient) -> None:
    response = client.get(URL.format(DEMO_REQUEST_CODE))
    assert response.status_code == 200
    body = response.json()
    assert body["parameters"] == {
        "wave_size": 3, "max_waves": 5, "response_window_minutes": 120, "seed": CASCADE_SEED,
        "initial_channel_policy": body["parameters"]["initial_channel_policy"], "response_stress": "none",
    }
    assert body["evaluation_point"] == "REQUEST_START"
    matching = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/matching", params={"limit": 3}).json()
    first_wave = body["waves"][0]
    assert [c["donor_code"] for c in first_wave["contacts"]] == [c["donor_code"] for c in matching["ranking"]]
    assert first_wave["applied_action"] is None
    assert [h["donor_code"] for h in body["historical_attempts"]] == ["DON-00001", "DON-00002"]
    assert "nothing is persisted" in body["notice"]


def test_cascade_is_deterministic_and_seed_sensitive(client: TestClient) -> None:
    first = client.get(URL.format(DEMO_REQUEST_CODE), params={"seed": 7}).json()
    assert first == client.get(URL.format(DEMO_REQUEST_CODE), params={"seed": 7}).json()
    outcomes = {
        tuple(c["response"] for w in client.get(URL.format(DEMO_REQUEST_CODE), params={"seed": s}).json()["waves"]
              for c in w["contacts"])
        for s in range(1, 6)
    }
    assert len(outcomes) > 1


def test_outcome_is_internally_consistent(engine: AdaptiveCascadeEngine) -> None:
    for seed in range(1, 25):
        result = engine.simulate(DEMO_REQUEST_CODE, seed=seed, response_stress="severe")
        contacts = _contacts(result)
        codes = [c.donor_code for c in contacts]
        assert len(codes) == len(set(codes))  # nobody contacted twice
        assert result.total_contacts == len(contacts)
        assert result.units_secured == sum(c.secured for c in contacts) == len(result.secured_donor_codes)
        for c in contacts:
            if c.secured:
                assert c.response is SimulatedResponse.ACCEPTED
        if result.outcome is CascadeOutcome.FULFILLED:
            assert result.units_secured == result.units_required and result.escalation is None
            assert result.waves[-1].healing is None
        for wave in result.waves[:-1]:
            assert wave.autopsy is not None and wave.healing is not None
        for earlier, later in zip(result.waves, result.waves[1:]):
            assert later.applied_action is earlier.healing.action  # type: ignore[union-attr]
            assert later.started_at > earlier.closed_at


def test_failed_wave_heals_and_rematches(engine: AdaptiveCascadeEngine) -> None:
    result = _find(engine, lambda r: r.waves_used >= 2 and r.waves[0].healing.action  # type: ignore[union-attr]
                   is RecoveryActionType.ALTERNATIVE_DONOR)
    first, second = result.waves[0], result.waves[1]
    assert first.autopsy.dominant_cause is SimulatedResponse.NO_RESPONSE  # type: ignore[union-attr]
    assert second.applied_action is RecoveryActionType.ALTERNATIVE_DONOR
    assert second.wave_size == first.wave_size + 1
    assert all(c.channel is InteractionChannel.SIMULATED_CALL for c in second.contacts)
    assert not {c.donor_code for c in first.contacts} & {c.donor_code for c in second.contacts}
    assert second.eligible_candidates == first.eligible_candidates - first.wave_size  # re-matched without them


def test_bridge_group_escalation_prioritises_members(engine: AdaptiveCascadeEngine) -> None:
    result = _find(engine, lambda r: any(w.applied_action is RecoveryActionType.BRIDGE_GROUP_ESCALATION
                                         for w in r.waves), response_stress="severe")
    wave = next(w for w in result.waves if w.applied_action is RecoveryActionType.BRIDGE_GROUP_ESCALATION)
    flags = [c.bridge_group_member for c in wave.contacts]
    assert flags[0] is True
    assert flags == sorted(flags, reverse=True)  # members first


def test_exhausted_cascade_escalates(engine: AdaptiveCascadeEngine) -> None:
    result = _find(engine, lambda r: r.outcome is CascadeOutcome.ESCALATED, max_waves=1, response_stress="severe")
    assert result.escalation is not None
    assert result.escalation.action is RecoveryActionType.HUMAN_COORDINATOR_REVIEW  # HIGH urgency, not CRITICAL
    assert result.units_secured < result.units_required
    assert result.deadline_met is False


def test_learning_preview_covers_every_contact(engine: AdaptiveCascadeEngine) -> None:
    result = _find(engine, lambda r: r.waves_used >= 2)
    contact_signals = [s for s in result.learning_preview if s.donor_code is not None]
    assert [s.donor_code for s in contact_signals] == [c.donor_code for c in _contacts(result)]
    assert any(s.donor_code is None and s.event_type.value.startswith("RECOVERY_") for s in result.learning_preview)


def test_simulation_persists_nothing(client: TestClient) -> None:
    before = client.get("/api/v1/system/dataset-stats").json()
    client.get(URL.format(DEMO_REQUEST_CODE), params={"response_stress": "severe", "max_waves": 8})
    assert client.get("/api/v1/system/dataset-stats").json() == before


# ---- API parameters ---------------------------------------------------------------------------


def test_wave_size_override(client: TestClient) -> None:
    body = client.get(URL.format(DEMO_REQUEST_CODE), params={"wave_size": 2}).json()
    assert body["parameters"]["wave_size"] == 2 and body["waves"][0]["wave_size"] == 2


@pytest.mark.parametrize("params", [
    {"max_waves": 0}, {"max_waves": 9}, {"wave_size": 0}, {"wave_size": 7}, {"seed": -1},
    {"response_stress": "extreme"}, {"evaluate_at": "later"},
])
def test_invalid_parameters_are_rejected(client: TestClient, params: dict) -> None:
    assert client.get(URL.format(DEMO_REQUEST_CODE), params=params).status_code == 422


def test_missing_request_returns_404(client: TestClient) -> None:
    response = client.get(URL.format("REQ-99999"))
    assert response.status_code == 404 and response.json()["detail"] == "Request REQ-99999 not found"
