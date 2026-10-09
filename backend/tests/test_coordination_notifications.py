"""Phase 10B: the demo messaging provider and event-driven DEMO notifications from simulated cascades.
Notifications observe the simulation; they never influence it, are created only by an explicit POST, and are
always DEMO / SIMULATED."""

import re
import socket
from collections import Counter
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.clock import DATASET_REFERENCE_TIME
from app.db.session import SessionLocal
from app.db.synthetic import DEMO_REQUEST_CODE
from app.models.enums import NotificationEventType, NotificationRecipientRole, NotificationStatus
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import NotificationCreate
from app.services.coordination_notifications import SimulationParams
from app.services.notification_provider import DeliveryOutcome, DemoMessagingProvider, NotificationProvider
from app.services.notifications import NotificationService

pytestmark = pytest.mark.usefixtures("seeded_app_database")
SEED = 25
NOTIFY = "/api/v1/requests/{}/cascade/notifications"
CASCADE = "/api/v1/requests/{}/cascade"
LIST = "/api/v1/notifications"
LABEL = "Synthetic demonstration, not for clinical use."


@pytest.fixture(autouse=True)
def clean_notifications() -> Iterator[None]:
    def wipe() -> None:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM notifications"))
            session.commit()

    wipe()
    yield
    wipe()


def notify(client: TestClient, code: str = DEMO_REQUEST_CODE, **params: object):  # type: ignore[no-untyped-def]
    return client.post(NOTIFY.format(code), params={"seed": SEED, **params})


def all_notifications(client: TestClient) -> list[dict]:
    return client.get(LIST, params={"page_size": 100}).json()["items"]


def by_event(items: list[dict]) -> Counter:
    return Counter((i["event_type"], i["recipient_role"]) for i in items)


# ---- events ----------------------------------------------------------------------------------------


def test_seed_25_events(client: TestClient) -> None:
    response = notify(client)
    assert response.status_code == 201
    report = response.json()
    assert report["mode"] == "DEMO" and report["rejected"] == 0 and report["duplicates"] == 0
    assert report["cascade_outcome"] == "FULFILLED" and re.fullmatch(r"SIM-[0-9A-F]{12}", report["simulation_id"])
    cascade = client.get(CASCADE.format(DEMO_REQUEST_CODE), params={"seed": SEED}).json()
    contacts = [c["donor_code"] for w in cascade["waves"] for c in w["contacts"]]
    items = all_notifications(client)
    assert len(items) == report["created"] == len(contacts) + 5
    assert by_event(items) == Counter({
        ("DONOR_OUTREACH", "DONOR"): len(contacts), ("REQUEST_UPDATE", "PATIENT"): 1, ("REQUEST_UPDATE", "COORDINATOR"): 1,
        ("RECOVERY_ACTION", "COORDINATOR"): 1, ("REQUEST_FULFILLED", "COORDINATOR"): 1, ("REQUEST_FULFILLED", "PATIENT"): 1,
    })
    assert sorted(i["recipient_ref"] for i in items if i["event_type"] == "DONOR_OUTREACH") == sorted(contacts)
    assert {i["recipient_ref"] for i in items if i["recipient_role"] == "PATIENT"} == {cascade["request"]["patient_code"]}
    assert all(i["blood_request_code"] == DEMO_REQUEST_CODE for i in items)


def test_human_coordinator_escalation(client: TestClient) -> None:
    params = {"seed": 2, "response_stress": "severe", "max_waves": 2}
    cascade = client.get(CASCADE.format(DEMO_REQUEST_CODE), params=params).json()
    assert cascade["requires_human_intervention"] and cascade["escalation_type"] == "HUMAN_COORDINATOR"
    report = client.post(NOTIFY.format(DEMO_REQUEST_CODE), params=params).json()
    assert report["cascade_outcome"] == "ESCALATED" and report["rejected"] == 0
    items = all_notifications(client)
    escalations = [i for i in items if i["event_type"] == "ESCALATION"]
    assert len(escalations) == 1 and escalations[0]["recipient_role"] == "COORDINATOR"
    body = escalations[0]["body"]
    assert "human coordinator" in body and "Next action:" in body and DEMO_REQUEST_CODE in escalations[0]["title"]
    assert not any(i["event_type"] == "REQUEST_FULFILLED" for i in items)
    # an escalation replaces, rather than duplicates, the recovery notice for that wave
    assert [i["wave_number"] for i in report["items"] if i["event_type"] == "ESCALATION"] == [cascade["waves_used"]]


