"""Failure Autopsy Engine: taxonomy, pattern detection, severity/confidence/recommendation rules,
evidence, recorded vs simulated sources, cascade integration and the read-only API."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.clock import DATASET_REFERENCE_TIME
from app.db.synthetic import DEMO_DONOR_CODES, DEMO_REQUEST_CODE
from app.models.enums import FailureCategory, FailureSeverity, InteractionChannel, UrgencyLevel
from app.schemas.failure_autopsy import FailurePatternType, FailureSource, RecoveryRecommendation
from app.services.failure_autopsy import (
    GATE_FAILURE_TYPES,
    INDIVIDUAL_RECOMMENDATION,
    PATTERN_RECOMMENDATION,
    FailureObservation,
    PatternContext,
    _bump_for_urgency,
    analyze_individual,
    build_autopsy,
    detect_patterns,
)

pytestmark = pytest.mark.usefixtures("seeded_app_database")
AUTOPSY_URL = "/api/v1/requests/{}/failures/autopsy"
SINGLE_URL = "/api/v1/requests/{}/failures/{}/autopsy"
NOW = DATASET_REFERENCE_TIME


def obs(
    code: str = "DON-00001",
    ftype: FailureCategory = FailureCategory.NO_RESPONSE,
    channel: InteractionChannel | None = InteractionChannel.SIMULATED_SMS,
    bridge: bool = False,
    window_expired: bool = True,
) -> FailureObservation:
    return FailureObservation(
        donor_code=code, display_name=f"Donor {code}", blood_group="B-", failure_type=ftype, channel=channel,
        detected_at=NOW, bridge_group_member=bridge, window_expired=window_expired, reference=f"REF-{code}",
    )


def ctx(
    remaining_in_radius: int = 30, filtered_outside_radius: int = 10, radius_known: bool = True,
    urgency: UrgencyLevel = UrgencyLevel.MODERATE,
) -> PatternContext:
    return PatternContext(remaining_in_radius, filtered_outside_radius, radius_known, urgency)


# ---- individual failure taxonomy (every FailureCategory) ------------------------------------------


@pytest.mark.parametrize(
    ("failure_type", "window_expired"),
    [
        (FailureCategory.NO_RESPONSE, True),
        (FailureCategory.DECLINED, False),
        (FailureCategory.UNAVAILABLE, False),
        (FailureCategory.RECENT_DONATION, False),
        (FailureCategory.DEFERRAL, False),
        (FailureCategory.CONTACT_FAILURE, False),
        (FailureCategory.ALREADY_CONTACTED, False),
        (FailureCategory.CASCADE_EXHAUSTED, False),
        (FailureCategory.FATIGUE, False),
        (FailureCategory.OTHER, False),
    ],
)
def test_every_failure_category_produces_a_valid_individual_autopsy(
    failure_type: FailureCategory, window_expired: bool
) -> None:
    result = analyze_individual(
        obs(ftype=failure_type, window_expired=window_expired), DEMO_REQUEST_CODE, FailureSource.RECORDED, pattern=None
    )
    assert result.failure_type is failure_type
    assert result.affected_donor == "DON-00001" and result.affected_request == DEMO_REQUEST_CODE
    assert 0 <= result.rule_confidence <= 1
    assert result.recommended_next_action is INDIVIDUAL_RECOMMENDATION[failure_type]
    assert result.evidence  # never empty: at least the outcome is recorded
    assert all(e.description for e in result.evidence)  # no invented/blank evidence


def test_cascade_exhausted_is_always_critical_and_not_donor_specific() -> None:
    result = analyze_individual(obs(ftype=FailureCategory.CASCADE_EXHAUSTED), "REQ", FailureSource.RECORDED, pattern=None)
    assert result.severity is FailureSeverity.CRITICAL
    # Pool exhaustion is a systemic/network condition, not caused by this one donor.
    autopsy = build_autopsy("REQ", FailureSource.RECORDED, [obs(ftype=FailureCategory.CASCADE_EXHAUSTED)], ctx(), "notice", NOW)
    assert autopsy.individual_failures[0].network_related is False  # isolated case: no pattern evidence to attribute it to


def test_isolated_decline_is_low_severity_and_other_types_default_moderate() -> None:
    decline = analyze_individual(obs(ftype=FailureCategory.DECLINED), "REQ", FailureSource.RECORDED, None)
    unavailable = analyze_individual(obs(ftype=FailureCategory.UNAVAILABLE), "REQ", FailureSource.RECORDED, None)
    assert decline.severity is FailureSeverity.LOW
    assert unavailable.severity is FailureSeverity.MEDIUM  # MODERATE, named MEDIUM in the existing FailureSeverity enum


def test_evidence_cites_the_real_recorded_reason_not_an_invented_one() -> None:
    o = FailureObservation(
        donor_code="DON-1", display_name="D", blood_group="B-", failure_type=FailureCategory.DECLINED,
        channel=InteractionChannel.SIMULATED_CALL, detected_at=NOW, bridge_group_member=False, window_expired=False,
        reference="FLR-1", detail="Travel distance to the hospital is too long",
    )
    result = analyze_individual(o, "REQ", FailureSource.RECORDED, None)
    descriptions = [e.description for e in result.evidence]
    assert "Travel distance to the hospital is too long" in descriptions
    assert all(e.reference == "FLR-1" for e in result.evidence)


# ---- pattern taxonomy (all 8 pattern types) -------------------------------------------------------


def test_individual_donor_failure_marker_for_a_single_failure() -> None:
    autopsy = build_autopsy(DEMO_REQUEST_CODE, FailureSource.RECORDED, [obs()], ctx(), "notice", NOW)
    assert autopsy.pattern_detected is False
    assert autopsy.patterns == []
    assert autopsy.dominant_pattern is not None
    assert autopsy.dominant_pattern.pattern_type is FailurePatternType.INDIVIDUAL_DONOR_FAILURE
    assert autopsy.dominant_pattern.supporting_failures == 1


def test_channel_response_failure_when_same_channel_no_response() -> None:
    observations = [obs("DON-1", channel=InteractionChannel.SIMULATED_CALL), obs("DON-2", channel=InteractionChannel.SIMULATED_CALL)]
    (pattern,) = detect_patterns(observations, ctx())
    assert pattern.pattern_type is FailurePatternType.CHANNEL_RESPONSE_FAILURE
    assert pattern.affected_channel is InteractionChannel.SIMULATED_CALL
    assert pattern.channel_specific is True
    assert pattern.recommended_action is RecoveryRecommendation.SWITCH_CHANNEL
    assert pattern.recommended_action is PATTERN_RECOMMENDATION[FailurePatternType.CHANNEL_RESPONSE_FAILURE]


def test_response_window_failure_when_no_response_across_channels() -> None:
    observations = [obs("DON-1", channel=InteractionChannel.SIMULATED_CALL), obs("DON-2", channel=InteractionChannel.SIMULATED_SMS)]
    (pattern,) = detect_patterns(observations, ctx())
    assert pattern.pattern_type is FailurePatternType.RESPONSE_WINDOW_FAILURE
    assert pattern.timing_related is True
    assert pattern.recommended_action is RecoveryRecommendation.INCREASE_WAVE_SIZE


def test_local_pool_failure_when_few_remain_locally_but_region_has_more() -> None:
    observations = [obs("DON-1", ftype=FailureCategory.DECLINED), obs("DON-2", ftype=FailureCategory.UNAVAILABLE)]
    context = ctx(remaining_in_radius=1, filtered_outside_radius=25, radius_known=True)
    (pattern,) = detect_patterns(observations, context)
    assert pattern.pattern_type is FailurePatternType.LOCAL_POOL_FAILURE
    assert pattern.network_related is True
    assert pattern.recommended_action is RecoveryRecommendation.EXPAND_SEARCH_RADIUS


def test_bridge_group_failure_when_majority_are_bridge_members() -> None:
    # UNAVAILABLE/DECLINED (not NO_RESPONSE), so no channel/window pattern also fires:
    # this isolates BRIDGE_GROUP_FAILURE as the only pattern the evidence supports.
    observations = [
        obs("DON-1", ftype=FailureCategory.UNAVAILABLE, bridge=True),
        obs("DON-2", ftype=FailureCategory.UNAVAILABLE, bridge=True),
        obs("DON-3", ftype=FailureCategory.DECLINED, bridge=False),
    ]
    (pattern,) = detect_patterns(observations, ctx())
    assert pattern.pattern_type is FailurePatternType.BRIDGE_GROUP_FAILURE
    assert set(pattern.affected_donors) == {"DON-1", "DON-2"}
    assert pattern.recommended_action is RecoveryRecommendation.TRY_BRIDGE_GROUP


def test_candidate_pool_exhaustion_when_nothing_remains_anywhere() -> None:
    context = ctx(remaining_in_radius=0, filtered_outside_radius=0, radius_known=False)
    (pattern,) = detect_patterns([obs(ftype=FailureCategory.UNAVAILABLE)], context)
    assert pattern.pattern_type is FailurePatternType.CANDIDATE_POOL_EXHAUSTION
    assert pattern.severity is FailureSeverity.CRITICAL
    assert pattern.recommended_action is RecoveryRecommendation.HUMAN_COORDINATOR
    # A single failure is still enough: exhaustion is about what's left, not how many just failed.
    assert pattern.supporting_failures == 1


def test_candidate_pool_exhaustion_takes_priority_over_local_pool() -> None:
    context = ctx(remaining_in_radius=0, filtered_outside_radius=0, radius_known=True)
    patterns = detect_patterns([obs()], context)
    assert [p.pattern_type for p in patterns] == [FailurePatternType.CANDIDATE_POOL_EXHAUSTION]


def test_recent_donation_pool_when_majority_are_gate_exclusions() -> None:
    observations = [obs("DON-1", ftype=FailureCategory.RECENT_DONATION), obs("DON-2", ftype=FailureCategory.DEFERRAL)]
    assert all(o.failure_type in GATE_FAILURE_TYPES for o in observations)
    (pattern,) = detect_patterns(observations, ctx())
    assert pattern.pattern_type is FailurePatternType.RECENT_DONATION_POOL
    assert pattern.recommended_action is RecoveryRecommendation.RE_RUN_MATCHING


def test_unknown_pattern_when_causes_are_mixed_and_evidence_is_insufficient() -> None:
    observations = [obs("DON-1", ftype=FailureCategory.DECLINED), obs("DON-2", ftype=FailureCategory.UNAVAILABLE)]
    assert detect_patterns(observations, ctx()) == []  # no rule matches: never forces a pattern
    autopsy = build_autopsy("REQ", FailureSource.RECORDED, observations, ctx(), "notice", NOW)
    assert autopsy.pattern_detected is False
    assert autopsy.dominant_pattern.pattern_type is FailurePatternType.UNKNOWN_PATTERN


def test_zero_failures_never_fabricates_a_pattern_even_with_zero_context() -> None:
    """Regression: a placeholder "nothing computed" context of (0 remaining, 0 outside) must not be
    misread as CANDIDATE_POOL_EXHAUSTION when there are no failures to explain in the first place."""
    assert detect_patterns([], ctx(remaining_in_radius=0, filtered_outside_radius=0, radius_known=True)) == []
    autopsy = build_autopsy("REQ", FailureSource.RECORDED, [], ctx(remaining_in_radius=0, filtered_outside_radius=0), "notice", NOW)
    assert autopsy.patterns == [] and autopsy.dominant_pattern is None and autopsy.pattern_detected is False


def test_no_false_pattern_below_the_minimum_failure_count() -> None:
    # A single NO_RESPONSE must never be read as a channel/window pattern.
    assert detect_patterns([obs("DON-1", channel=InteractionChannel.SIMULATED_CALL)], ctx()) == []
    # A single bridge-group failure must never be read as a bridge-group pattern.
    assert detect_patterns([obs("DON-1", bridge=True), obs("DON-2", ftype=FailureCategory.DECLINED)], ctx()) == []


def test_dominant_pattern_always_has_a_pattern_type_when_failures_exist() -> None:
    for observations in ([], [obs()], [obs("DON-1"), obs("DON-2", ftype=FailureCategory.DECLINED)]):
        autopsy = build_autopsy("REQ", FailureSource.RECORDED, observations, ctx(), "notice", NOW)
        if observations:
            assert autopsy.dominant_pattern is not None
            assert isinstance(autopsy.dominant_pattern.pattern_type, FailurePatternType)
        else:
            assert autopsy.dominant_pattern is None  # nothing to report when there are no failures


# ---- severity, confidence, recommendation rules ---------------------------------------------------


def test_urgency_bumps_severity_by_exactly_one_level() -> None:
    assert _bump_for_urgency(FailureSeverity.LOW, UrgencyLevel.CRITICAL) is FailureSeverity.MEDIUM
    assert _bump_for_urgency(FailureSeverity.HIGH, UrgencyLevel.CRITICAL) is FailureSeverity.CRITICAL
    assert _bump_for_urgency(FailureSeverity.CRITICAL, UrgencyLevel.CRITICAL) is FailureSeverity.CRITICAL  # capped
    assert _bump_for_urgency(FailureSeverity.LOW, UrgencyLevel.HIGH) is FailureSeverity.LOW  # only CRITICAL bumps


def test_pattern_confidence_is_deterministic_and_grows_with_evidence_then_caps() -> None:
    few = detect_patterns([obs("DON-1", channel=InteractionChannel.SIMULATED_CALL), obs("DON-2", channel=InteractionChannel.SIMULATED_CALL)], ctx())[0]
    many = detect_patterns(
        [obs(f"DON-{i}", channel=InteractionChannel.SIMULATED_CALL) for i in range(10)], ctx()
    )[0]
    assert few.rule_confidence == detect_patterns(
        [obs("DON-1", channel=InteractionChannel.SIMULATED_CALL), obs("DON-2", channel=InteractionChannel.SIMULATED_CALL)], ctx()
    )[0].rule_confidence  # same inputs -> same confidence
    assert few.rule_confidence < many.rule_confidence <= 0.97  # grows, but never claims near-certainty


def test_recommendation_tables_cover_every_pattern_and_failure_type() -> None:
    for pattern_type in FailurePatternType:
        if pattern_type in (FailurePatternType.INDIVIDUAL_DONOR_FAILURE, FailurePatternType.UNKNOWN_PATTERN):
            continue
        assert pattern_type in PATTERN_RECOMMENDATION
    for failure_type in FailureCategory:
        assert failure_type in INDIVIDUAL_RECOMMENDATION


# ---- recorded vs simulated separation --------------------------------------------------------------


def test_recorded_autopsy_is_source_recorded(client: TestClient) -> None:
    body = client.get(AUTOPSY_URL.format(DEMO_REQUEST_CODE)).json()
    assert body["source"] == "RECORDED"
    assert all(f["source"] == "RECORDED" for f in body["individual_failures"])


def test_demo_recorded_failure_is_don_00001_no_response(client: TestClient) -> None:
    body = client.get(AUTOPSY_URL.format(DEMO_REQUEST_CODE)).json()
    assert body["failures_analyzed"] == 1
    (failure,) = body["individual_failures"]
    assert failure["affected_donor"] == DEMO_DONOR_CODES[0]
    assert failure["failure_type"] == "NO_RESPONSE"
    assert failure["affected_channel"] == "SIMULATED_SMS"
    assert body["dominant_pattern"]["pattern_type"] == "INDIVIDUAL_DONOR_FAILURE"
    assert body["pattern_detected"] is False


def test_single_recorded_failure_endpoint(client: TestClient) -> None:
    autopsy = client.get(AUTOPSY_URL.format(DEMO_REQUEST_CODE)).json()
    failure_code = autopsy["individual_failures"][0]["reference"]
    body = client.get(SINGLE_URL.format(DEMO_REQUEST_CODE, failure_code)).json()
    assert body["source"] == "RECORDED"
    assert body["affected_donor"] == DEMO_DONOR_CODES[0]
    assert body["reference"] == failure_code


def test_simulated_cascade_wave_autopsy_is_source_simulated(client: TestClient) -> None:
    body = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25}).json()
    analysed_waves = [w for w in body["waves"] if w["failure_autopsy"] is not None]
    assert analysed_waves
    for wave in analysed_waves:
        assert wave["failure_autopsy"]["source"] == "SIMULATED"
        assert all(f["source"] == "SIMULATED" for f in wave["failure_autopsy"]["individual_failures"])


# ---- cascade integration: autopsy recommends, self-healing decides, seed=25 -----------------------


def test_seed_25_produces_the_documented_channel_response_failure_story(client: TestClient) -> None:
    body = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25}).json()
    assert body["outcome"] == "FULFILLED"
    assert body["waves_used"] == 2

    wave1 = body["waves"][0]
    autopsy = wave1["failure_autopsy"]
    assert autopsy["failures_analyzed"] == 3
    assert autopsy["pattern_detected"] is True
    assert autopsy["dominant_pattern"]["pattern_type"] == "CHANNEL_RESPONSE_FAILURE"
    assert autopsy["recommended_action"] == "SWITCH_CHANNEL"

    # Self-Healing is a separate decision, not overwritten by the autopsy recommendation.
    healing = wave1["healing"]
    assert healing["action"] == "ALTERNATIVE_DONOR"
    assert healing is not autopsy  # distinct structures: autopsy recommends, self-healing decides
    assert wave1["autopsy"] is not None  # the original lightweight autopsy summary still exists, unchanged


def test_failure_autopsy_never_sets_healing_fields(client: TestClient) -> None:
    """Autopsy must only recommend; it must never itself choose next_wave_size/channel_override/etc."""
    body = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25}).json()
    for wave in body["waves"]:
        if wave["failure_autopsy"] is None:
            continue
        assert set(wave["failure_autopsy"].keys()) & {"next_wave_size", "channel_override", "radius_step"} == set()


# ---- determinism, errors, no mutation --------------------------------------------------------------


def test_recorded_autopsy_is_deterministic(client: TestClient) -> None:
    first = client.get(AUTOPSY_URL.format(DEMO_REQUEST_CODE)).json()
    second = client.get(AUTOPSY_URL.format(DEMO_REQUEST_CODE)).json()
    assert first == second
    assert datetime.fromisoformat(first["analysis_time"]) == NOW  # injected clock, not wall time


def test_simulated_autopsy_is_deterministic_across_repeated_runs(client: TestClient) -> None:
    first = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25}).json()
    second = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25}).json()
    assert first == second


def test_autopsy_apis_mutate_nothing(client: TestClient) -> None:
    before = client.get("/api/v1/system/dataset-stats").json()
    client.get(AUTOPSY_URL.format(DEMO_REQUEST_CODE))
    autopsy = client.get(AUTOPSY_URL.format(DEMO_REQUEST_CODE)).json()
    client.get(SINGLE_URL.format(DEMO_REQUEST_CODE, autopsy["individual_failures"][0]["reference"]))
    client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25})
    after = client.get("/api/v1/system/dataset-stats").json()
    assert before == after


def test_unknown_request_returns_404(client: TestClient) -> None:
    response = client.get(AUTOPSY_URL.format("REQ-99999"))
    assert response.status_code == 404
    assert response.json()["detail"] == "Request REQ-99999 not found"

    response2 = client.get(SINGLE_URL.format("REQ-99999", "FLR-00001"))
    assert response2.status_code == 404


def test_unknown_failure_code_returns_404(client: TestClient) -> None:
    response = client.get(SINGLE_URL.format(DEMO_REQUEST_CODE, "FLR-99999"))
    assert response.status_code == 404
    assert response.json()["detail"] == "Failure FLR-99999 not found"


def test_request_with_no_recorded_failures_returns_an_empty_autopsy(client: TestClient) -> None:
    # A FULFILLED first-attempt-success request exists in the synthetic dataset; find one via the API.
    requests = client.get("/api/v1/requests", params={"page_size": 100}).json()["items"]
    candidate = next(
        r["request_code"] for r in requests
        if client.get(AUTOPSY_URL.format(r["request_code"])).json()["failures_analyzed"] == 0
    )
    body = client.get(AUTOPSY_URL.format(candidate)).json()
    assert body["individual_failures"] == [] and body["patterns"] == []
    assert body["dominant_pattern"] is None
    assert body["recommended_action"] is None
    assert "no" in body["explanation"].lower()
