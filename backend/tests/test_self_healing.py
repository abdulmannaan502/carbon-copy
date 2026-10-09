"""Self-Healing Engine: policy rules and priority, limits, escalation, apply, cascade integration and API."""

import time
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.core.clock import DATASET_REFERENCE_TIME
from app.core.config import DATA_NOTICE
from app.db.session import SessionLocal, engine as db_engine
from app.db.synthetic import DEMO_REQUEST_CODE
from app.models.enums import FailureSeverity, InteractionChannel, RecoveryActionType, UrgencyLevel
from app.repositories.digital_twin_repository import DigitalTwinRepository
from app.repositories.donor_state_repository import DonorStateRepository
from app.repositories.failure_autopsy_repository import FailureAutopsyRepository
from app.repositories.matching_repository import MatchingRepository
from app.schemas.cascade import CascadeOutcome, CascadeResult
from app.schemas.failure_autopsy import FailurePatternType, FailureSource, RecoveryRecommendation
from app.schemas.self_healing import BridgePriority, EscalationType
from app.services.cascade import AdaptiveCascadeEngine
from app.services.digital_twin import DigitalTwinService
from app.services.donor_state import DonorStateEngine
from app.services.failure_autopsy import FailureAutopsyEngine
from app.services.matching import MatchingEngine
from app.services.self_healing import (
    HUMAN_ESCALATION_CONTACTS,
    MAX_CHANNEL_SWITCHES,
    MAX_RADIUS_STEP,
    MAX_RECOVERY_ATTEMPTS,
    MAX_WAVE_SIZE,
    PERSISTED_ACTION,
    CascadeState,
    FailureSignal,
    MalformedStateError,
    SelfHealingEngine,
    WaveSettings,
    persisted_action,
)

pytestmark = pytest.mark.usefixtures("seeded_app_database")
URL = "/api/v1/requests/{}/self-healing"
Action = RecoveryRecommendation
Pattern = FailurePatternType
CALL, SMS = InteractionChannel.SIMULATED_CALL, InteractionChannel.SIMULATED_SMS
healing = SelfHealingEngine()


def _state(**overrides: object) -> CascadeState:
    base: dict[str, object] = dict(
        wave_number=1, max_waves=5, urgency=UrgencyLevel.HIGH, wave_size=3, channel_override=None, radius_step=0,
        contacted_total=3, remaining_candidates=40, wave_contacted=3,
    )
    return CascadeState(**{**base, **overrides})  # type: ignore[arg-type]


def _signal(pattern: Pattern | None = None, failures: int = 3, severity: FailureSeverity | None = FailureSeverity.HIGH,
            confidence: float | None = 0.8) -> FailureSignal:
    return FailureSignal(pattern, severity, confidence, failures, None)


def _plan(state: CascadeState, signal: FailureSignal):  # type: ignore[no-untyped-def]
    return healing.plan_from_signal(DEMO_REQUEST_CODE, state, signal)


# ---- the policy, rule by rule ------------------------------------------------------------------


def test_nothing_outstanding_means_no_change() -> None:
    plan = _plan(_state(units_outstanding=0), _signal(Pattern.CHANNEL_RESPONSE_FAILURE))
    assert plan.primary_action is Action.NO_CHANGE and plan.fallback_actions == []
    assert plan.changes.model_dump(exclude_none=True) == {} and not plan.requires_human_intervention


def test_channel_response_failure_switches_channel_and_widens_wave() -> None:
    state = _state(no_response_channels=(SMS, SMS, SMS))
    plan = _plan(state, _signal(Pattern.CHANNEL_RESPONSE_FAILURE))
    assert plan.rule_id == "P5" and plan.primary_action is Action.SWITCH_CHANNEL
    assert plan.changes.model_dump(exclude_none=True) == {"channel": CALL, "wave_size": 4}
    assert "may improve" in plan.expected_effect and "guaranteed" in plan.expected_effect
    assert any("SMS" in item or "no-response" in item for item in plan.evidence)
    assert Action.INCREASE_WAVE_SIZE in plan.fallback_actions and Action.SWITCH_CHANNEL not in plan.fallback_actions


