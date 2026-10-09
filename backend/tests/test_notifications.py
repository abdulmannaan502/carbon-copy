"""Notifications (Phase 10A): record keeping only. Creation never sends anything, demo notifications are
never SENT or DELIVERED, and the existing dataset is untouched."""

import re
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.clock import DATASET_REFERENCE_TIME
from app.db.session import SessionLocal
from app.db.synthetic import DEMO_REQUEST_CODE
from app.models import Notification
from app.models.enums import (
    NotificationChannel,
    NotificationEventType,
    NotificationMode,
    NotificationRecipientRole,
    NotificationStatus,
)

pytestmark = pytest.mark.usefixtures("seeded_app_database")
URL = "/api/v1/notifications"
DONOR, OTHER_DONOR, PATIENT = "DON-00001", "DON-00002", "PAT-0001"


@pytest.fixture(autouse=True)
def clean_notifications() -> Iterator[None]:
    """The in-memory database is shared across tests; each test starts and ends without notifications."""
    def wipe() -> None:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM notifications"))
            session.commit()

    wipe()
    yield
    wipe()


def payload(**overrides: object) -> dict:
    base: dict = {
        "event_type": "DONOR_OUTREACH", "recipient_role": "DONOR", "recipient_ref": DONOR,
        "blood_request_code": DEMO_REQUEST_CODE, "title": "A request needs your help",
        "body": "A donation request is open. Please reply if you are available.",
    }
    return {**base, **overrides}


def create(client: TestClient, **overrides: object) -> dict:
    response = client.post(URL, json=payload(**overrides))
    assert response.status_code in (200, 201), response.text
    return response.json()


# ---- creation and retrieval ---------------------------------------------------------------------


def test_create_and_retrieve(client: TestClient) -> None:
    created = client.post(URL, json=payload())
    assert created.status_code == 201
    body = created.json()
    assert re.fullmatch(r"NTF-[0-9A-F]{12}", body["notification_id"])
    assert body["mode"] == "DEMO" and body["status"] == "SIMULATED" and body["channel"] == "IN_APP"
    assert body["recipient_role"] == "DONOR" and body["recipient_ref"] == DONOR
    assert body["blood_request_code"] == DEMO_REQUEST_CODE and body["read"] is False and body["read_at"] is None
    assert body["provider_message_id"] is None and body["failure_code"] is None
    assert "Nothing was delivered" in body["delivery_note"]
    assert body["created_at"] == body["updated_at"] == DATASET_REFERENCE_TIME.isoformat()  # injected clock
    fetched = client.get(f"{URL}/{body['notification_id']}")
    assert fetched.status_code == 200 and fetched.json() == body


def test_queued_is_allowed_and_described_truthfully(client: TestClient) -> None:
    body = create(client, status="QUEUED")
    assert body["status"] == "QUEUED" and "Nothing has been sent" in body["delivery_note"]


@pytest.mark.parametrize("channel", ["IN_APP", "SMS", "WHATSAPP"])
def test_every_channel_is_recorded_but_never_sent(client: TestClient, channel: str) -> None:
    body = create(client, channel=channel)
    assert body["mode"] == "DEMO" and body["status"] == "SIMULATED" and body["provider_message_id"] is None


@pytest.mark.parametrize("override", [
    {"mode": "LIVE"}, {"status": "SENT"}, {"status": "DELIVERED"}, {"status": "FAILED"}, {"status": "CANCELLED"},
    {"provider_message_id": "SM123"}, {"mode": "demo2"}, {"channel": "EMAIL"}, {"event_type": "UNKNOWN"},
])
def test_creation_cannot_request_live_or_delivery_states(client: TestClient, override: dict) -> None:
    assert client.post(URL, json=payload(**override)).status_code == 422


def test_database_refuses_demo_notifications_that_claim_delivery() -> None:
    def row(**kwargs: object) -> Notification:
        base = dict(
            notification_code="NTF-AAAAAAAAAAAA", event_type=NotificationEventType.SYSTEM_NOTICE,
            recipient_role=NotificationRecipientRole.SYSTEM, channel=NotificationChannel.IN_APP,
            mode=NotificationMode.DEMO, status=NotificationStatus.SIMULATED, title="t", body="b",
            created_at=DATASET_REFERENCE_TIME, updated_at=DATASET_REFERENCE_TIME,
        )
        return Notification(**{**base, **kwargs})  # type: ignore[arg-type]

    for bad in (row(status=NotificationStatus.SENT), row(status=NotificationStatus.DELIVERED),
                row(provider_message_id="SM123")):
        with SessionLocal() as session:
            session.add(bad)
            with pytest.raises(IntegrityError):
                session.commit()


