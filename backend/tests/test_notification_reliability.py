"""Phase 10D: request search, event-coverage audit, all-or-nothing recording, idempotency and API consistency."""

from collections import Counter
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.clock import DATASET_REFERENCE_TIME
from app.core.config import DATA_NOTICE
from app.db.session import SessionLocal
from app.db.synthetic import DEMO_REQUEST_CODE
from app.models.enums import NotificationEventType as Event
from app.models.enums import NotificationRecipientRole as Role
from app.repositories.digital_twin_repository import DigitalTwinRepository
from app.repositories.donor_state_repository import DonorStateRepository
from app.repositories.failure_autopsy_repository import FailureAutopsyRepository
from app.repositories.matching_repository import MatchingRepository
from app.repositories.notification_repository import NotificationRepository
from app.schemas.cascade import CascadeOutcome
from app.services.cascade import AdaptiveCascadeEngine
from app.services.coordination_notifications import (
    CoordinationNotifier,
    NotificationBatchRejected,
    SimulationParams,
    build_notifications,
)
from app.services.digital_twin import DigitalTwinService
from app.services.donor_state import DonorStateEngine
from app.services.failure_autopsy import FailureAutopsyEngine
from app.services.matching import MatchingEngine
from app.services.notification_provider import DeliveryOutcome, DemoMessagingProvider, ProviderResult
from app.services.notifications import NotificationService

pytestmark = pytest.mark.usefixtures("seeded_app_database")
REQUESTS = "/api/v1/requests"
NOTIFY = "/api/v1/requests/{}/cascade/notifications"
LIST = "/api/v1/notifications"


@pytest.fixture(autouse=True)
def clean_notifications() -> Iterator[None]:
    def wipe() -> None:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM notifications"))
            session.commit()

    wipe()
    yield
    wipe()


def stored() -> int:
    with SessionLocal() as session:
        return session.scalar(text("select count(*) from notifications")) or 0


# ---- request search ---------------------------------------------------------------------------------------


def test_search_finds_the_demo_request_by_code(client: TestClient) -> None:
    body = client.get(REQUESTS, params={"search": DEMO_REQUEST_CODE}).json()
    assert body["total"] == 1 and [r["request_code"] for r in body["items"]] == [DEMO_REQUEST_CODE]
    # the exact same schema as the unfiltered list: no new or sensitive fields
    assert set(body["items"][0]) == set(client.get(REQUESTS).json()["items"][0])


def test_search_is_case_insensitive_partial_and_exact_match_first(client: TestClient) -> None:
    assert client.get(REQUESTS, params={"search": "demo-request-001"}).json()["items"][0]["request_code"] == DEMO_REQUEST_CODE
    partial = client.get(REQUESTS, params={"search": "REQ-0000", "page_size": 5}).json()
    assert partial["total"] > 5 and len(partial["items"]) == 5 and partial["pages"] > 1
    assert all("REQ-0000" in r["request_code"] for r in partial["items"])
    exact = client.get(REQUESTS, params={"search": "REQ-00010"}).json()
    assert exact["items"][0]["request_code"] == "REQ-00010"  # exact code first, then codes that contain it


def test_search_pagination_and_unfiltered_list_are_unchanged(client: TestClient) -> None:
    everything = client.get(REQUESTS, params={"page_size": 100}).json()
    assert everything["total"] == 320 and len(everything["items"]) == 100
    seen: list[str] = []
    for page in (1, 2, 3, 4):
        body = client.get(REQUESTS, params={"search": "REQ-", "page": page, "page_size": 100}).json()
        seen += [r["request_code"] for r in body["items"]]
    assert len(seen) == len(set(seen)) == body["total"] > 100


@pytest.mark.parametrize("search", ["REQ-99999", "zzz", "%", "_", "REQ-%", "DEMO_REQUEST"])
def test_unknown_or_wildcard_searches_return_nothing(client: TestClient, search: str) -> None:
    body = client.get(REQUESTS, params={"search": search}).json()
    assert body["total"] == 0 and body["items"] == [] and body["pages"] == 0  # wildcards are escaped, not interpreted


@pytest.mark.parametrize("params", [{"search": ""}, {"search": "x" * 25}])
def test_invalid_search_is_rejected(client: TestClient, params: dict) -> None:
    assert client.get(REQUESTS, params=params).status_code == 422