def test_channel_switch_is_not_offered_when_calls_already_failed() -> None:
    state = _state(no_response_channels=(CALL, CALL, CALL))
    plan = _plan(state, _signal(Pattern.CHANNEL_RESPONSE_FAILURE))
    assert plan.primary_action is Action.INCREASE_WAVE_SIZE  # no stronger channel exists
    assert "no better channel" in plan.reason


def test_channel_switch_limit() -> None:
    state = _state(no_response_channels=(SMS, SMS), channel_switches=MAX_CHANNEL_SWITCHES)
    plan = _plan(state, _signal(Pattern.CHANNEL_RESPONSE_FAILURE, failures=2))
    assert plan.primary_action is not Action.SWITCH_CHANNEL
    assert Action.SWITCH_CHANNEL not in plan.fallback_actions


def test_several_failures_with_enough_candidates_increase_wave_size() -> None:
    plan = _plan(_state(), _signal(Pattern.RESPONSE_WINDOW_FAILURE))
    assert plan.rule_id == "P8" and plan.primary_action is Action.INCREASE_WAVE_SIZE
    assert plan.changes.wave_size == 4


def test_wave_size_never_exceeds_the_limit() -> None:
    plan = _plan(_state(wave_size=MAX_WAVE_SIZE), _signal(Pattern.RESPONSE_WINDOW_FAILURE))
    assert plan.primary_action is not Action.INCREASE_WAVE_SIZE
    near = _plan(_state(wave_size=MAX_WAVE_SIZE - 1, remaining_candidates=40), _signal(Pattern.RESPONSE_WINDOW_FAILURE))
    assert near.changes.wave_size == MAX_WAVE_SIZE
    applied = healing.apply(near, WaveSettings(MAX_WAVE_SIZE - 1))
    assert applied.wave_size == MAX_WAVE_SIZE


def test_wave_size_waits_for_enough_usable_candidates() -> None:
    thin = _state(remaining_candidates=5, fatigued_remaining=0)
    assert _plan(thin, _signal(Pattern.RESPONSE_WINDOW_FAILURE)).primary_action is not Action.INCREASE_WAVE_SIZE


def test_single_failure_tries_an_alternative_donor() -> None:
    plan = _plan(_state(), _signal(Pattern.INDIVIDUAL_DONOR_FAILURE, failures=1, confidence=0.9))
    assert plan.rule_id == "P9" and plan.primary_action is Action.TRY_ALTERNATIVE_DONOR
    assert plan.changes.model_dump(exclude_none=True) == {}


def test_unexplained_failures_rerun_matching() -> None:
    plan = _plan(_state(), FailureSignal(None, None, None, 0, None))
    assert plan.rule_id == "P10" and plan.primary_action is Action.RE_RUN_MATCHING


def test_bridge_group_failure_tries_the_other_group_strategy() -> None:
    state = _state(remaining_candidates=40, bridge_remaining=6, bridge_priority=BridgePriority.BRIDGE_FIRST)
    plan = _plan(state, _signal(Pattern.BRIDGE_GROUP_FAILURE))
    assert plan.rule_id == "P4" and plan.primary_action is Action.TRY_ALTERNATIVE_BRIDGE_GROUP
    assert plan.changes.bridge_priority is BridgePriority.NON_BRIDGE_FIRST
    # already tried: do not repeat it
    again = _plan(_state(bridge_remaining=6, bridge_priority=BridgePriority.NON_BRIDGE_FIRST), _signal(Pattern.BRIDGE_GROUP_FAILURE))
    assert again.primary_action is not Action.TRY_ALTERNATIVE_BRIDGE_GROUP


def test_second_failed_wave_prioritises_the_bridge_group() -> None:
    plan = _plan(_state(wave_number=2, recovery_attempts=1, bridge_remaining=5), _signal(Pattern.UNKNOWN_PATTERN))
    assert plan.rule_id == "P7" and plan.changes.bridge_priority is BridgePriority.BRIDGE_FIRST
    assert healing.apply(plan, WaveSettings(3)).bridge_priority is BridgePriority.BRIDGE_FIRST