def test_demo_mode_never_reports_sent_or_delivered(client: TestClient) -> None:
    for channel in ("IN_APP", "SMS", "WHATSAPP"):
        for status in ("SIMULATED", "QUEUED"):
            create(client, channel=channel, status=status)
    items = client.get(URL, params={"page_size": 100}).json()["items"]
    assert len(items) == 6 and {i["status"] for i in items} <= {"SIMULATED", "QUEUED"}
    summary = client.get(f"{URL}/summary").json()
    assert summary["by_status"]["SENT"] == summary["by_status"]["DELIVERED"] == 0
    assert summary["by_mode"] == {"DEMO": 6, "LIVE": 0}


# ---- listing, pagination, filters, summary ---------------------------------------------------------


def test_pagination_newest_first(client: TestClient) -> None:
    ids = [create(client, title=f"Notice {n}", body="Update.")["notification_id"] for n in range(25)]
    page1 = client.get(URL, params={"page": 1, "page_size": 10}).json()
    page3 = client.get(URL, params={"page": 3, "page_size": 10}).json()
    assert (page1["total"], page1["pages"], page1["page"], page1["page_size"]) == (25, 3, 1, 10)
    assert [i["notification_id"] for i in page1["items"]] == ids[::-1][:10]  # newest first
    assert len(page3["items"]) == 5 and page3["items"][-1]["notification_id"] == ids[0]
    assert client.get(URL, params={"page": 4, "page_size": 10}).json()["items"] == []


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"page": "x"}])
def test_invalid_pagination_is_rejected(client: TestClient, params: dict) -> None:
    assert client.get(URL, params=params).status_code == 422


def test_filters(client: TestClient) -> None:
    create(client)
    create(client, channel="SMS", status="QUEUED")
    create(client, recipient_ref=OTHER_DONOR, blood_request_code=None)
    create(client, event_type="REQUEST_UPDATE", recipient_role="PATIENT", recipient_ref=PATIENT, body="Your request is being coordinated.")
    create(client, event_type="ESCALATION", recipient_role="COORDINATOR", recipient_ref=None, body="Review needed.")
    create(client, event_type="SYSTEM_NOTICE", recipient_role="SYSTEM", recipient_ref=None, blood_request_code=None)

    def count(**params: object) -> int:
        response = client.get(URL, params=params)
        assert response.status_code == 200
        return response.json()["total"]

    assert count() == 6
    assert count(recipient_role="DONOR") == 3 and count(recipient_role="PATIENT") == 1
    assert count(recipient_role="COORDINATOR") == 1 and count(recipient_role="SYSTEM") == 1
    assert count(recipient_ref=DONOR) == 2 and count(recipient_ref=OTHER_DONOR) == 1
    assert count(request_code=DEMO_REQUEST_CODE) == 4
    assert count(channel="SMS") == 1 and count(channel="IN_APP") == 5 and count(channel="WHATSAPP") == 0
    assert count(status="QUEUED") == 1 and count(status="SIMULATED") == 5 and count(status="SENT") == 0
    assert count(mode="DEMO") == 6 and count(mode="LIVE") == 0
    assert count(recipient_role="DONOR", channel="IN_APP", request_code=DEMO_REQUEST_CODE) == 1
    assert count(request_code="REQ-99999") == 0


@pytest.mark.parametrize("params", [
    {"status": "DELIVERD"}, {"mode": "TEST"}, {"channel": "EMAIL"}, {"recipient_role": "ADMIN"},
    {"unread_only": "maybe"}, {"recipient_ref": "x" * 33},
])
def test_invalid_filters_are_rejected(client: TestClient, params: dict) -> None:
    assert client.get(URL, params=params).status_code == 422
    assert client.get(f"{URL}/summary", params=params).status_code == 422


def test_summary_counts_are_exact_and_zero_filled(client: TestClient) -> None:
    empty = client.get(f"{URL}/summary").json()
    assert empty["total"] == 0 and set(empty["by_status"]) == {s.value for s in NotificationStatus}
    assert sum(empty["by_status"].values()) == 0 and empty["unread_in_app"] == 0
    for _ in range(3):
        create(client)
    create(client, status="QUEUED")
    create(client, channel="SMS")
    summary = client.get(f"{URL}/summary").json()
    assert summary["total"] == 5 and summary["by_status"]["SIMULATED"] == 4 and summary["by_status"]["QUEUED"] == 1
    assert summary["by_channel"] == {"IN_APP": 4, "SMS": 1, "WHATSAPP": 0} and summary["unread_in_app"] == 4
    assert "no real message was sent" in summary["demo_notice"]
    scoped = client.get(f"{URL}/summary", params={"channel": "SMS"}).json()
    assert scoped["total"] == 1 and scoped["unread_in_app"] == 0


