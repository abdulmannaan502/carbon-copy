"""Phase 10E.1: the Twilio SMS provider, with a MOCKED client only. No test ever calls Twilio or the network.

All credentials and phone numbers below are obviously fake placeholders."""

import json
import logging
import re
import socket
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from twilio.base.exceptions import TwilioRestException

from app.api.deps import DbSession, NotificationServiceDep, get_live_sms_sender
from app.core.clock import DATASET_REFERENCE_TIME
from app.core.config import DATA_NOTICE, Settings, get_settings
from app.db import test_recipients as recipient_cli
from app.db.session import SessionLocal
from app.db.synthetic import DEMO_REQUEST_CODE
from app.main import create_app
from app.models import Notification, TestRecipient
from app.models.enums import NotificationChannel, NotificationEventType, NotificationRecipientRole, NotificationStatus
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import NotificationCreate
from app.services.live_sms import (
    MAX_TEST_SENDS_PER_RECIPIENT,
    LiveSmsSender,
    RecipientAuthorizer,
    SendNotAuthorized,
    TwilioConfig,
    TwilioSmsProvider,
    classify_error,
    default_client_factory,
    render_template,
)
from app.services.notifications import NotificationConflict, NotificationService

pytestmark = pytest.mark.usefixtures("seeded_app_database")