def test_failing_local_pool_expands_the_search_radius() -> None:
    plan = _plan(_state(), _signal(Pattern.LOCAL_POOL_FAILURE))
    assert plan.rule_id == "P6" and plan.primary_action is Action.EXPAND_SEARCH_RADIUS
    assert plan.changes.radius_step == 1 and plan.changes.radius_km == 80.0
    repeated = _plan(_state(wave_number=3, recovery_attempts=2), _signal(Pattern.UNKNOWN_PATTERN))
    assert repeated.primary_action is Action.EXPAND_SEARCH_RADIUS


def test_fatigued_pool_expands_the_search_radius() -> None:
    state = _state(remaining_candidates=10, fatigued_remaining=9)  # only 1 non-fatigued candidate left
    plan = _plan(state, _signal(Pattern.RESPONSE_WINDOW_FAILURE))
    assert plan.primary_action is Action.EXPAND_SEARCH_RADIUS


def test_radius_never_goes_past_the_widest_step() -> None:
    state = _state(radius_step=MAX_RADIUS_STEP, remaining_candidates=10, fatigued_remaining=9)
    plan = _plan(state, _signal(Pattern.LOCAL_POOL_FAILURE))
    assert plan.primary_action is not Action.EXPAND_SEARCH_RADIUS
    assert Action.EXPAND_SEARCH_RADIUS not in plan.fallback_actions
    last = _plan(_state(radius_step=MAX_RADIUS_STEP - 1), _signal(Pattern.LOCAL_POOL_FAILURE))
    assert healing.apply(last, WaveSettings(3, radius_step=MAX_RADIUS_STEP - 1)).radius_step == MAX_RADIUS_STEP


def test_no_candidates_left_expands_then_escalates() -> None:
    expand = _plan(_state(remaining_candidates=0), _signal())
    assert expand.rule_id == "P2" and expand.primary_action is Action.EXPAND_SEARCH_RADIUS
    stop = _plan(_state(remaining_candidates=0, radius_step=MAX_RADIUS_STEP), _signal(Pattern.CANDIDATE_POOL_EXHAUSTION))
    assert stop.primary_action is Action.HUMAN_COORDINATOR and stop.requires_human_intervention


# ---- escalation, priority, urgency, severity -------------------------------------------------------


def test_wave_limit_escalates_by_urgency() -> None:
    high = _plan(_state(wave_number=5), _signal())
    assert high.primary_action is Action.HUMAN_COORDINATOR and high.escalation_type is EscalationType.HUMAN_COORDINATOR
    critical = _plan(_state(wave_number=5, urgency=UrgencyLevel.CRITICAL), _signal())
    assert critical.primary_action is Action.BLOOD_BANK_ESCALATION and critical.escalation_type is EscalationType.BLOOD_BANK
    assert critical.fallback_actions == [Action.HUMAN_COORDINATOR]


def test_escalation_explains_why_automation_stopped() -> None:
    state = _state(wave_number=5, contacted_total=15, recovery_attempts=2, applied_actions=("SWITCH_CHANNEL", "EXPAND_SEARCH_RADIUS"),
                   failure_totals={"NO_RESPONSE": 9, "DECLINED": 6})
    plan = _plan(state, _signal())
    summary = plan.escalation
    assert summary is not None and plan.requires_human_intervention
    assert summary.actions_attempted == ["SWITCH_CHANNEL", "EXPAND_SEARCH_RADIUS"]
    assert summary.donors_contacted == 15 and summary.failures == {"NO_RESPONSE": 9, "DECLINED": 6}
    assert "wave limit" in summary.why_automation_stopped and summary.recommended_human_action
    assert healing.apply(plan, WaveSettings(3)) == WaveSettings(3)  # escalation changes nothing automatically


def test_recovery_attempt_limit_stops_automation() -> None:
    plan = _plan(_state(wave_number=4, recovery_attempts=MAX_RECOVERY_ATTEMPTS), _signal(Pattern.CHANNEL_RESPONSE_FAILURE))
    assert plan.rule_id == "P1" and plan.requires_human_intervention