def test_search_never_creates_notifications(client: TestClient) -> None:
    client.get(REQUESTS, params={"search": "REQ-"})
    assert stored() == 0


# ---- event coverage audit -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cascade() -> Iterator[AdaptiveCascadeEngine]:
    with SessionLocal() as session:
        donor_states = DonorStateEngine(DonorStateRepository(session), DATASET_REFERENCE_TIME)
        twins = DigitalTwinService(DigitalTwinRepository(session), donor_states, DATASET_REFERENCE_TIME)
        matching = MatchingEngine(MatchingRepository(session), donor_states, twins)
        autopsy = FailureAutopsyEngine(FailureAutopsyRepository(session), matching, DATASET_REFERENCE_TIME, DATA_NOTICE)
        yield AdaptiveCascadeEngine(session, matching, autopsy)


SCENARIOS = [
    (code, seed, stress, waves)
    for code in (DEMO_REQUEST_CODE, "REQ-00001", "REQ-00002")  # HIGH, MODERATE and CRITICAL urgency
    for seed in range(1, 9)
    for stress, waves in (("none", 5), ("severe", 2), ("severe", 5))
]


def test_every_cascade_outcome_is_covered_exactly_once(cascade: AdaptiveCascadeEngine) -> None:
    outcomes: Counter = Counter()
    for code, seed, stress, max_waves in SCENARIOS:
        result = cascade.simulate(code, seed=seed, response_stress=stress, max_waves=max_waves)
        params = SimulationParams("auto", max_waves, None, seed, stress)
        planned = build_notifications(result, params)
        context = f"{code} seed={seed} {stress} waves={max_waves}"
        assert all(p.data is not None for p in planned), (context, [p.error for p in planned if p.data is None])
        by = Counter((p.event_type, p.recipient_role) for p in planned)
        fulfilled = result.outcome is CascadeOutcome.FULFILLED
        outcomes[result.outcome.value, result.escalation_type.value if result.escalation_type else None] += 1

        contacts = [c.donor_code for w in result.waves for c in w.contacts]
        assert by[Event.DONOR_OUTREACH, Role.DONOR] == len(contacts) == result.total_contacts, context
        assert sorted(p.data.recipient_ref for p in planned if p.event_type is Event.DONOR_OUTREACH) == sorted(contacts), context  # type: ignore[union-attr]
        failed_waves = [w for w in result.waves if w.units_secured_after_wave < result.units_required]
        assert by[Event.REQUEST_UPDATE, Role.COORDINATOR] == len(failed_waves), context
        automatic = [w for w in result.waves if w.recovery_plan and not w.recovery_plan.requires_human_intervention]
        assert by[Event.RECOVERY_ACTION, Role.COORDINATOR] == len(automatic), context
        assert by[Event.ESCALATION, Role.COORDINATOR] == (0 if fulfilled else 1), context
        assert result.requires_human_intervention is (not fulfilled), context  # an unfulfilled run always has an escalation
        assert by[Event.REQUEST_FULFILLED, Role.COORDINATOR] == by[Event.REQUEST_FULFILLED, Role.PATIENT] == (1 if fulfilled else 0), context
        # patient-facing: one "in progress" update, plus the secured outcome only when the simulation reached it
        assert by[Event.REQUEST_UPDATE, Role.PATIENT] == 1, context
        assert sum(n for (event, role), n in by.items() if role is Role.PATIENT) == (2 if fulfilled else 1), context
        # nothing the simulation cannot substantiate
        assert not {e for e, _ in by} & {Event.DONOR_ACCEPTED, Event.SYSTEM_NOTICE}, context
        assert not any(role is Role.SYSTEM for _, role in by), context
        keys = [p.data.idempotency_key for p in planned if p.data]
        assert len(keys) == len(set(keys)) and all(len(k) <= 128 for k in keys), context
    # the audit really exercised success, human-coordinator and blood-bank outcomes
    assert ("FULFILLED", None) in outcomes and ("ESCALATED", "BLOOD_BANK") in outcomes and ("ESCALATED", "HUMAN_COORDINATOR") in outcomes, outcomes