def test_blood_bank_escalation(client: TestClient) -> None:
    params = {"seed": 1, "response_stress": "severe", "max_waves": 2}
    code = "REQ-00002"
    cascade = client.get(CASCADE.format(code), params=params).json()
    assert cascade["escalation_type"] == "BLOOD_BANK"
    assert client.post(NOTIFY.format(code), params=params).status_code == 201
    escalation = next(i for i in all_notifications(client) if i["event_type"] == "ESCALATION")
    assert "blood bank" in escalation["body"] and escalation["blood_request_code"] == code


def test_failed_waves_and_recoveries_are_reported_to_the_coordinator(client: TestClient) -> None:
    params = {"seed": 7, "response_stress": "severe", "max_waves": 5}
    cascade = client.get(CASCADE.format(DEMO_REQUEST_CODE), params=params).json()
    failed = [w for w in cascade["waves"] if w["recovery_plan"]]
    automatic = [w for w in failed if not w["recovery_plan"]["requires_human_intervention"]]
    client.post(NOTIFY.format(DEMO_REQUEST_CODE), params=params)
    counts = by_event(all_notifications(client))
    assert counts[("REQUEST_UPDATE", "COORDINATOR")] == len(failed)
    assert counts[("RECOVERY_ACTION", "COORDINATOR")] == len(automatic)
    for item in all_notifications(client):
        if item["event_type"] == "RECOVERY_ACTION":
            assert "self-healing selected" in item["body"] and "Next action:" in item["body"]


# ---- statuses, labels, privacy ---------------------------------------------------------------------


def _created_with_everything(client: TestClient) -> list[dict]:
    notify(client)
    notify(client, seed=2, response_stress="severe", max_waves=2)
    client.post(NOTIFY.format("REQ-00002"), params={"seed": 1, "response_stress": "severe", "max_waves": 2})
    return all_notifications(client)


def test_every_notification_is_demo_and_simulated(client: TestClient) -> None:
    items = _created_with_everything(client)
    assert len(items) > 20
    assert {i["mode"] for i in items} == {"DEMO"} and {i["status"] for i in items} == {"SIMULATED"}
    assert all(i["provider_message_id"] is None and i["failure_code"] is None for i in items)
    assert not {i["status"] for i in items} & {"SENT", "DELIVERED", "FAILED"}
    assert all("Nothing was delivered" in i["delivery_note"] for i in items)
    summary = client.get(f"{LIST}/summary").json()
    assert summary["by_status"]["SENT"] == summary["by_status"]["DELIVERED"] == 0 and summary["by_mode"]["LIVE"] == 0


def test_every_message_is_labelled_and_respects_privacy(client: TestClient) -> None:
    for item in _created_with_everything(client):
        assert item["title"].startswith("[DEMO]") and item["body"].startswith(LABEL), item["title"]
        text_ = f"{item['title']} {item['body']}"
        assert not re.search(r"\+?\d[\d\s().-]{7,}\d|@", text_)
        donors, patients = set(re.findall(r"DON-\d+", text_)), set(re.findall(r"PAT-\d+", text_))
        if item["recipient_role"] == "DONOR":
            assert not patients and donors <= {item["recipient_ref"]}
            assert "No real message was sent to any phone" in item["body"] and "nothing is being asked of you" in item["body"]
        if item["recipient_role"] == "PATIENT":
            assert not donors and patients <= {item["recipient_ref"]}
            assert re.search(r"availability|clinical", item["body"]) and "guarantee" not in item["body"].lower()
        assert len(item["body"]) <= 500 and item["recipient_ref"] != "" and item["event_type"] != "DONOR_ACCEPTED"


def test_donor_messages_do_not_claim_contact_or_response(client: TestClient) -> None:
    notify(client)
    for item in all_notifications(client):
        if item["recipient_role"] == "DONOR":
            lowered = item["body"].lower()
            assert "in this simulation" in lowered and "accepted" not in lowered and "confirmed" not in lowered


# ---- idempotency and distinct simulations ---------------------------------------------------------------