def test_contact_threshold_stops_automation() -> None:
    plan = _plan(_state(wave_number=3, contacted_total=HUMAN_ESCALATION_CONTACTS), _signal())
    assert plan.rule_id == "P1" and "contacted" in plan.reason


def test_critical_stall_goes_to_the_blood_bank_early() -> None:
    state = _state(wave_number=3, urgency=UrgencyLevel.CRITICAL, recovery_attempts=2)
    plan = _plan(state, _signal(Pattern.UNKNOWN_PATTERN, severity=FailureSeverity.CRITICAL))
    assert plan.rule_id == "P3" and plan.escalation_type is EscalationType.BLOOD_BANK
    calm = _plan(state, _signal(Pattern.UNKNOWN_PATTERN, severity=FailureSeverity.MEDIUM))
    assert not calm.requires_human_intervention


def test_rule_priority_first_match_wins() -> None:
    # A channel pattern is overridden by the safety limit, and exhaustion beats a channel switch.
    channel = _signal(Pattern.CHANNEL_RESPONSE_FAILURE)
    state = _state(no_response_channels=(SMS, SMS, SMS))
    assert _plan(state, channel).rule_id == "P5"
    assert _plan(_state(wave_number=5, no_response_channels=(SMS,) * 3), channel).rule_id == "P1"
    assert _plan(_state(remaining_candidates=0, no_response_channels=(SMS,) * 3), channel).rule_id == "P2"
    # bridge failure outranks a local-pool pattern's radius expansion at equal state
    assert _plan(_state(bridge_remaining=4), _signal(Pattern.BRIDGE_GROUP_FAILURE)).rule_id == "P4"


def test_plans_carry_rule_strength_and_a_state_snapshot() -> None:
    plan = _plan(_state(no_response_channels=(SMS, SMS, SMS)), _signal(Pattern.CHANNEL_RESPONSE_FAILURE, confidence=0.9))
    assert 0 < plan.rule_strength <= 0.95
    assert plan.current_state.wave_size == 3 and plan.current_state.eligible_remaining == 40
    assert plan.trigger.pattern is Pattern.CHANNEL_RESPONSE_FAILURE and plan.trigger.severity is FailureSeverity.HIGH
    assert plan.urgency is UrgencyLevel.HIGH and plan.evidence


def test_planning_is_deterministic_and_fast() -> None:
    state, signal = _state(no_response_channels=(SMS, SMS, SMS)), _signal(Pattern.CHANNEL_RESPONSE_FAILURE)
    assert _plan(state, signal) == _plan(state, signal)
    started = time.perf_counter()
    for _ in range(200):
        _plan(state, signal)
    assert (time.perf_counter() - started) / 200 < 0.1


@pytest.mark.parametrize("overrides", [
    {"wave_number": 0}, {"wave_number": 9}, {"wave_size": 0}, {"wave_size": MAX_WAVE_SIZE + 1},
    {"radius_step": 3}, {"remaining_candidates": -1}, {"fatigued_remaining": 99},
])
def test_malformed_state_is_rejected(overrides: dict) -> None:
    with pytest.raises(MalformedStateError):
        _plan(_state(**overrides), _signal())


def test_every_action_maps_to_the_persisted_vocabulary() -> None:
    assert set(PERSISTED_ACTION) == set(Action)
    assert all(isinstance(value, RecoveryActionType) for value in PERSISTED_ACTION.values())
    plan = _plan(_state(no_response_channels=(SMS, SMS)), _signal(Pattern.CHANNEL_RESPONSE_FAILURE))
    assert persisted_action(plan) is RecoveryActionType.ALTERNATIVE_DONOR


def test_apply_changes_only_what_the_plan_changes() -> None:
    plan = _plan(_state(no_response_channels=(SMS, SMS, SMS)), _signal(Pattern.CHANNEL_RESPONSE_FAILURE))
    before = WaveSettings(3, radius_step=1, bridge_priority=BridgePriority.BRIDGE_FIRST)
    after = healing.apply(plan, before)
    assert after.channel_override is CALL and after.wave_size == 4 and after.channel_switches == 1
    assert after.radius_step == 1 and after.bridge_priority is BridgePriority.BRIDGE_FIRST