def test_escalation_replaces_the_recovery_notice_for_that_wave(cascade: AdaptiveCascadeEngine) -> None:
    result = cascade.simulate(DEMO_REQUEST_CODE, seed=2, response_stress="severe", max_waves=2)
    assert result.requires_human_intervention
    planned = build_notifications(result, SimulationParams("auto", 2, None, 2, "severe"))
    last_wave = result.waves_used
    kinds = [(p.event_type, p.wave_number) for p in planned if p.recipient_role is Role.COORDINATOR]
    assert (Event.ESCALATION, last_wave) in kinds and (Event.RECOVERY_ACTION, last_wave) not in kinds


def test_simulations_do_not_change_stored_request_status(client: TestClient) -> None:
    def statuses() -> list:
        with SessionLocal() as session:
            return [tuple(r) for r in session.execute(text("select request_code, status from blood_requests order by id"))]

    before = statuses()
    for code, seed in ((DEMO_REQUEST_CODE, 25), ("REQ-00001", 2), ("REQ-00002", 1)):  # includes fulfilled and escalated runs
        client.post(NOTIFY.format(code), params={"seed": seed})
        client.post(NOTIFY.format(code), params={"seed": seed, "response_stress": "severe", "max_waves": 2})
    assert statuses() == before


# ---- idempotency, counts, reseed -------------------------------------------------------------------------


def keyed(prefix: str) -> int:
    with SessionLocal() as session:
        return session.scalar(text("select count(*) from notifications where idempotency_key like :p"), {"p": prefix + "%"}) or 0


def test_reported_counts_match_stored_rows(client: TestClient) -> None:
    runs = [(DEMO_REQUEST_CODE, {"seed": 25}), (DEMO_REQUEST_CODE, {"seed": 26}), ("REQ-00001", {"seed": 2}),
            ("REQ-00002", {"seed": 1, "response_stress": "severe", "max_waves": 2})]
    total = 0
    for code, params in runs:
        report = client.post(NOTIFY.format(code), params=params).json()
        assert report["created"] + report["duplicates"] + report["rejected"] == len(report["items"])
        assert report["rejected"] == 0 and report["duplicates"] == 0
        assert keyed(f"{code}:{report['simulation_id']}:") == report["created"] == len(report["items"])
        assert sum(i["notification_id"] is not None for i in report["items"]) == report["created"]
        total += report["created"]
    assert stored() == total == client.get(f"{LIST}/summary").json()["total"] == client.get(LIST).json()["total"]
    again = client.post(NOTIFY.format(DEMO_REQUEST_CODE), params={"seed": 25}).json()
    assert again["created"] == 0 and again["duplicates"] == len(again["items"]) and stored() == total


def test_notifications_from_simulations_survive_a_reseed(client: TestClient) -> None:
    from app.db.seed import seed_database

    first = client.post(NOTIFY.format(DEMO_REQUEST_CODE), params={"seed": 25}).json()
    ids = sorted(i["notification_id"] for i in client.get(LIST, params={"page_size": 100}).json()["items"])
    with SessionLocal() as session:
        seed_database(session)
    assert sorted(i["notification_id"] for i in client.get(LIST, params={"page_size": 100}).json()["items"]) == ids
    rerun = client.post(NOTIFY.format(DEMO_REQUEST_CODE), params={"seed": 25}).json()  # same codes after the reseed
    assert rerun["created"] == 0 and rerun["duplicates"] == first["created"] and stored() == first["created"]


# ---- all-or-nothing recording ----------------------------------------------------------------------------


class FlakyProvider(DemoMessagingProvider):
    """Rejects, or raises on, the n-th delivery so a failure lands in the middle of a set."""

    def __init__(self, service: NotificationService, fail_at: int, mode: str) -> None:
        super().__init__(service)
        self.fail_at, self.mode, self.calls = fail_at, mode, 0

    def deliver(self, request, *, commit: bool = True) -> ProviderResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == self.fail_at:
            if self.mode == "raise":
                raise RuntimeError("database went away")
            return ProviderResult(DeliveryOutcome.REJECTED, error="simulated rejection")
        return super().deliver(request, commit=commit)


