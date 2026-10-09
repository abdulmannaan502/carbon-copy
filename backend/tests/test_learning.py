"""Learning Engine: evidence strength, numerators/denominators, source separation, sufficiency, causal
caution, donor-protection, configuration flag, read-only behaviour and API."""

import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.config import DATA_NOTICE, Settings, get_settings
from app.db.session import SessionLocal
from app.db.synthetic import DEMO_REQUEST_CODE
from app.main import create_app
from app.models import LearningEvent
from app.models.enums import (
    InteractionChannel,
    InteractionResponseStatus,
    InteractionType,
    LearningEventType,
    LearningSourceType,
    RecoveryActionType,
)
from app.repositories.learning_repository import InteractionRow
from app.schemas.failure_autopsy import FailureSource
from app.schemas.learning import EvidenceStrength, InsightCategory
from app.services.learning import (
    LEARNING_MAX_ADJUSTMENT_POINTS,
    MIN_SAMPLE,
    LearningEngine,
    contact_load_bands,
    strength_for,
    wilson,
)

pytestmark = pytest.mark.usefixtures("seeded_app_database")
SMS, CALL, APP = InteractionChannel.SIMULATED_SMS, InteractionChannel.SIMULATED_CALL, InteractionChannel.SIMULATED_APP
Status = InteractionResponseStatus
CAUSAL_WORDS = re.compile(r"\b(caused|causes|proves?|proven|guarantee[sd]?|because of)\b", re.IGNORECASE)


class FakeRepository:
    """Injected data, so tests do not depend on the generated dataset."""

    def __init__(self, **data: object) -> None:
        self.data = data

    def _get(self, key: str) -> list:
        return list(self.data.get(key, []))  # type: ignore[call-overload]

    def channel_counts(self):  # type: ignore[no-untyped-def]
        return self._get("channels")

    def interaction_window(self):  # type: ignore[no-untyped-def]
        return self.data.get("window", (None, None))

    def interactions(self):  # type: ignore[no-untyped-def]
        return self._get("interactions")

    def failure_category_counts(self):  # type: ignore[no-untyped-def]
        return self._get("categories")

    def failure_window(self):  # type: ignore[no-untyped-def]
        return (None, None)

    def failures(self):  # type: ignore[no-untyped-def]
        return self._get("failures")

    def recovery_outcomes(self):  # type: ignore[no-untyped-def]
        return self._get("recoveries")

    def recovery_status_counts(self):  # type: ignore[no-untyped-def]
        return self._get("recovery_status")

    def recovery_window(self):  # type: ignore[no-untyped-def]
        return (None, None)

    def attempts(self):  # type: ignore[no-untyped-def]
        return []

    def requests(self):  # type: ignore[no-untyped-def]
        return []


def _engine(repo: FakeRepository, enabled: bool = False) -> LearningEngine:
    return LearningEngine(repo, DATA_NOTICE, enabled)  # type: ignore[arg-type]


def _insight(report, insight_id: str):  # type: ignore[no-untyped-def]
    return next(i for i in report.insights if i.insight_id == insight_id)


# ---- statistics -----------------------------------------------------------------------------------


@pytest.mark.parametrize("sample,expected", [
    (0, EvidenceStrength.INSUFFICIENT_DATA), (MIN_SAMPLE - 1, EvidenceStrength.INSUFFICIENT_DATA),
    (MIN_SAMPLE, EvidenceStrength.LOW), (29, EvidenceStrength.LOW), (30, EvidenceStrength.MODERATE),
    (99, EvidenceStrength.MODERATE), (100, EvidenceStrength.HIGH), (10_000, EvidenceStrength.HIGH),
])
def test_evidence_strength_thresholds(sample: int, expected: EvidenceStrength) -> None:
    assert strength_for(sample)[0] is expected


def test_observational_evidence_is_capped_whatever_the_sample() -> None:
    label, reason = strength_for(100_000, EvidenceStrength.MODERATE)
    assert label is EvidenceStrength.MODERATE and "Capped at MODERATE" in reason


def test_wilson_interval_is_bounded_and_deterministic() -> None:
    assert wilson(0, 0) is None
    low, high = wilson(5, 10) or (0, 0)
    assert 0 <= low < 0.5 < high <= 1 and (low, high) == wilson(5, 10)
    assert wilson(0, 20) == (0.0, wilson(0, 20)[1]) and wilson(20, 20)[1] == 1.0  # type: ignore[index]