# ---- cascade integration ---------------------------------------------------------------------------


@pytest.fixture
def cascade() -> Iterator[AdaptiveCascadeEngine]:
    with SessionLocal() as session:
        donor_states = DonorStateEngine(DonorStateRepository(session), DATASET_REFERENCE_TIME)
        twins = DigitalTwinService(DigitalTwinRepository(session), donor_states, DATASET_REFERENCE_TIME)
        matching = MatchingEngine(MatchingRepository(session), donor_states, twins)
        autopsy = FailureAutopsyEngine(FailureAutopsyRepository(session), matching, DATASET_REFERENCE_TIME, DATA_NOTICE)
        yield AdaptiveCascadeEngine(session, matching, autopsy)


def _find(cascade: AdaptiveCascadeEngine, predicate: Callable[[CascadeResult], bool], **kwargs: object) -> CascadeResult:
    for seed in range(1, 200):
        result = cascade.simulate(DEMO_REQUEST_CODE, seed=seed, **kwargs)  # type: ignore[arg-type]
        if predicate(result):
            return result
    raise AssertionError("no seed produced the scenario")


def test_seed_25_fails_heals_and_succeeds(client: TestClient) -> None:
    body = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25}).json()
    first, second = body["waves"][0], body["waves"][1]
    assert first["failure_autopsy"]["dominant_pattern"]["pattern_type"] == "CHANNEL_RESPONSE_FAILURE"
    plan = first["recovery_plan"]
    assert plan["source"] == "SIMULATED" and plan["trigger"]["pattern"] == "CHANNEL_RESPONSE_FAILURE"
    assert plan["primary_action"] == "INCREASE_WAVE_SIZE" and plan["changes"]["channel"] == "SIMULATED_CALL"
    assert second["wave_size"] == plan["changes"]["wave_size"] == first["wave_size"] + 1
    assert {c["channel"] for c in second["contacts"]} == {"SIMULATED_CALL"}
    assert body["outcome"] == "FULFILLED" and not body["requires_human_intervention"]
    assert second["recovery_plan"] is None  # fulfilled: nothing to recover


def test_a_switch_is_applied_to_the_next_wave(client: TestClient) -> None:
    """A natural SMS non-response run (REQ-00001, seed 2): wave 1 by SMS, wave 2 by call with one more donor."""
    body = client.get("/api/v1/requests/REQ-00001/cascade", params={"seed": 2}).json()
    first, second = body["waves"][0], body["waves"][1]
    plan = first["recovery_plan"]
    assert plan["primary_action"] == "SWITCH_CHANNEL" and plan["trigger"]["pattern"] == "CHANNEL_RESPONSE_FAILURE"
    assert {c["channel"] for c in first["contacts"]} == {"SIMULATED_SMS"}
    assert {c["channel"] for c in second["contacts"]} == {"SIMULATED_CALL"}
    assert second["wave_size"] == first["wave_size"] + 1 == plan["changes"]["wave_size"]
    assert first["healing"]["action"] == "ALTERNATIVE_DONOR" and second["applied_action"] == "ALTERNATIVE_DONOR"


def test_wave_two_excludes_everyone_already_contacted(cascade: AdaptiveCascadeEngine) -> None:
    for seed in range(1, 30):
        result = cascade.simulate(DEMO_REQUEST_CODE, seed=seed, response_stress="severe", max_waves=8)
        codes = [c.donor_code for w in result.waves for c in w.contacts]
        assert len(codes) == len(set(codes))
        for earlier, later in zip(result.waves, result.waves[1:]):
            assert later.eligible_candidates <= earlier.eligible_candidates - earlier.wave_size or later.radius_km != earlier.radius_km