FAKE_SID = "AC" + "0" * 32
FAKE_TOKEN = "fake-auth-token-for-tests-only"
FAKE_FROM = "+15550100000"
FAKE_PHONE = "+15550100123"
FAKE_MESSAGE_SID = "SM" + "1" * 32
URL = "/api/v1/notifications/test-sms"
CONFIG = TwilioConfig(FAKE_SID, FAKE_TOKEN, FAKE_FROM, None, 5.0)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clean tables, and make any real network connection a test failure."""
    def wipe() -> None:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM notifications"))
            session.execute(text("DELETE FROM test_recipients"))
            session.commit()

    real_connect = socket.socket.connect

    def only_loopback(sock: socket.socket, address: object, *args: object) -> None:
        # The event loop's own self-pipe connects to 127.0.0.1; anything else would be a real connection.
        if not (isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1", "localhost")):
            raise AssertionError("a network connection was attempted")
        real_connect(sock, address, *args)  # type: ignore[arg-type]

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", only_loopback)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    wipe()
    yield
    wipe()


class FakeTwilio:
    """Stands in for twilio.rest.Client: records calls, and returns or raises what the test says."""

    def __init__(self, result: object = None, raises: BaseException | None = None, delay: float = 0.0) -> None:
        self.calls: list[dict] = []
        self.result = result if result is not None else SimpleNamespace(sid=FAKE_MESSAGE_SID, status="queued")
        self.raises, self.delay = raises, delay
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        return self.result


def live_client(fake: FakeTwilio, config: TwilioConfig = CONFIG) -> Iterator[TestClient]:
    app = create_app()

    def override(db: DbSession, notifications: NotificationServiceDep) -> LiveSmsSender:
        provider = TwilioSmsProvider(config, notifications, RecipientAuthorizer(NotificationRepository(db)), lambda _config: fake)
        return LiveSmsSender(provider)

    app.dependency_overrides[get_live_sms_sender] = override
    with TestClient(app) as client:
        yield client


@pytest.fixture
def fake() -> FakeTwilio:
    return FakeTwilio()


@pytest.fixture
def live(fake: FakeTwilio) -> Iterator[TestClient]:
    yield from live_client(fake)


def add_recipient(consent: bool = True, verified: bool = True, opted_out: bool = False, phone: str = FAKE_PHONE, code: str = "TR-00000001") -> str:
    with SessionLocal() as session:
        session.add(TestRecipient(
            recipient_code=code, label="Test person", phone_e164=phone,
            consent_recorded_at=DATASET_REFERENCE_TIME if consent else None, consent_statement="agreed (test)" if consent else None,
            verified_at=DATASET_REFERENCE_TIME if verified else None, opted_out_at=DATASET_REFERENCE_TIME if opted_out else None,
        ))
        session.commit()
    return code


def payload(code: str = "TR-00000001", key: str = "live-test-0001", **overrides: object) -> dict:
    return {"recipient_code": code, "template_id": "CONNECTIVITY_TEST", "idempotency_key": key, "confirm_live_send": True, **overrides}


def rows() -> list[Notification]:
    with SessionLocal() as session:
        return list(session.query(Notification).all())


# ---- configuration ------------------------------------------------------------------------------------


def test_demo_is_the_default_and_needs_no_credentials() -> None:
    settings = Settings(_env_file=None)
    assert settings.messaging_mode == "DEMO" and settings.twilio_account_sid is None and settings.twilio_auth_token is None
    assert TwilioConfig.from_settings(settings) is None


def test_env_example_is_demo_with_empty_placeholders_only() -> None:
    lines = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8").splitlines()
    values = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines if re.match(r"^[A-Z_]+=", line)}
    assert values["MESSAGING_MODE"] == "DEMO"
    assert all(values[k] == "" for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TWILIO_STATUS_CALLBACK_URL"))
    assert Settings(_env_file=None, **{k.lower(): v for k, v in values.items() if k.startswith(("TWILIO", "MESSAGING"))}).messaging_mode == "DEMO"


def test_live_mode_with_missing_or_invalid_credentials_fails_without_echoing_values() -> None:
    secret = "super-secret-token-value-123"
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, messaging_mode="LIVE", twilio_account_sid="not-a-sid", twilio_auth_token=secret, twilio_from_number="12345")
    message = str(caught.value) + repr(caught.value)
    assert "TWILIO_ACCOUNT_SID" in message and "TWILIO_FROM_NUMBER" in message and "TWILIO_AUTH_TOKEN" not in message
    assert secret not in message and "not-a-sid" not in message and "12345" not in message
    with pytest.raises(ValidationError) as empty:
        Settings(_env_file=None, messaging_mode="LIVE")
    assert all(name in str(empty.value) for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))
    with pytest.raises(ValidationError):
        Settings(_env_file=None, messaging_mode="MAYBE")


def test_valid_live_configuration_and_redaction() -> None:
    settings = Settings(_env_file=None, messaging_mode="live", twilio_account_sid=FAKE_SID, twilio_auth_token=FAKE_TOKEN,
                        twilio_from_number=FAKE_FROM, twilio_status_callback_url="https://example.invalid/status")
    config = TwilioConfig.from_settings(settings)
    assert settings.messaging_mode == "LIVE" and config is not None and config.timeout_seconds == 10.0
    assert FAKE_TOKEN not in repr(config) and FAKE_TOKEN not in repr(settings) and FAKE_TOKEN not in str(settings.twilio_auth_token)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, twilio_status_callback_url="http://insecure.invalid/x")


def test_client_factory_uses_the_official_client_with_a_timeout() -> None:
    client = default_client_factory(CONFIG)  # constructing a client makes no network call
    assert client.__class__.__module__.startswith("twilio.rest") and client.http_client.timeout == CONFIG.timeout_seconds


def test_demo_mode_refuses_live_sending(client: TestClient) -> None:
    add_recipient()
    response = client.post(URL, json=payload())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "LIVE_MODE_DISABLED" and rows() == []


# ---- a valid, authorised test send ----------------------------------------------------------------------


def test_authorised_send_records_provider_acceptance_not_delivery(live: TestClient, fake: FakeTwilio) -> None:
    code = add_recipient()
    response = live.post(URL, json=payload(code, blood_request_code=DEMO_REQUEST_CODE))
    assert response.status_code == 201
    body = response.json()
    note = body["notification"]
    assert body["outcome"] == "RECORDED" and body["provider_accepted"] is True and body["delivery_confirmed"] is False
    assert note["mode"] == "LIVE" and note["status"] == "SENT" and note["channel"] == "SMS"
    assert note["provider_message_id"] == FAKE_MESSAGE_SID and note["failure_code"] is None
    assert note["recipient_ref"] == code and note["blood_request_code"] == DEMO_REQUEST_CODE
    assert "not a delivery confirmation" in note["delivery_note"] and "not a delivery confirmation" in body["note"]
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["to"] == FAKE_PHONE and call["from_"] == FAKE_FROM and call["body"] == render_template("CONNECTIVITY_TEST", DEMO_REQUEST_CODE)[1]
    assert "status_callback" not in call
    assert FAKE_TOKEN not in response.text and FAKE_PHONE not in response.text and FAKE_SID not in response.text
    stored = live.get(f"/api/v1/notifications/{note['notification_id']}")
    assert stored.json() == note and FAKE_PHONE not in stored.text
    summary = live.get("/api/v1/notifications/summary").json()
    assert summary["by_status"]["SENT"] == 1 and summary["by_status"]["DELIVERED"] == 0 and summary["by_mode"]["LIVE"] == 1


def test_callback_url_is_passed_only_when_configured(fake: FakeTwilio) -> None:
    add_recipient()
    config = TwilioConfig(FAKE_SID, FAKE_TOKEN, FAKE_FROM, "https://example.invalid/status", 5.0)
    for client in live_client(fake, config):
        assert client.post(URL, json=payload()).status_code == 201
    assert fake.calls[0]["status_callback"] == "https://example.invalid/status"


# ---- authorisation and validation -----------------------------------------------------------------------


@pytest.mark.parametrize("kwargs,code", [
    ({"consent": False}, "CONSENT_MISSING"), ({"verified": False}, "RECIPIENT_NOT_VERIFIED"),
    ({"opted_out": True}, "OPTED_OUT"), ({"phone": "98 66 not a number"}, "INVALID_PHONE"), ({"phone": "+0123456"}, "INVALID_PHONE"),
])
def test_unauthorised_recipients_are_refused_before_anything_is_sent(live: TestClient, fake: FakeTwilio, kwargs: dict, code: str) -> None:
    add_recipient(**kwargs)
    response = live.post(URL, json=payload())
    assert response.status_code == 403 and response.json()["detail"]["code"] == code
    assert fake.calls == [] and rows() == []  # no provider call and not even an attempt record
    assert FAKE_PHONE not in response.text


def test_opt_out_beats_valid_consent(live: TestClient, fake: FakeTwilio) -> None:
    code = add_recipient()
    assert live.post(URL, json=payload(code, key="first-key-0001")).status_code == 201
    with SessionLocal() as session:
        session.execute(text("UPDATE test_recipients SET opted_out_at = :t"), {"t": DATASET_REFERENCE_TIME})
        session.commit()
    assert live.post(URL, json=payload(code, key="second-key-0002")).json()["detail"]["code"] == "OPTED_OUT"
    assert len(fake.calls) == 1


def test_unknown_recipient_is_refused(live: TestClient, fake: FakeTwilio) -> None:
    response = live.post(URL, json=payload("TR-DEADBEEF"))
    assert response.status_code == 403 and response.json()["detail"]["code"] == "UNKNOWN_RECIPIENT" and fake.calls == []


@pytest.mark.parametrize("override", [
    {"recipient_code": FAKE_PHONE}, {"recipient_code": "DON-00001"}, {"recipient_code": "TR-ZZZZZZZZ"},
    {"template_id": "FREE_TEXT"}, {"confirm_live_send": False}, {"idempotency_key": "short"}, {"idempotency_key": "has space in key"},
    {"blood_request_code": "bad code!"},
    {"phone": FAKE_PHONE}, {"to": FAKE_PHONE}, {"body": "Free text"}, {"recipients": ["TR-00000001"]},  # unknown fields are refused
])
def test_invalid_or_unapproved_requests_are_rejected(live: TestClient, fake: FakeTwilio, override: dict) -> None:
    add_recipient()
    assert live.post(URL, json={**payload(), **override}).status_code == 422
    assert fake.calls == [] and rows() == []


def test_confirmation_is_required(live: TestClient, fake: FakeTwilio) -> None:
    add_recipient()
    body = payload()
    del body["confirm_live_send"]
    assert live.post(URL, json=body).status_code == 422 and fake.calls == []


def test_unknown_request_context_is_refused(live: TestClient, fake: FakeTwilio) -> None:
    add_recipient()
    response = live.post(URL, json=payload(blood_request_code="REQ-99999"))
    assert response.status_code == 422 and response.json()["detail"]["code"] == "UNKNOWN_REQUEST" and fake.calls == [] and rows() == []


def test_provider_refuses_any_text_that_is_not_an_approved_template(fake: FakeTwilio) -> None:
    add_recipient()
    title, body = render_template("CONNECTIVITY_TEST", None)
    with SessionLocal() as session:
        provider = TwilioSmsProvider(CONFIG, NotificationService(NotificationRepository(session), DATASET_REFERENCE_TIME),
                                     RecipientAuthorizer(NotificationRepository(session)), lambda _c: fake)
        def attempt(**overrides: object) -> None:
            data = dict(event_type=NotificationEventType.SYSTEM_NOTICE, recipient_role=NotificationRecipientRole.COORDINATOR,
                        recipient_ref="TR-00000001", channel=NotificationChannel.SMS, title=title, body=body, idempotency_key="direct-key-0001")
            provider.deliver(NotificationCreate(**{**data, **overrides}))  # type: ignore[arg-type]

        for bad in ({"body": "Please call me back about the blood request"}, {"title": "Urgent"}):
            with pytest.raises(SendNotAuthorized) as caught:
                attempt(**bad)
            assert caught.value.code == "MESSAGE_NOT_APPROVED"
        for bad in ({"channel": NotificationChannel.WHATSAPP}, {"recipient_role": NotificationRecipientRole.DONOR, "recipient_ref": "DON-00001"},
                    {"idempotency_key": None}):
            with pytest.raises(SendNotAuthorized) as caught:
                attempt(**bad)
            assert caught.value.code == "INVALID_SEND_REQUEST"
    assert fake.calls == [] and rows() == []


def test_synthetic_donors_and_patients_can_never_be_live_recipients(live: TestClient, fake: FakeTwilio) -> None:
    for ref in ("DON-00001", "PAT-0001"):
        assert live.post(URL, json=payload(ref)).status_code == 422
    assert fake.calls == [] and live.post("/api/v1/notifications", json={
        "event_type": "DONOR_OUTREACH", "recipient_role": "DONOR", "recipient_ref": "DON-00001", "channel": "SMS", "mode": "LIVE",
        "title": "t", "body": "b"}).status_code == 422


def test_per_recipient_send_limit(live: TestClient, fake: FakeTwilio) -> None:
    code = add_recipient()
    for n in range(MAX_TEST_SENDS_PER_RECIPIENT):
        assert live.post(URL, json=payload(code, key=f"limit-key-{n:04d}")).status_code == 201
    over = live.post(URL, json=payload(code, key="limit-key-over"))
    assert over.status_code == 429 and over.json()["detail"]["code"] == "SEND_LIMIT_REACHED"
    assert len(fake.calls) == MAX_TEST_SENDS_PER_RECIPIENT


# ---- provider failures ---------------------------------------------------------------------------------


def test_provider_rejection_is_failed_not_sent() -> None:
    error = TwilioRestException(400, "/Messages", f"The number {FAKE_PHONE} is unverified", code=21608)
    fake = FakeTwilio(raises=error)
    add_recipient()
    for client in live_client(fake):
        response = client.post(URL, json=payload())
        assert response.status_code == 502
        body = response.json()
        note = body["notification"]
        assert body["outcome"] == "FAILED" and body["provider_accepted"] is False and body["delivery_confirmed"] is False
        assert note["status"] == "FAILED" and note["failure_code"] == "TWILIO_21608" and note["provider_message_id"] is None
        assert "not verified" in note["failure_message"] and FAKE_PHONE not in response.text and "unverified" not in response.text
        repeat = client.post(URL, json=payload())
        assert repeat.status_code == 200 and repeat.json()["outcome"] == "DUPLICATE"
    assert len(fake.calls) == 1  # a repeat of the key never calls the provider again, even after a failure


@pytest.mark.parametrize("error", [
    requests.exceptions.ConnectTimeout("timed out"), requests.exceptions.ReadTimeout("read timed out"),
    requests.exceptions.ConnectionError("reset"), TwilioRestException(503, "/Messages", "unavailable"), RuntimeError("boom"),
])
def test_network_failure_or_timeout_is_uncertain_and_never_resent(error: BaseException) -> None:
    fake = FakeTwilio(raises=error)
    add_recipient()
    for client in live_client(fake):
        response = client.post(URL, json=payload())
        body = response.json()
        assert response.status_code == 504 and body["outcome"] == "UNCERTAIN" and body["provider_accepted"] is False
        assert body["notification"]["status"] == "UNCERTAIN" and body["notification"]["provider_message_id"] is None
        assert "may or may not" in body["notification"]["delivery_note"]
        assert str(error) not in response.text
        again = client.post(URL, json=payload())
        assert again.status_code == 200 and again.json()["notification"]["status"] == "UNCERTAIN"
    assert len(fake.calls) == 1


@pytest.mark.parametrize("result,status", [
    (SimpleNamespace(status="queued"), "UNCERTAIN"), (SimpleNamespace(sid="", status="queued"), "UNCERTAIN"),
    (SimpleNamespace(sid=FAKE_MESSAGE_SID, status="failed"), "FAILED"), (SimpleNamespace(sid=FAKE_MESSAGE_SID, status="accepted"), "SENT"),
])
def test_provider_responses_are_interpreted_conservatively(result: object, status: str) -> None:
    fake = FakeTwilio(result=result)
    add_recipient()
    for client in live_client(fake):
        note = client.post(URL, json=payload()).json()["notification"]
        assert note["status"] == status
        assert (note["provider_message_id"] is not None) == (status in ("SENT", "FAILED") and bool(getattr(result, "sid", "")))
        assert note["status"] != "DELIVERED"


def test_error_classification_never_uses_provider_text() -> None:
    status, code, message = classify_error(TwilioRestException(400, "/Messages", f"to {FAKE_PHONE} failed", code=21211))
    assert (status, code) == (NotificationStatus.FAILED, "TWILIO_21211") and FAKE_PHONE not in message
    assert classify_error(TwilioRestException(401, "/Messages", "auth", code=20003))[0] is NotificationStatus.FAILED
    assert classify_error(TwilioRestException(400, "/Messages", "odd", code=99999))[2] == "The provider rejected the request."
    assert classify_error(TimeoutError("x"))[0] is NotificationStatus.UNCERTAIN


# ---- duplicates and concurrency --------------------------------------------------------------------------


def test_duplicate_submission_sends_once(live: TestClient, fake: FakeTwilio) -> None:
    code = add_recipient()
    first = live.post(URL, json=payload(code))
    second = live.post(URL, json=payload(code))
    assert (first.status_code, second.status_code) == (201, 200) and second.json()["outcome"] == "DUPLICATE"
    assert second.json()["notification"] == first.json()["notification"] and len(fake.calls) == 1 and len(rows()) == 1
    assert "nothing was sent" in second.json()["note"]


def test_key_reuse_for_something_else_conflicts(live: TestClient, fake: FakeTwilio) -> None:
    code = add_recipient()
    add_recipient(code="TR-00000002", phone="+15550100456")
    assert live.post(URL, json=payload(code)).status_code == 201
    other = live.post(URL, json=payload("TR-00000002"))  # same key, different recipient
    assert other.status_code == 409 and other.json()["detail"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert live.post(URL, json=payload(code, blood_request_code=DEMO_REQUEST_CODE)).status_code == 409  # different content
    assert len(fake.calls) == 1


def test_a_demo_notification_key_cannot_trigger_a_live_send(live: TestClient, fake: FakeTwilio) -> None:
    add_recipient()
    title, body = render_template("CONNECTIVITY_TEST", None)
    assert live.post("/api/v1/notifications", json={
        "event_type": "SYSTEM_NOTICE", "recipient_role": "COORDINATOR", "recipient_ref": "TR-00000001", "channel": "SMS",
        "title": title, "body": body, "idempotency_key": "shared-key-0001"}).status_code == 201
    response = live.post(URL, json=payload(key="shared-key-0001"))
    assert response.status_code == 409 and fake.calls == []


def test_concurrent_attempts_cannot_both_send(fake: FakeTwilio) -> None:
    """Two submissions race: the second one's duplicate check misses (as it would in a real race) and the unique
    idempotency key stops its insert, so only the first reaches the provider."""
    add_recipient()
    with SessionLocal() as session:
        repo = NotificationRepository(session)
        service = NotificationService(repo, DATASET_REFERENCE_TIME)
        provider = TwilioSmsProvider(CONFIG, service, RecipientAuthorizer(repo), lambda _c: fake)
        title, body = render_template("CONNECTIVITY_TEST", None)
        request = NotificationCreate(
            event_type=NotificationEventType.SYSTEM_NOTICE, recipient_role=NotificationRecipientRole.COORDINATOR,
            recipient_ref="TR-00000001", channel=NotificationChannel.SMS, title=title, body=body, idempotency_key="race-key-0001")
        first = provider.deliver(request)
        real_lookup = repo.get_by_idempotency_key
        misses = {"left": 1}

        def blind_once(key: str):  # type: ignore[no-untyped-def]
            if misses["left"]:
                misses["left"] -= 1
                return None
            return real_lookup(key)

        repo.get_by_idempotency_key = blind_once  # type: ignore[method-assign]
        second = provider.deliver(request)
    assert first.outcome.value == "RECORDED" and second.outcome.value == "DUPLICATE"
    assert len(fake.calls) == 1 and len(rows()) == 1


def test_real_concurrent_attempts_send_at_most_once(tmp_path: Path) -> None:
    """Eight threads, each with its OWN connection to a file database, submit the same live send at the same moment.
    The unique idempotency key lets exactly one insert its attempt record, so exactly one calls the provider."""
    import threading

    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.session import create_db_engine

    engine = create_db_engine(f"sqlite:///{(tmp_path / 'race.db').as_posix()}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with maker() as session:
        session.add(TestRecipient(recipient_code="TR-00000001", label="Test", phone_e164=FAKE_PHONE,
                                  consent_recorded_at=DATASET_REFERENCE_TIME, verified_at=DATASET_REFERENCE_TIME))
        session.commit()
    fake = FakeTwilio(delay=0.3)
    title, body = render_template("CONNECTIVITY_TEST", None)
    request = NotificationCreate(
        event_type=NotificationEventType.SYSTEM_NOTICE, recipient_role=NotificationRecipientRole.COORDINATOR,
        recipient_ref="TR-00000001", channel=NotificationChannel.SMS, title=title, body=body, idempotency_key="thread-key-0001")
    barrier, outcomes = threading.Barrier(8), []

    def attempt() -> None:
        with maker() as session:
            repo = NotificationRepository(session)
            provider = TwilioSmsProvider(CONFIG, NotificationService(repo, DATASET_REFERENCE_TIME), RecipientAuthorizer(repo), lambda _c: fake)
            barrier.wait()
            try:
                outcomes.append(provider.deliver(request).outcome.value)
            except Exception as error:  # noqa: BLE001 - a lock timeout or conflict is a refusal, never a second send
                outcomes.append(type(error).__name__)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with maker() as session:
        stored = session.query(Notification).all()
    engine.dispose()
    assert len(fake.calls) == 1 and outcomes.count("RECORDED") == 1, outcomes
    assert len(stored) == 1 and stored[0].status is NotificationStatus.SENT and stored[0].provider_message_id == FAKE_MESSAGE_SID


# ---- status integrity --------------------------------------------------------------------------------------


def test_delivered_cannot_be_recorded_without_trusted_evidence(live: TestClient) -> None:
    add_recipient()
    live.post(URL, json=payload())
    with SessionLocal() as session:
        service = NotificationService(NotificationRepository(session), DATASET_REFERENCE_TIME)
        sent = rows()[0].notification_code
        for status in (NotificationStatus.DELIVERED, NotificationStatus.SENT, NotificationStatus.CANCELLED, NotificationStatus.QUEUED):
            with pytest.raises(NotificationConflict):
                service.record_live_outcome(sent, status, provider_message_id="SM" + "2" * 32)  # already recorded: not QUEUED any more
    assert rows()[0].status is NotificationStatus.SENT


def test_outcome_recording_rules() -> None:
    add_recipient()
    with SessionLocal() as session:
        service = NotificationService(NotificationRepository(session), DATASET_REFERENCE_TIME)
        title, body = render_template("CONNECTIVITY_TEST", None)
        queued, _ = service.create_live_attempt(NotificationCreate(
            event_type=NotificationEventType.SYSTEM_NOTICE, recipient_role=NotificationRecipientRole.COORDINATOR,
            recipient_ref="TR-00000001", channel=NotificationChannel.SMS, title=title, body=body, idempotency_key="rules-key-0001"))
        assert queued.status is NotificationStatus.QUEUED and queued.mode.value == "LIVE" and queued.provider_message_id is None
        with pytest.raises(NotificationConflict):
            service.record_live_outcome(queued.notification_id, NotificationStatus.DELIVERED, provider_message_id=FAKE_MESSAGE_SID)
        with pytest.raises(NotificationConflict):
            service.record_live_outcome(queued.notification_id, NotificationStatus.SENT)  # no provider id: never invented
        done = service.record_live_outcome(queued.notification_id, NotificationStatus.SENT, provider_message_id=FAKE_MESSAGE_SID)
        assert done.status is NotificationStatus.SENT and done.provider_message_id == FAKE_MESSAGE_SID


def test_demo_notifications_can_never_become_sent_or_delivered(client: TestClient) -> None:
    created = client.post("/api/v1/notifications", json={
        "event_type": "SYSTEM_NOTICE", "recipient_role": "SYSTEM", "title": "Demo", "body": "Demo message"}).json()
    assert created["mode"] == "DEMO" and created["status"] == "SIMULATED"
    with SessionLocal() as session:
        service = NotificationService(NotificationRepository(session), DATASET_REFERENCE_TIME)
        row = session.query(Notification).one()
        for status in (NotificationStatus.SENT, NotificationStatus.DELIVERED, NotificationStatus.FAILED):
            with pytest.raises(NotificationConflict):
                service.record_live_outcome(row.notification_code, status, provider_message_id=FAKE_MESSAGE_SID)
        row.status = NotificationStatus.DELIVERED  # even a direct write is refused by the database
        with pytest.raises(Exception):
            session.commit()
        session.rollback()
    for body in ({"status": "SENT"}, {"status": "DELIVERED"}, {"mode": "LIVE"}, {"provider_message_id": FAKE_MESSAGE_SID}):
        assert client.post("/api/v1/notifications", json={
            "event_type": "SYSTEM_NOTICE", "recipient_role": "SYSTEM", "title": "x", "body": "y", **body}).status_code == 422


def test_only_the_live_test_endpoint_can_cause_a_provider_call() -> None:
    schema = create_app().openapi()
    writers = sorted(f"{method.upper()} {path}" for path, ops in schema["paths"].items() for method in ops if method in ("post", "put", "patch", "delete"))
    assert [w for w in writers if "test-sms" in w] == ["POST /api/v1/notifications/test-sms"]
    assert not any(method == "get" for method in schema["paths"]["/api/v1/notifications/test-sms"])


# ---- nothing else sends ------------------------------------------------------------------------------------


def test_reports_and_demo_workflows_never_call_the_provider(live: TestClient, fake: FakeTwilio) -> None:
    add_recipient()
    code = DEMO_REQUEST_CODE
    for url, params in [(f"/api/v1/requests/{code}/cascade", {"seed": 25}), (f"/api/v1/requests/{code}/matching", {}),
                        (f"/api/v1/requests/{code}/failures/autopsy", {}), (f"/api/v1/requests/{code}/self-healing", {"seed": 25}),
                        (f"/api/v1/requests/{code}/learning", {"seed": 25}), ("/api/v1/learning/report", {}),
                        ("/api/v1/notifications", {}), ("/api/v1/notifications/summary", {}), ("/api/v1/requests", {"search": code})]:
        assert live.get(url, params=params).status_code == 200
    report = live.post(f"/api/v1/requests/{code}/cascade/notifications", params={"seed": 25})
    assert report.status_code == 201  # the cascade events stay DEMO even when the backend is configured LIVE
    items = live.get("/api/v1/notifications", params={"page_size": 100}).json()["items"]
    assert items and all(i["mode"] == "DEMO" and i["status"] == "SIMULATED" for i in items)
    assert fake.calls == []


def test_existing_demo_notifications_still_work(client: TestClient) -> None:
    body = client.post("/api/v1/notifications", json={
        "event_type": "DONOR_OUTREACH", "recipient_role": "DONOR", "recipient_ref": "DON-00001", "title": "Hello", "body": "A demo message."})
    assert body.status_code == 201 and body.json()["mode"] == "DEMO" and body.json()["status"] == "SIMULATED"
    assert client.get("/api/v1/notifications/summary").json()["by_mode"]["LIVE"] == 0


# ---- secrets ----------------------------------------------------------------------------------------------


def test_no_secrets_phone_numbers_or_bodies_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    body_text = render_template("CONNECTIVITY_TEST", None)[1]
    cases = [FakeTwilio(), FakeTwilio(raises=TwilioRestException(400, "/Messages", f"bad {FAKE_PHONE}", code=21211)),
             FakeTwilio(raises=requests.exceptions.ReadTimeout(f"read timed out sending to {FAKE_PHONE}"))]
    for number, fake in enumerate(cases):
        add_recipient(code=f"TR-0000000{number}", phone=FAKE_PHONE)
        for client in live_client(fake):
            response = client.post(URL, json=payload(f"TR-0000000{number}", key=f"log-key-000{number}"))
            assert FAKE_TOKEN not in response.text and FAKE_PHONE not in response.text
    logs = caplog.text
    for sensitive in (FAKE_TOKEN, FAKE_SID, FAKE_PHONE, body_text):
        assert sensitive not in logs
    assert "live sms attempt NTF-" in logs  # the code of the attempt is logged, nothing more


def test_secrets_are_not_in_source_docs_or_frontend() -> None:
    root = Path(__file__).resolve().parents[2]
    patterns = [re.compile(r"\bAC[0-9a-fA-F]{32}\b"), re.compile(r"(?i)auth_?token\s*[=:]\s*['\"]?[0-9a-f]{32}")]
    scanned = 0
    for folder in ("backend/app", "frontend/src", "docs"):
        for path in (root / folder).rglob("*"):
            if path.suffix in (".py", ".ts", ".tsx", ".md", ".css", ".json") and path.is_file():
                text_ = path.read_text(encoding="utf-8", errors="ignore")
                scanned += 1
                assert not any(p.search(text_) for p in patterns), path
    for name in ("README.md", ".env.example"):
        assert not any(p.search((root / name).read_text(encoding="utf-8")) for p in patterns), name
    assert scanned > 50
    assert not list((root / "frontend" / "src").rglob("*")) or not any(
        re.search(r"(?i)twilio|TWILIO_|auth_token", p.read_text(encoding="utf-8", errors="ignore"))
        for p in (root / "frontend" / "src").rglob("*") if p.is_file() and p.suffix in (".ts", ".tsx"))
    gitignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore and ".env.*" in gitignore and "!.env.example" in gitignore
    assert not (root / "backend" / ".env").exists() or ".env" in gitignore
    dist = root / "frontend" / "dist"
    if dist.exists():  # a built bundle must not carry any backend setting name or credential shape
        for path in dist.rglob("*.js"):
            bundle = path.read_text(encoding="utf-8", errors="ignore")
            assert not re.search(r"TWILIO_|(?i:auth_token)|\bAC[0-9a-fA-F]{32}\b", bundle), path


def test_settings_are_not_exposed_by_the_api(client: TestClient) -> None:
    for path in ("/api/v1/system/status", "/api/v1/system/dataset-stats", "/health", "/openapi.json"):
        response = client.get(path)
        if response.status_code == 200:
            assert not re.search(r"TWILIO_AUTH_TOKEN|twilio_auth_token|\bAC[0-9a-fA-F]{32}\b", response.text), path


# ---- the operator tool ---------------------------------------------------------------------------------------


def test_operator_tool_registers_authorises_and_suppresses(capsys: pytest.CaptureFixture[str], live: TestClient, fake: FakeTwilio) -> None:
    assert recipient_cli.main(["add", "--label", "Owner", "--phone", "+15550100777"]) == 0
    incomplete = capsys.readouterr().out
    assert "NOT authorised yet" in incomplete and "+15550100777" not in incomplete
    code = re.search(r"TR-[0-9A-F]{8}", incomplete).group(0)  # type: ignore[union-attr]
    assert live.post(URL, json=payload(code, key="cli-key-00001")).json()["detail"]["code"] == "CONSENT_MISSING"

    assert recipient_cli.main(["add", "--label", "Owner 2", "--phone", "+15550100888", "--consent", "Agreed by email (test)", "--verified"]) == 0
    ready = capsys.readouterr().out
    assert "Authorised for controlled test sends" in ready and "+15550100888" not in ready
    code2 = re.search(r"TR-[0-9A-F]{8}", ready).group(0)  # type: ignore[union-attr]
    assert live.post(URL, json=payload(code2, key="cli-key-00002")).status_code == 201 and fake.calls[0]["to"] == "+15550100888"

    assert recipient_cli.main(["list"]) == 0
    listing = capsys.readouterr().out
    assert code in listing and code2 in listing and "+15550100888" not in listing and "[authorised]" in listing

    assert recipient_cli.main(["opt-out", code2]) == 0
    assert "+1555" not in capsys.readouterr().out
    assert live.post(URL, json=payload(code2, key="cli-key-00003")).json()["detail"]["code"] == "OPTED_OUT"
    assert len(fake.calls) == 1
    assert recipient_cli.main(["add", "--label", "x", "--phone", "98661"]) == 2
    assert recipient_cli.main(["opt-out", "nonsense"]) == 2


def test_get_settings_in_the_test_environment_is_demo() -> None:
    assert get_settings().messaging_mode == "DEMO" and DATA_NOTICE
    assert json.loads(json.dumps({"ok": True}))["ok"]