# ---- numerators, denominators, sample sizes ---------------------------------------------------------


def test_channel_numerators_denominators_and_pending_exclusion() -> None:
    repo = FakeRepository(channels=[
        (SMS, Status.ACCEPTED, 30), (SMS, Status.NO_RESPONSE, 50), (SMS, Status.DECLINED, 20), (SMS, Status.PENDING, 99),
        (CALL, Status.ACCEPTED, 60), (CALL, Status.NO_RESPONSE, 10), (CALL, Status.RESPONDED, 30),
    ])
    report = _engine(repo).recorded_report()
    response, accept = _insight(report, "CH-RESPONSE-RECORDED"), _insight(report, "CH-ACCEPT-RECORDED")
    sms, call = response.groups
    assert (sms.label, sms.numerator, sms.denominator) == ("SMS", 50, 100)  # pending excluded
    assert (call.label, call.numerator, call.denominator) == ("Call", 90, 100)
    assert response.numerator == 140 and response.denominator == 200 and response.sample_size == 200
    assert [(g.numerator, g.denominator) for g in accept.groups] == [(30, 100), (60, 100)]
    assert response.strength is EvidenceStrength.HIGH and "Call was higher than SMS" in response.finding


def test_numbers_match_independent_sql_on_the_dataset(client: TestClient) -> None:
    body = client.get("/api/v1/learning/report").json()
    with SessionLocal() as session:
        resolved = session.scalar(text(
            "select count(*) from donor_interactions where interaction_type='DONATION_REQUEST' and response_status != 'PENDING'"))
        accepted = session.scalar(text(
            "select count(*) from donor_interactions where interaction_type='DONATION_REQUEST' and response_status = 'ACCEPTED'"))
        events = session.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.source_type == LearningSourceType.RECOVERY_ACTION))
    insights = {i["insight_id"]: i for i in body["insights"]}
    assert insights["CH-ACCEPT-RECORDED"]["numerator"] == accepted
    assert insights["CH-ACCEPT-RECORDED"]["denominator"] == resolved == insights["CH-RESPONSE-RECORDED"]["denominator"]
    coverage = insights["RE-COVERAGE-RECORDED"]
    assert coverage["numerator"] == events and coverage["denominator"] == 266


# ---- zero records, small samples, missing evidence -----------------------------------------------------


def test_zero_records_gives_insufficient_data_everywhere() -> None:
    report = _engine(FakeRepository()).recorded_report()
    assert report.insights and all(i.strength is EvidenceStrength.INSUFFICIENT_DATA for i in report.insights
                                   if i.category is not InsightCategory.COORDINATION_BOTTLENECK or i.sample_size == 0)
    assert all(s.status is EvidenceStrength.INSUFFICIENT_DATA for s in report.sufficiency)
    assert all(i.numerator in (None, 0) for i in report.insights)
    assert report.recommendations and all("collect more data" in r.text.lower() for r in report.recommendations)


def test_small_samples_are_flagged_not_concluded() -> None:
    tiny = _engine(FakeRepository(channels=[(SMS, Status.ACCEPTED, 4), (SMS, Status.NO_RESPONSE, 3),
                                            (CALL, Status.ACCEPTED, 6)])).recorded_report()
    response = _insight(tiny, "CH-RESPONSE-RECORDED")
    assert response.strength is EvidenceStrength.INSUFFICIENT_DATA and "too small" in response.finding
    assert response.consideration == "Collect more data before relying on this."
    low = _engine(FakeRepository(channels=[(SMS, Status.ACCEPTED, 15), (CALL, Status.ACCEPTED, 12)])).recorded_report()
    assert _insight(low, "CH-RESPONSE-RECORDED").strength is EvidenceStrength.LOW


def test_groups_below_the_minimum_are_not_compared() -> None:
    repo = FakeRepository(channels=[(SMS, Status.ACCEPTED, 90), (SMS, Status.NO_RESPONSE, 10), (APP, Status.ACCEPTED, 3), (CALL, Status.NO_RESPONSE, 4)])
    insight = _insight(_engine(repo).recorded_report(), "CH-RESPONSE-RECORDED")
    assert "No channel clearly differs" in insight.finding  # only SMS is eligible