def test_recovery_never_loops_forever(cascade: AdaptiveCascadeEngine) -> None:
    for seed in range(1, 40):
        result = cascade.simulate(DEMO_REQUEST_CODE, seed=seed, response_stress="severe", max_waves=8, wave_size=1)
        plans = [w.recovery_plan for w in result.waves if w.recovery_plan]
        automatic = [p for p in plans if not p.requires_human_intervention]
        assert len(automatic) <= MAX_RECOVERY_ATTEMPTS
        assert result.waves_used <= 8
        assert all(w.wave_size <= MAX_WAVE_SIZE for w in result.waves)
        assert sum(1 for w in result.waves if w.applied_action is RecoveryActionType.EXPANDED_SEARCH) <= MAX_RADIUS_STEP
        if result.outcome is CascadeOutcome.ESCALATED:
            assert result.requires_human_intervention and result.escalation_type is not None
            summary = result.escalation_summary
            assert summary is not None and summary.donors_contacted == result.total_contacts
            assert summary.recommended_human_action and summary.why_automation_stopped


def test_exhausted_cascade_hands_over_to_people(cascade: AdaptiveCascadeEngine) -> None:
    result = _find(cascade, lambda r: r.outcome is CascadeOutcome.ESCALATED, max_waves=2, response_stress="severe")
    assert result.requires_human_intervention is True
    assert result.escalation_type is EscalationType.HUMAN_COORDINATOR  # HIGH urgency
    assert result.waves[-1].recovery_plan.requires_human_intervention  # type: ignore[union-attr]
    assert result.escalation is not None and result.escalation.next_wave_size is None


def test_each_wave_plan_is_the_one_applied(cascade: AdaptiveCascadeEngine) -> None:
    result = cascade.simulate(DEMO_REQUEST_CODE, seed=25)
    for earlier, later in zip(result.waves, result.waves[1:]):
        assert earlier.recovery_plan is not None and earlier.healing is not None
        assert later.applied_action is earlier.healing.action is persisted_action(earlier.recovery_plan)


# ---- API --------------------------------------------------------------------------------------------


def test_self_healing_endpoint_reports_plans(client: TestClient) -> None:
    response = client.get(URL.format(DEMO_REQUEST_CODE), params={"seed": 25})
    assert response.status_code == 200
    body = response.json()
    assert body["request_code"] == DEMO_REQUEST_CODE and body["simulated_outcome"] == "FULFILLED"
    assert body["parameters"]["seed"] == 25 and body["requires_human_intervention"] is False
    plans = body["simulated_plans"]
    assert plans and plans[0]["wave_number"] == 1 and plans[0]["plan"]["source"] == "SIMULATED"
    assert body["automatic_recovery_attempts"] == len(plans)
    assert DATA_NOTICE == body["data_notice"]


def test_recorded_and_simulated_plans_stay_separate(client: TestClient) -> None:
    body = client.get(URL.format(DEMO_REQUEST_CODE), params={"seed": 25}).json()
    recorded = body["recorded_plan"]
    assert recorded is not None and recorded["source"] == FailureSource.RECORDED.value
    assert all(p["plan"]["source"] == "SIMULATED" for p in body["simulated_plans"])
    assert recorded["primary_action"] != "NO_CHANGE" and recorded["current_state"]["wave_number"] == 1


def test_self_healing_endpoint_is_deterministic_and_read_only(client: TestClient) -> None:
    before = client.get("/api/v1/system/dataset-stats").json()
    params = {"seed": 7, "response_stress": "severe", "max_waves": 6}
    first = client.get(URL.format(DEMO_REQUEST_CODE), params=params).json()
    assert first == client.get(URL.format(DEMO_REQUEST_CODE), params=params).json()
    assert client.get("/api/v1/system/dataset-stats").json() == before


def test_no_new_tables() -> None:
    tables = set(inspect(db_engine).get_table_names())
    assert "recovery_actions" in tables and len(tables) == 12  # 10 dataset tables + notifications (10A) + test_recipients (10E.1)


def test_unknown_request_returns_404(client: TestClient) -> None:
    response = client.get(URL.format("REQ-99999"))
    assert response.status_code == 404 and response.json()["detail"] == "Request REQ-99999 not found"


@pytest.mark.parametrize("params", [{"max_waves": 0}, {"wave_size": 9}, {"seed": -1}, {"response_stress": "x"}])
def test_invalid_parameters_are_rejected(client: TestClient, params: dict) -> None:
    assert client.get(URL.format(DEMO_REQUEST_CODE), params=params).status_code == 422