def test_repeat_processing_creates_nothing_new(client: TestClient) -> None:
    first = notify(client)
    ids = sorted(i["notification_id"] for i in all_notifications(client))
    again = notify(client)
    assert first.status_code == 201 and again.status_code == 200
    report = again.json()
    assert report["created"] == 0 and report["duplicates"] == first.json()["created"] and report["rejected"] == 0
    assert sorted(i["notification_id"] for i in all_notifications(client)) == ids
    assert {i["outcome"] for i in report["items"]} == {"DUPLICATE"}


def test_distinct_simulations_do_not_deduplicate(client: TestClient) -> None:
    runs = [{"seed": 25}, {"seed": 26}, {"seed": 25, "response_stress": "severe"}, {"seed": 25, "wave_size": 2}, {"seed": 25, "max_waves": 3}]
    reports = [client.post(NOTIFY.format(DEMO_REQUEST_CODE), params=p).json() for p in runs]
    assert len({r["simulation_id"] for r in reports}) == len(runs)
    assert all(r["duplicates"] == 0 and r["rejected"] == 0 for r in reports)
    assert len(all_notifications(client)) == sum(r["created"] for r in reports)
    keys = [i["idempotency_key"] for i in all_notifications(client)]
    assert len(keys) == len(set(keys)) and all(len(k) <= 128 and re.fullmatch(r"[A-Za-z0-9._:-]+", k) for k in keys)
    assert all(k.startswith(f"{DEMO_REQUEST_CODE}:SIM-") for k in keys)


def test_simulation_id_is_stable_and_covers_every_parameter() -> None:
    base = SimulationParams("auto", 5, None, 25, "none")
    assert base.simulation_id(DEMO_REQUEST_CODE) == "SIM-D0352F87A569"  # regression: derived only from parameters
    variants = [SimulationParams("now", 5, None, 25, "none"), SimulationParams("auto", 4, None, 25, "none"),
                SimulationParams("auto", 5, 2, 25, "none"), SimulationParams("auto", 5, None, 26, "none"),
                SimulationParams("auto", 5, None, 25, "severe")]
    ids = {v.simulation_id(DEMO_REQUEST_CODE) for v in variants} | {base.simulation_id(DEMO_REQUEST_CODE), base.simulation_id("REQ-00001")}
    assert len(ids) == len(variants) + 2


# ---- read-only behaviour and non-interference -------------------------------------------------------------


def test_read_only_endpoints_never_create_notifications(client: TestClient) -> None:
    code = DEMO_REQUEST_CODE
    for url, params in [
        (CASCADE.format(code), {"seed": SEED}), (f"/api/v1/requests/{code}/matching", {}),
        (f"/api/v1/requests/{code}/failures/autopsy", {}), (f"/api/v1/requests/{code}/self-healing", {"seed": SEED}),
        (f"/api/v1/requests/{code}/learning", {"seed": SEED, "runs": 3}), ("/api/v1/learning/report", {}),
        (f"/api/v1/requests/{code}/digital-twin-context", {}), (f"/api/v1/requests/{code}/donor-comparison", {}),
        ("/api/v1/patients/PAT-0001/digital-twin", {}), ("/api/v1/donors/DON-00001/state", {}),
        (LIST, {}), (f"{LIST}/summary", {}),
    ]:
        assert client.get(url, params=params).status_code == 200, url
    assert client.get(f"{LIST}/summary").json()["total"] == 0


def test_notifying_does_not_change_any_workflow_output(client: TestClient) -> None:
    code = DEMO_REQUEST_CODE
    reads = {
        "cascade": (CASCADE.format(code), {"seed": SEED}), "matching": (f"/api/v1/requests/{code}/matching", {}),
        "autopsy": (f"/api/v1/requests/{code}/failures/autopsy", {}),
        "healing": (f"/api/v1/requests/{code}/self-healing", {"seed": SEED}),
        "learning": (f"/api/v1/requests/{code}/learning", {"seed": SEED, "runs": 3}),
        "recorded": ("/api/v1/learning/report", {}), "twin": ("/api/v1/patients/PAT-0001/digital-twin", {}),
    }
    before = {name: client.get(url, params=params).json() for name, (url, params) in reads.items()}
    assert notify(client).status_code == 201 and notify(client).status_code == 200
    assert {name: client.get(url, params=params).json() for name, (url, params) in reads.items()} == before
    report = notify(client).json()
    assert report["cascade_outcome"] == before["cascade"]["outcome"]