@pytest.mark.parametrize("mode", ["reject", "raise"])
def test_a_failure_part_way_leaves_no_partial_event_set(cascade: AdaptiveCascadeEngine, mode: str) -> None:
    with SessionLocal() as session:
        service = NotificationService(NotificationRepository(session), DATASET_REFERENCE_TIME)
        notifier = CoordinationNotifier(cascade, FlakyProvider(service, fail_at=6, mode=mode))
        expected = len(build_notifications(
            cascade.simulate(DEMO_REQUEST_CODE, seed=25), SimulationParams("auto", 5, None, 25, "none")))
        assert expected > 6
        with pytest.raises(NotificationBatchRejected if mode == "reject" else RuntimeError):
            notifier.notify_simulation(DEMO_REQUEST_CODE, SimulationParams("auto", 5, None, 25, "none"))
    assert stored() == 0  # the five notifications staged before the failure were rolled back
    with SessionLocal() as session:  # and the same simulation then records completely
        clean = CoordinationNotifier(cascade, DemoMessagingProvider(NotificationService(NotificationRepository(session), DATASET_REFERENCE_TIME)))
        report = clean.notify_simulation(DEMO_REQUEST_CODE, SimulationParams("auto", 5, None, 25, "none"))
    assert report.created == expected == stored() and report.rejected == 0


def test_api_reports_a_rejected_set_as_a_conflict_and_stores_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    original = DemoMessagingProvider.deliver
    calls = {"n": 0}

    def reject_third(self, request, *, commit: bool = True):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 3:
            return ProviderResult(DeliveryOutcome.REJECTED, error="unknown donor DON-99999")
        return original(self, request, commit=commit)

    monkeypatch.setattr(DemoMessagingProvider, "deliver", reject_third)
    response = client.post(NOTIFY.format(DEMO_REQUEST_CODE), params={"seed": 25})
    assert response.status_code == 409 and "No notifications were stored" in response.json()["detail"]
    assert "unknown donor DON-99999" in response.json()["detail"] and stored() == 0
    monkeypatch.undo()
    ok = client.post(NOTIFY.format(DEMO_REQUEST_CODE), params={"seed": 25})
    assert ok.status_code == 201 and stored() == ok.json()["created"]


def test_a_key_conflict_rejects_the_whole_set(client: TestClient) -> None:
    probe = client.post(NOTIFY.format(DEMO_REQUEST_CODE), params={"seed": 25}).json()
    key = client.get(LIST, params={"page_size": 100}).json()["items"][0]["idempotency_key"]
    with SessionLocal() as session:  # a different notification already holds one of this simulation's keys
        session.execute(text("DELETE FROM notifications WHERE idempotency_key != :k"), {"k": key})
        session.execute(text("UPDATE notifications SET title='Something else' WHERE idempotency_key = :k"), {"k": key})
        session.commit()
    assert stored() == 1
    response = client.post(NOTIFY.format(DEMO_REQUEST_CODE), params={"seed": 25})
    assert response.status_code == 409 and "different notification" in response.json()["detail"]
    assert stored() == 1 and probe["created"] > 1  # nothing new was kept


# ---- API consistency -------------------------------------------------------------------------------------


def _fill(client: TestClient) -> None:
    for code, params in ((DEMO_REQUEST_CODE, {"seed": 25}), ("REQ-00001", {"seed": 2}), ("REQ-00002", {"seed": 1, "response_stress": "severe", "max_waves": 2})):
        assert client.post(NOTIFY.format(code), params=params).status_code == 201


def test_summary_agrees_with_stored_records(client: TestClient) -> None:
    _fill(client)
    summary = client.get(f"{LIST}/summary").json()
    with SessionLocal() as session:
        def grouped(column: str) -> dict:
            return dict(session.execute(text(f"select {column}, count(*) from notifications group by {column}")).all())

        by_status, by_channel, by_mode = grouped("status"), grouped("channel"), grouped("mode")
        unread = session.scalar(text("select count(*) from notifications where channel='IN_APP' and read_at is null")) or 0
    assert summary["total"] == stored() == sum(by_status.values())
    assert {k: v for k, v in summary["by_status"].items() if v} == by_status
    assert {k: v for k, v in summary["by_channel"].items() if v} == by_channel
    assert {k: v for k, v in summary["by_mode"].items() if v} == by_mode
    assert summary["unread_in_app"] == unread
    assert summary["by_status"]["SENT"] == summary["by_status"]["DELIVERED"] == 0 and summary["by_mode"]["LIVE"] == 0