def test_missing_recovery_outcome_evidence_is_reported_not_guessed() -> None:
    repo = FakeRepository(recoveries=[(RecoveryActionType.NEXT_DONOR, None, 40), (RecoveryActionType.ALTERNATIVE_DONOR, None, 30)])
    report = _engine(repo).recorded_report()
    effect, coverage = _insight(report, "RE-EFFECT-RECORDED"), _insight(report, "RE-COVERAGE-RECORDED")
    assert effect.strength is EvidenceStrength.INSUFFICIENT_DATA and effect.groups == []
    assert (coverage.numerator, coverage.denominator) == (0, 70)
    assert "0 of 70" in coverage.finding and "70 have none" in coverage.finding
    assert not [r for r in report.recommendations if "recovery options" in r.text]


def test_no_recovery_actions_at_all() -> None:
    effect = _insight(_engine(FakeRepository()).recorded_report(), "RE-EFFECT-RECORDED")
    assert effect.strength is EvidenceStrength.INSUFFICIENT_DATA and effect.sample_size == 0


# ---- causal caution -------------------------------------------------------------------------------------


def _big_recovery_repo() -> FakeRepository:
    return FakeRepository(recoveries=[
        (RecoveryActionType.EXPANDED_SEARCH, LearningEventType.RECOVERY_SUCCESS, 900),
        (RecoveryActionType.EXPANDED_SEARCH, LearningEventType.RECOVERY_FAILURE, 100),
        (RecoveryActionType.NEXT_DONOR, LearningEventType.RECOVERY_SUCCESS, 300),
        (RecoveryActionType.NEXT_DONOR, LearningEventType.RECOVERY_FAILURE, 700),
    ])


def test_recovery_findings_are_associations_never_causal_claims() -> None:
    report = _engine(_big_recovery_repo()).recorded_report()
    effect = _insight(report, "RE-EFFECT-RECORDED")
    assert effect.strength is EvidenceStrength.MODERATE  # capped despite 2000 observations
    assert "association" in effect.finding and not CAUSAL_WORDS.search(effect.finding + effect.consideration)
    assert any("not that the action caused it" in text for text in effect.limitations)
    for recommendation in report.recommendations:
        assert not CAUSAL_WORDS.search(recommendation.text) and recommendation.implemented is False


def test_real_report_has_no_causal_language_and_states_synthetic_limits(client: TestClient) -> None:
    body = client.get("/api/v1/learning/report").json()
    for insight in body["insights"]:
        assert not CAUSAL_WORDS.search(insight["finding"] + " " + insight["consideration"])
        assert any("synthetic" in text.lower() for text in insight["limitations"])
        if insight["category"] in ("RECOVERY_EFFECTIVENESS", "DONOR_FATIGUE") or insight["insight_id"].startswith(("FP-RESPONSE", "FP-CHANNEL", "FP-BRIDGE")):
            assert insight["strength"] != "HIGH"
    assert body["data_notice"] == DATA_NOTICE and "not evidence of real-world" in body["notice"]


# ---- donor fatigue respects protections -------------------------------------------------------------


def _row(donor: int, day: float, status: Status, kind: InteractionType = InteractionType.DONATION_REQUEST) -> InteractionRow:
    start = datetime(2026, 1, 1)
    return InteractionRow(donor, CALL, kind, start + timedelta(days=day), status, None)


def test_contact_load_counts_only_the_window_and_excludes_pending() -> None:
    rows = [
        _row(1, 0, Status.NO_RESPONSE), _row(1, 5, Status.ACCEPTED), _row(1, 10, Status.PENDING),
        _row(1, 45, Status.RESPONDED),  # earlier contacts are > 30 days old
        _row(2, 0, Status.ACCEPTED),
    ]
    bands = contact_load_bands(rows)
    assert bands["0 prior contacts"] == [2, 3]   # donor 1 @0 (no reply), donor 1 @45, donor 2 @0
    assert bands["1 prior contact"] == [1, 1]    # donor 1 @5
    assert bands["2–3 prior contacts"] == [0, 0]  # the pending row at day 10 is excluded