# ---- idempotency -------------------------------------------------------------------------------------


def test_idempotency_key_prevents_duplicates(client: TestClient) -> None:
    first = client.post(URL, json=payload(idempotency_key="evt:req-1:wave-1"))
    again = client.post(URL, json=payload(idempotency_key="evt:req-1:wave-1"))
    assert first.status_code == 201 and again.status_code == 200
    assert first.json() == again.json()
    assert client.get(URL).json()["total"] == 1


def test_reusing_a_key_for_a_different_notification_conflicts(client: TestClient) -> None:
    create(client, idempotency_key="k-1")
    response = client.post(URL, json=payload(idempotency_key="k-1", title="A different message"))
    assert response.status_code == 409 and "different notification" in response.json()["detail"]
    assert client.get(URL).json()["total"] == 1


def test_without_a_key_repeats_are_separate_notifications(client: TestClient) -> None:
    assert create(client)["notification_id"] != create(client)["notification_id"]
    assert client.get(URL).json()["total"] == 2


@pytest.mark.parametrize("key", ["has space", "x" * 129, "emoji🙂", "a/b"])
def test_invalid_idempotency_keys_are_rejected(client: TestClient, key: str) -> None:
    assert client.post(URL, json=payload(idempotency_key=key)).status_code == 422


# ---- lookup errors -----------------------------------------------------------------------------------


def test_unknown_and_malformed_ids(client: TestClient) -> None:
    unknown = client.get(f"{URL}/NTF-000000000000")
    assert unknown.status_code == 404 and "not found" in unknown.json()["detail"]
    assert client.patch(f"{URL}/NTF-000000000000/read").status_code == 404
    assert client.get(f"{URL}/not-a-notification").status_code == 422
    assert client.get(f"{URL}/summary").status_code == 200  # not captured by the id route


# ---- read state --------------------------------------------------------------------------------------


def test_read_state_transitions(client: TestClient) -> None:
    created = create(client)
    nid = created["notification_id"]
    assert client.get(URL, params={"unread_only": True}).json()["total"] == 1
    read = client.patch(f"{URL}/{nid}/read")
    assert read.status_code == 200 and read.json()["read"] is True
    first_read_at = read.json()["read_at"]
    assert first_read_at == DATASET_REFERENCE_TIME.isoformat() and read.json()["status"] == "SIMULATED"
    assert read.json()["updated_at"] == DATASET_REFERENCE_TIME.isoformat()  # operational clock, never wall-clock
    assert client.patch(f"{URL}/{nid}/read").json()["read_at"] == first_read_at  # idempotent
    assert client.get(URL, params={"unread_only": True}).json()["total"] == 0
    assert client.get(f"{URL}/summary").json()["unread_in_app"] == 0
    assert client.get(f"{URL}/{nid}").json()["read"] is True


def test_only_in_app_notifications_have_read_state(client: TestClient) -> None:
    nid = create(client, channel="SMS")["notification_id"]
    response = client.patch(f"{URL}/{nid}/read")
    assert response.status_code == 409 and "in-app" in response.json()["detail"]
    assert client.get(f"{URL}/{nid}").json()["read"] is False


def test_cancelled_notification_cannot_be_read(client: TestClient) -> None:
    nid = create(client)["notification_id"]
    with SessionLocal() as session:
        session.execute(text("UPDATE notifications SET status='CANCELLED' WHERE notification_code=:c"), {"c": nid})
        session.commit()
    assert client.patch(f"{URL}/{nid}/read").status_code == 409
    assert client.get(URL, params={"unread_only": True}).json()["total"] == 0
    assert "nothing was delivered" in client.get(f"{URL}/{nid}").json()["delivery_note"].lower()


# ---- recipients, references and privacy -----------------------------------------------------------


@pytest.mark.parametrize("override", [
    {"recipient_ref": "DON-99999"}, {"recipient_role": "PATIENT", "recipient_ref": "PAT-9999", "body": "Update."},
    {"blood_request_code": "REQ-99999"},
])
def test_unknown_references_are_rejected(client: TestClient, override: dict) -> None:
    response = client.post(URL, json=payload(**override))
    assert response.status_code == 422 and "Unknown" in response.json()["detail"]
    assert client.get(URL).json()["total"] == 0


@pytest.mark.parametrize("override", [
    {"recipient_ref": None}, {"recipient_ref": "donor-1"}, {"recipient_role": "PATIENT"},
    {"recipient_role": "SYSTEM"}, {"recipient_role": "COORDINATOR", "recipient_ref": "bad;label"},
    {"blood_request_code": "bad code!"}, {"title": " "}, {"body": ""}, {"body": "x" * 501},
])
def test_invalid_recipient_or_content_is_rejected(client: TestClient, override: dict) -> None:
    assert client.post(URL, json=payload(**override)).status_code == 422