def test_only_notification_rows_change(client: TestClient) -> None:
    tables = ["donors", "patients", "blood_requests", "donor_interactions", "coordination_attempts", "failures",
              "recovery_actions", "learning_events", "donor_states", "bridge_groups"]

    def snapshot() -> dict:
        with SessionLocal() as session:
            return {
                "counts": {t: session.scalar(text(f"select count(*) from {t}")) for t in tables},
                "requests": [tuple(r) for r in session.execute(text("select id, status, units_required from blood_requests order by id"))],
                "interactions": [tuple(r) for r in session.execute(text("select id, response_status, response_at from donor_interactions order by id"))],
                "states": [tuple(r) for r in session.execute(text("select donor_id, availability_status, fatigue_score, current_priority_score from donor_states order by donor_id"))],
            }

    before = snapshot()
    report = notify(client).json()
    assert snapshot() == before
    with SessionLocal() as session:
        assert session.scalar(text("select count(*) from notifications")) == report["created"] > 0


def test_no_external_network_calls(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a network connection was attempted")

    for target in ("connect",):
        monkeypatch.setattr(socket.socket, target, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    assert notify(client).status_code == 201


# ---- errors ---------------------------------------------------------------------------------------------


def test_unknown_request_and_invalid_parameters(client: TestClient) -> None:
    assert client.post(NOTIFY.format("REQ-99999")).status_code == 404
    for params in ({"max_waves": 0}, {"max_waves": 9}, {"wave_size": 7}, {"seed": -1}, {"response_stress": "x"}, {"evaluate_at": "later"}):
        assert client.post(NOTIFY.format(DEMO_REQUEST_CODE), params=params).status_code == 422
    assert all_notifications(client) == []
    assert client.get(NOTIFY.format(DEMO_REQUEST_CODE)).status_code == 405  # no notification-creating GET


# ---- the provider -----------------------------------------------------------------------------------------


def _provider() -> tuple[DemoMessagingProvider, SessionLocal]:  # type: ignore[valid-type]
    session = SessionLocal()
    return DemoMessagingProvider(NotificationService(NotificationRepository(session), DATASET_REFERENCE_TIME)), session


def _request(**overrides: object) -> NotificationCreate:
    base: dict = dict(
        event_type=NotificationEventType.DONOR_OUTREACH, recipient_role=NotificationRecipientRole.DONOR,
        recipient_ref="DON-00001", blood_request_code=DEMO_REQUEST_CODE, title="[DEMO] Test",
        body=f"{LABEL} A simulated message.",
    )
    return NotificationCreate(**{**base, **overrides})


def test_demo_provider_records_simulated_and_reports_outcomes() -> None:
    provider, session = _provider()
    with session:
        assert isinstance(provider, NotificationProvider) and provider.name == "demo" and provider.mode.value == "DEMO"
        queued = _request(status=NotificationStatus.QUEUED, idempotency_key="p-1")
        first = provider.deliver(queued)
        assert first.outcome is DeliveryOutcome.RECORDED and first.recorded
        assert first.notification is not None and first.notification.status is NotificationStatus.SIMULATED  # never queued
        assert first.notification.provider_message_id is None and first.notification.mode.value == "DEMO"
        again = provider.deliver(queued)
        assert again.outcome is DeliveryOutcome.DUPLICATE and again.notification == first.notification
        conflict = provider.deliver(_request(idempotency_key="p-1", title="[DEMO] Different"))
        assert conflict.outcome is DeliveryOutcome.REJECTED and "different notification" in (conflict.error or "")
        unknown = provider.deliver(_request(recipient_ref="DON-99999"))
        assert unknown.outcome is DeliveryOutcome.REJECTED and unknown.notification is None and "Unknown donor" in (unknown.error or "")


def test_provider_has_no_network_client_and_cannot_be_live() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "services"
    forbidden = re.compile(r"^\s*(import|from)\s+(httpx|requests|urllib|aiohttp|http\.client|socket|smtplib|twilio|boto3)\b", re.M)
    for name in ("notification_provider.py", "coordination_notifications.py"):
        assert not forbidden.search((root / name).read_text(encoding="utf-8")), name
    with pytest.raises(ValueError):
        _request(mode="LIVE")
    with pytest.raises(ValueError):
        _request(status="SENT")