def test_fatigue_insight_is_aggregate_only_and_keeps_protections() -> None:
    rows = [_row(d, i * 1.0, Status.RESPONDED if (d + i) % 3 else Status.NO_RESPONSE) for d in range(1, 40) for i in range(6)]
    report = _engine(FakeRepository(interactions=rows)).recorded_report()
    fatigue = _insight(report, "DF-CONTACT-LOAD-RECORDED")
    assert fatigue.strength in (EvidenceStrength.MODERATE, EvidenceStrength.LOW)  # observational cap
    text_blob = " ".join([fatigue.finding, fatigue.reason, fatigue.consideration, *fatigue.limitations])
    assert not re.search(r"DON-\d+", text_blob) and "unchanged" in text_blob + fatigue.consideration
    assert "increase contact" not in text_blob.lower() or "do not" in text_blob.lower()
    recommendation = next(r for r in report.recommendations if r.insight_ids == [fatigue.insight_id])
    assert "never relaxes" in recommendation.text and recommendation.adjustment is None


def test_higher_response_among_heavily_contacted_donors_is_not_read_as_a_reason_to_contact_more() -> None:
    quiet = [_row(d, 0, Status.NO_RESPONSE if d % 3 else Status.RESPONDED) for d in range(100, 400)]
    busy = [_row(d, i, Status.RESPONDED if i else Status.NO_RESPONSE) for d in range(1, 120) for i in range(0, 6)]
    rows = sorted(quiet + busy, key=lambda r: (r.donor_id, r.initiated_at))
    fatigue = _insight(_engine(FakeRepository(interactions=rows)).recorded_report(), "DF-CONTACT-LOAD-RECORDED")
    assert "Do not use this to increase contact frequency" in fatigue.consideration


def test_report_never_exposes_donor_identifiers(client: TestClient) -> None:
    blob = client.get("/api/v1/learning/report").text
    sim = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/learning", params={"seed": 25}).text
    assert not re.search(r"DON-\d{5}", blob + sim) and "phone" not in (blob + sim).lower()


# ---- configuration flag ---------------------------------------------------------------------------------


def _strong_channel_repo() -> FakeRepository:
    return FakeRepository(channels=[(SMS, Status.ACCEPTED, 40), (SMS, Status.NO_RESPONSE, 160),
                                    (CALL, Status.ACCEPTED, 150), (CALL, Status.NO_RESPONSE, 50)])


def test_adjustments_are_disabled_by_default() -> None:
    report = _engine(_strong_channel_repo()).recorded_report()
    assert report.adjustments_enabled is False and report.recommendations
    assert all(r.adjustment is None and r.implemented is False for r in report.recommendations)
    assert "does not change matching" in report.operational_effect


def test_enabled_adjustments_are_bounded_and_still_only_recommendations() -> None:
    report = _engine(_strong_channel_repo(), enabled=True).recorded_report()
    adjusted = [r for r in report.recommendations if r.adjustment is not None]
    assert adjusted and report.adjustments_enabled is True
    for recommendation in adjusted:
        assert 0 < recommendation.adjustment.value <= recommendation.adjustment.bound == LEARNING_MAX_ADJUSTMENT_POINTS  # type: ignore[union-attr]
        assert recommendation.implemented is False
    weak = _engine(FakeRepository(channels=[(SMS, Status.ACCEPTED, 8), (CALL, Status.NO_RESPONSE, 8)]), enabled=True).recorded_report()
    assert all(r.adjustment is None for r in weak.recommendations)  # insufficient evidence never adjusts


def test_flag_does_not_change_cascade_or_matching_behaviour(client: TestClient) -> None:
    def cascade() -> dict:
        return client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25}).json()

    before = cascade()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(learning_adjustments_enabled=True)
    with TestClient(app) as flagged:
        report = flagged.get("/api/v1/learning/report").json()
        after = flagged.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", params={"seed": 25}).json()
    assert report["adjustments_enabled"] is True and after == before


# ---- sources stay separate -----------------------------------------------------------------------------


def test_recorded_and_simulated_reports_never_mix(client: TestClient) -> None:
    recorded = client.get("/api/v1/learning/report").json()
    simulated = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/learning", params={"seed": 25, "runs": 4}).json()
    assert recorded["source"] == "RECORDED" and simulated["source"] == "SIMULATED"
    assert {i["source"] for i in recorded["insights"]} == {"RECORDED"}
    assert {i["source"] for i in simulated["insights"]} == {"SIMULATED"}
    assert all(i["insight_id"].endswith("-RECORDED") for i in recorded["insights"])
    assert all(i["insight_id"].endswith("-SIMULATED") for i in simulated["insights"])
    assert "RECORDED" in recorded["provenance"] and "SIMULATED" in simulated["provenance"]
    assert "seeds 25-28" in simulated["population"] and "interactions" in recorded["population"]
    rec_n = {i["insight_id"][:-9]: i["sample_size"] for i in recorded["insights"]}
    sim_n = {i["insight_id"][:-10]: i["sample_size"] for i in simulated["insights"]}
    assert rec_n["CH-RESPONSE"] != sim_n["CH-RESPONSE"]