@pytest.mark.parametrize("override", [
    {"body": f"Donor {OTHER_DONOR} also replied."},                      # another donor's details
    {"body": "This is for patient PAT-0001."},                           # patient identity to a donor
    {"body": "Call +91 98765 43210 now."}, {"body": "Write to someone@example.com"},
    {"title": f"About {OTHER_DONOR}"},
    {"recipient_role": "PATIENT", "recipient_ref": PATIENT, "body": f"{DONOR} is coming."},  # donor details to a patient
    {"recipient_role": "PATIENT", "recipient_ref": PATIENT, "body": "Patient PAT-0002 is waiting."},
])
def test_private_details_are_not_shared_across_recipients(client: TestClient, override: dict) -> None:
    assert client.post(URL, json=payload(**override)).status_code == 422


def test_own_code_and_operational_messages_are_allowed(client: TestClient) -> None:
    assert client.post(URL, json=payload(body=f"Thank you {DONOR}.")).status_code == 201
    coordinator = payload(event_type="ESCALATION", recipient_role="COORDINATOR", recipient_ref="Duty desk",
                          body=f"{DONOR} accepted {DEMO_REQUEST_CODE}; {PATIENT} still needs one more unit.")
    assert client.post(URL, json=coordinator).status_code == 201


def test_responses_carry_no_internal_ids_or_credentials(client: TestClient) -> None:
    body = create(client)
    assert "id" not in body and not any("secret" in key or "token" in key or "key" == key for key in body)


# ---- safety: no external calls, no changes to existing records ------------------------------------


def _fingerprint() -> dict:
    with SessionLocal() as session:
        def rows(sql: str) -> list:
            return [tuple(r) for r in session.execute(text(sql)).all()]

        return {
            "donors": rows("select id, donor_code, active, bridge_group_id from donors order by id"),
            "patients": rows("select id, patient_code, active from patients order by id")
            if "active" in {c[1] for c in session.execute(text("pragma table_info(patients)")).all()}
            else rows("select id, patient_code from patients order by id"),
            "requests": rows("select id, request_code, status, units_required from blood_requests order by id"),
            "interactions": rows("select id, response_status, channel, response_at from donor_interactions order by id"),
            "attempts": rows("select id, status, outcome from coordination_attempts order by id"),
            "failures": rows("select id, failure_category from failures order by id"),
            "recoveries": rows("select id, action_type, status from recovery_actions order by id"),
            "learning": rows("select id, event_type, signal from learning_events order by id"),
        }


def test_notifications_do_not_change_existing_records(client: TestClient) -> None:
    before = _fingerprint()
    nid = create(client, idempotency_key="k")["notification_id"]
    create(client, channel="SMS", status="QUEUED")
    client.get(URL), client.get(f"{URL}/summary"), client.get(f"{URL}/{nid}")
    client.patch(f"{URL}/{nid}/read")
    client.post(URL, json=payload(recipient_ref="DON-99999"))  # rejected
    assert _fingerprint() == before


def test_no_network_or_messaging_calls(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    nid = create(client, channel="SMS")["notification_id"]
    create(client, channel="WHATSAPP", status="QUEUED")
    assert client.get(f"{URL}/{nid}").status_code == 200 and client.get(f"{URL}/summary").status_code == 200


def test_notification_code_has_no_messaging_or_http_client_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    sources = [root / "services" / "notifications.py", root / "repositories" / "notification_repository.py",
               root / "models" / "notification.py", root / "schemas" / "notification.py",
               root / "api" / "routes" / "notifications.py"]
    forbidden = re.compile(r"^\s*(import|from)\s+(httpx|requests|urllib|aiohttp|http\.client|socket|smtplib|twilio|boto3)\b", re.M)
    for source in sources:
        assert not forbidden.search(source.read_text(encoding="utf-8")), source.name


# ---- schema safety --------------------------------------------------------------------------------


def test_reseeding_the_dataset_keeps_notifications(client: TestClient) -> None:
    from app.db.seed import seed_database

    nid = create(client, idempotency_key="survives-reseed")["notification_id"]
    with SessionLocal() as session:
        counts = seed_database(session)
    assert counts["donors"] == 6946 and client.get(f"{URL}/{nid}").status_code == 200


def test_notifications_table_is_the_only_schema_addition() -> None:
    with SessionLocal() as session:
        tables = {row[0] for row in session.execute(text("select name from sqlite_master where type='table'"))}
    assert {"notifications", "test_recipients"} <= tables and len(tables) == 12