def test_pagination_walks_every_record_once_in_order(client: TestClient) -> None:
    _fill(client)
    with SessionLocal() as session:
        expected = [r[0] for r in session.execute(text("select notification_code from notifications order by created_at desc, id desc"))]
    seen: list[str] = []
    page, pages = 1, 1
    while page <= pages:
        body = client.get(LIST, params={"page": page, "page_size": 7}).json()
        pages = body["pages"]
        seen += [i["notification_id"] for i in body["items"]]
        assert body["total"] == len(expected) and len(body["items"]) <= 7
        page += 1
    assert seen == expected and pages == -(-len(expected) // 7)


@pytest.mark.parametrize("params,sql", [
    ({"recipient_role": "DONOR"}, "recipient_role='DONOR'"), ({"recipient_role": "PATIENT"}, "recipient_role='PATIENT'"),
    ({"recipient_role": "COORDINATOR"}, "recipient_role='COORDINATOR'"), ({"status": "SIMULATED"}, "status='SIMULATED'"),
    ({"status": "QUEUED"}, "status='QUEUED'"), ({"channel": "SMS"}, "channel='SMS'"), ({"channel": "IN_APP"}, "channel='IN_APP'"),
    ({"channel": "WHATSAPP"}, "channel='WHATSAPP'"), ({"mode": "DEMO"}, "mode='DEMO'"), ({"mode": "LIVE"}, "mode='LIVE'"),
    ({"request_code": "REQ-00002"}, "blood_request_code='REQ-00002'"), ({"request_code": "REQ-99999"}, "blood_request_code='REQ-99999'"),
    ({"recipient_role": "DONOR", "request_code": DEMO_REQUEST_CODE, "channel": "IN_APP"},
     f"recipient_role='DONOR' and blood_request_code='{DEMO_REQUEST_CODE}' and channel='IN_APP'"),
    ({"unread_only": True}, "channel='IN_APP' and read_at is null and status != 'CANCELLED'"),
])
def test_every_filter_agrees_with_the_database(client: TestClient, params: dict, sql: str) -> None:
    _fill(client)
    with SessionLocal() as session:
        expected = sorted(r[0] for r in session.execute(text(f"select notification_code from notifications where {sql}")))
    body = client.get(LIST, params={**params, "page_size": 100}).json()
    assert body["total"] == len(expected) and sorted(i["notification_id"] for i in body["items"]) == expected
    scoped = client.get(f"{LIST}/summary", params=params).json()
    assert scoped["total"] == len(expected)


def test_mark_as_read_keeps_the_unread_count_correct(client: TestClient) -> None:
    _fill(client)
    start = client.get(f"{LIST}/summary").json()["unread_in_app"]
    unread = client.get(LIST, params={"unread_only": True, "page_size": 3}).json()["items"]
    assert start > 3 and len(unread) == 3
    for index, item in enumerate(unread, start=1):
        assert client.patch(f"{LIST}/{item['notification_id']}/read").json()["read"] is True
        assert client.get(f"{LIST}/summary").json()["unread_in_app"] == start - index
    client.patch(f"{LIST}/{unread[0]['notification_id']}/read")  # repeating changes nothing
    assert client.get(f"{LIST}/summary").json()["unread_in_app"] == start - 3
    assert client.get(LIST, params={"unread_only": True}).json()["total"] == start - 3
    with SessionLocal() as session:
        assert session.scalar(text("select count(*) from notifications where channel='IN_APP' and read_at is null")) == start - 3


def test_no_demo_notification_is_ever_sent_or_delivered(client: TestClient) -> None:
    _fill(client)
    items = client.get(LIST, params={"page_size": 100}).json()["items"]
    assert items and all(i["mode"] == "DEMO" and i["status"] == "SIMULATED" for i in items)
    assert not [i for i in items if i["status"] in ("SENT", "DELIVERED") or i["provider_message_id"]]


def test_read_only_pages_create_nothing_after_all_changes(client: TestClient) -> None:
    for url, params in [(f"/api/v1/requests/{DEMO_REQUEST_CODE}/cascade", {"seed": 25}), (f"/api/v1/requests/{DEMO_REQUEST_CODE}/self-healing", {"seed": 25}),
                        (f"/api/v1/requests/{DEMO_REQUEST_CODE}/learning", {"seed": 25}), (REQUESTS, {"search": DEMO_REQUEST_CODE}),
                        (LIST, {}), (f"{LIST}/summary", {})]:
        assert client.get(url, params=params).status_code == 200
    assert stored() == 0