def test_simulated_report_needs_no_recorded_data() -> None:
    from app.core.clock import DATASET_REFERENCE_TIME  # noqa: F401

    report = LearningEngine(None, DATA_NOTICE).simulated_report([], [])
    assert report.source is FailureSource.SIMULATED and report.insights
    assert all(i.strength is EvidenceStrength.INSUFFICIENT_DATA for i in report.insights)


def test_simulated_fatigue_is_explicitly_not_assessable(client: TestClient) -> None:
    body = client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/learning", params={"seed": 25}).json()
    fatigue = next(i for i in body["insights"] if i["category"] == "DONOR_FATIGUE")
    assert fatigue["strength"] == "INSUFFICIENT_DATA" and "Not assessable" in fatigue["finding"]


def test_pool_patterns_are_not_invented_for_recorded_data(client: TestClient) -> None:
    body = client.get("/api/v1/learning/report").json()
    ids = " ".join(i["insight_id"] for i in body["insights"])
    assert "CANDIDATE_POOL_EXHAUSTION" not in ids and "LOCAL_POOL_FAILURE" not in ids
    assert any("cannot be assessed historically" in s["reason"] and s["status"] == "INSUFFICIENT_DATA" for s in body["sufficiency"])


# ---- determinism, windows, read-only, API --------------------------------------------------------------


def test_reports_are_deterministic(client: TestClient) -> None:
    assert client.get("/api/v1/learning/report").json() == client.get("/api/v1/learning/report").json()
    params = {"seed": 7, "runs": 3, "response_stress": "severe"}
    url = f"/api/v1/requests/{DEMO_REQUEST_CODE}/learning"
    assert client.get(url, params=params).json() == client.get(url, params=params).json()


def test_time_windows_come_from_the_data_not_the_clock(client: TestClient) -> None:
    body = client.get("/api/v1/learning/report").json()
    assert body["time_window"]["start"].startswith("2026-06-20")
    for insight in body["insights"]:
        window = insight["time_window"]
        if window["start"] and window["end"]:
            assert window["start"] <= window["end"] <= "2026-10-09"


def test_report_generation_does_not_mutate_the_database(client: TestClient) -> None:
    with SessionLocal() as session:
        tables = [row[0] for row in session.execute(text("select name from sqlite_master where type='table'"))]
        counts = lambda: {t: session.scalar(text(f'select count(*) from "{t}"')) for t in tables}  # noqa: E731
        before = counts()
        client.get("/api/v1/learning/report")
        client.get(f"/api/v1/requests/{DEMO_REQUEST_CODE}/learning", params={"runs": 5, "response_stress": "severe"})
        session.rollback()
        assert counts() == before and len(tables) == 12  # 10 dataset tables + notifications (10A) + test_recipients (10E.1)


def test_recorded_report_endpoint_shape(client: TestClient) -> None:
    body = client.get("/api/v1/learning/report").json()
    assert {i["category"] for i in body["insights"]} == {c.value for c in InsightCategory}
    for key in ("thresholds", "sufficiency", "recommendations", "population", "provenance", "operational_effect"):
        assert body[key]
    assert body["thresholds"]["min_sample"] == MIN_SAMPLE
    first = body["insights"][0]
    for key in ("insight_id", "source", "provenance", "finding", "numerator", "denominator", "sample_size",
                "time_window", "strength", "strength_reason", "reason", "limitations", "consideration"):
        assert key in first


def test_simulation_endpoint_parameters_and_errors(client: TestClient) -> None:
    url = f"/api/v1/requests/{DEMO_REQUEST_CODE}/learning"
    assert client.get(url, params={"seed": 25, "runs": 2}).status_code == 200
    assert client.get("/api/v1/requests/REQ-99999/learning").status_code == 404
    for params in ({"runs": 0}, {"runs": 11}, {"seed": -1}, {"response_stress": "x"}, {"max_waves": 9}):
        assert client.get(url, params=params).status_code == 422
