"""Live SMS (Phase 10E.1): one controlled, explicitly authorised test message through Twilio.

DEMO is the default and sends nothing. Live sending exists only when the backend is configured with
MESSAGING_MODE=LIVE and valid Twilio credentials, and even then a message goes out only if EVERY check in
`RecipientAuthorizer` passes for a recipient an operator registered, verified and recorded consent for:

    recipient exists (by code; clients never supply a phone number or a recipient list)
    · phone is valid E.164 · number verified · consent recorded · not opted out · per-recipient cap not reached
    · the message is exactly an approved template (clients cannot supply free text)
    · the request context, if given, exists · an idempotency key is supplied

SEND-ATTEMPT STRATEGY (a duplicate submission can never send twice)
    1. A LIVE notification row is committed as QUEUED, keyed by the idempotency key, BEFORE the provider is
       called. The key is unique, so of two concurrent submissions only one inserts a row and sends.
    2. The provider is called once, with no automatic retries.
    3. The outcome is recorded: SENT (the provider ACCEPTED the request; it is not a delivery confirmation and its
       SID is stored), FAILED (a definite rejection) or UNCERTAIN (a timeout or server error: it may or may not
       have been sent, and it is never resent automatically).
    A repeat of a key returns the stored record and never calls the provider, whatever its status. Exactly-once
    delivery cannot be guaranteed across a crash or a network failure: if the process dies after the provider
    accepted but before step 3, the row stays QUEUED and must be checked against the provider's logs.

DELIVERED is never set here: it needs trusted evidence (a provider status callback), which is not implemented.
Credentials, phone numbers and message bodies are never logged, stored in error messages or returned.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.core.config import E164_PATTERN, Settings
from app.models import TestRecipient
from app.models.enums import (
    NotificationChannel,
    NotificationEventType,
    NotificationMode,
    NotificationRecipientRole,
    NotificationStatus,
)
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import LiveTestSmsRequest, NotificationCreate, RECIPIENT_CODE
from app.services.notification_provider import DeliveryOutcome, NotificationProvider, ProviderResult
from app.services.notifications import InvalidNotificationReference, NotificationService

logger = logging.getLogger(__name__)

MAX_TEST_SENDS_PER_RECIPIENT = 5  # attempts per registered test recipient, in total
APPROVED_TEMPLATES = ("CONNECTIVITY_TEST",)

# Safe, generic explanations for the provider errors we recognise. The provider's own message text can
# contain the recipient's number, so it is never stored or returned.
SAFE_FAILURES = {
    20003: "The provider rejected the account credentials.",
    21211: "The provider rejected the recipient number as invalid.",
    21408: "The account is not permitted to send to that region.",
    21608: "The recipient number is not verified for this (trial) account.",
    21610: "The recipient has opted out at the provider.",
    21614: "The recipient number is not a valid mobile number.",
}
UNCERTAIN_MESSAGE = (
    "The request may or may not have reached the provider. It will not be resent automatically; "
    "check the provider's logs before trying again with a new idempotency key."
)
# A create-message response status that means the provider took the request (not that anything was delivered).
ACCEPTED_STATES = frozenset({"queued", "accepted", "scheduled", "sending", "sent"})


class LiveSmsDisabled(Exception):
    """MESSAGING_MODE is DEMO: live sending is switched off."""


class SendNotAuthorized(Exception):
    """A safety check failed; nothing was sent. `code` is stable and safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def render_template(template_id: str, blood_request_code: str | None) -> tuple[str, str]:
    """The only message texts that may be sent live."""
    if template_id not in APPROVED_TEMPLATES:
        raise SendNotAuthorized("MESSAGE_NOT_APPROVED", "That message template is not approved for live sending.")
    reference = f" (ref {blood_request_code})" if blood_request_code else ""
    return (
        "Controlled test SMS",
        f"Carbon Copy test{reference}: a controlled messaging test, not a real request. No action needed. "
        "Synthetic demo data, not for clinical use.",
    )


@dataclass(frozen=True)
class TwilioConfig:
    account_sid: str
    auth_token: str
    from_number: str
    status_callback_url: str | None
    timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "TwilioConfig | None":
        """None unless MESSAGING_MODE=LIVE (Settings already guarantees the credentials are present and valid)."""
        if settings.messaging_mode != "LIVE":
            return None
        assert settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number
        return cls(
            settings.twilio_account_sid, settings.twilio_auth_token.get_secret_value(), settings.twilio_from_number,
            settings.twilio_status_callback_url, settings.twilio_timeout_seconds,
        )

    def __repr__(self) -> str:  # never print credentials, even by accident
        return "TwilioConfig(<redacted>)"


def default_client_factory(config: TwilioConfig) -> Any:
    """The official Twilio client with a hard network timeout and no automatic retries."""
    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client

    logging.getLogger("twilio.http_client").setLevel(logging.WARNING)  # its DEBUG logs include numbers and bodies
    return Client(config.account_sid, config.auth_token, http_client=TwilioHttpClient(timeout=config.timeout_seconds))


def classify_error(error: Exception) -> tuple[NotificationStatus, str, str]:
    """(status, failure_code, safe message). Never uses the exception's own text."""
    try:
        from twilio.base.exceptions import TwilioRestException
    except ImportError:  # pragma: no cover - the SDK is a declared dependency
        TwilioRestException = ()  # type: ignore[assignment,misc]
    if isinstance(error, TwilioRestException):
        http_status = int(error.status or 0)
        if http_status >= 500 or http_status == 0:
            return NotificationStatus.UNCERTAIN, f"TWILIO_HTTP_{http_status}", UNCERTAIN_MESSAGE
        code = error.code
        return (
            NotificationStatus.FAILED,
            f"TWILIO_{code}" if code else f"TWILIO_HTTP_{http_status}",
            SAFE_FAILURES.get(int(code) if code else 0, "The provider rejected the request."),
        )
    return NotificationStatus.UNCERTAIN, "PROVIDER_OUTCOME_UNKNOWN", UNCERTAIN_MESSAGE


class RecipientAuthorizer:
    def __init__(self, repository: NotificationRepository) -> None:
        self._repo = repository

    def authorize(self, request: NotificationCreate) -> TestRecipient:
        """Raises SendNotAuthorized unless this is a well-formed test send to an authorised recipient."""
        if (
            request.recipient_role is not NotificationRecipientRole.COORDINATOR
            or not request.recipient_ref or not RECIPIENT_CODE.fullmatch(request.recipient_ref)
            or request.channel is not NotificationChannel.SMS or not request.idempotency_key
        ):
            raise SendNotAuthorized("INVALID_SEND_REQUEST", "A live test SMS needs a test-recipient code, the SMS channel and an idempotency key.")
        if not any((request.title, request.body) == render_template(t, request.blood_request_code) for t in APPROVED_TEMPLATES):
            raise SendNotAuthorized("MESSAGE_NOT_APPROVED", "Only approved test templates can be sent live.")
        recipient = self._repo.get_test_recipient(request.recipient_ref)
        if recipient is None:
            raise SendNotAuthorized("UNKNOWN_RECIPIENT", "That recipient is not an authorised test recipient.")
        if not E164_PATTERN.fullmatch(recipient.phone_e164):
            raise SendNotAuthorized("INVALID_PHONE", "The recipient's phone number is not a valid E.164 number.")
        if recipient.opted_out_at is not None:
            raise SendNotAuthorized("OPTED_OUT", "The recipient has opted out; no message will be sent.")
        if recipient.consent_recorded_at is None:
            raise SendNotAuthorized("CONSENT_MISSING", "No consent to receive test messages is recorded for this recipient.")
        if recipient.verified_at is None:
            raise SendNotAuthorized("RECIPIENT_NOT_VERIFIED", "This recipient has not been verified by an operator.")
        if self._repo.count_live_attempts(recipient.recipient_code) >= MAX_TEST_SENDS_PER_RECIPIENT:
            raise SendNotAuthorized("SEND_LIMIT_REACHED", f"This test recipient already received {MAX_TEST_SENDS_PER_RECIPIENT} test attempts.")
        return recipient


class TwilioSmsProvider:
    """The live provider. Sends one SMS per call, only after every authorisation check has passed."""

    name = "twilio-sms"
    mode = NotificationMode.LIVE

    def __init__(
        self, config: TwilioConfig, service: NotificationService, authorizer: RecipientAuthorizer,
        client_factory: Callable[[TwilioConfig], Any] = default_client_factory,
    ) -> None:
        self._config = config
        self._service = service
        self._authorizer = authorizer
        self._client_factory = client_factory

    def deliver(self, request: NotificationCreate, *, commit: bool = True) -> ProviderResult:
        # `commit` is ignored on purpose: the attempt record must be durable before the network call.
        recipient = self._authorizer.authorize(request)
        try:
            queued, created = self._service.create_live_attempt(request)
        except InvalidNotificationReference as error:
            raise SendNotAuthorized("UNKNOWN_REQUEST", str(error)) from error
        if not created:  # a repeat of an idempotency key: never call the provider again
            return ProviderResult(DeliveryOutcome.DUPLICATE, queued)

        status, provider_id, failure_code, failure_message = self._send(recipient.phone_e164, request.body)
        recorded = self._service.record_live_outcome(
            queued.notification_id, status, provider_message_id=provider_id,
            failure_code=failure_code, failure_message=failure_message,
        )
        logger.info("live sms attempt %s finished with status %s", queued.notification_id, status.value)  # no number, no body
        outcome = {
            NotificationStatus.SENT: DeliveryOutcome.RECORDED, NotificationStatus.FAILED: DeliveryOutcome.FAILED,
        }.get(status, DeliveryOutcome.UNCERTAIN)
        return ProviderResult(outcome, recorded, error=failure_message)

    def _send(self, phone: str, body: str) -> tuple[NotificationStatus, str | None, str | None, str | None]:
        try:
            kwargs: dict[str, Any] = {"to": phone, "from_": self._config.from_number, "body": body}
            if self._config.status_callback_url:
                kwargs["status_callback"] = self._config.status_callback_url
            message = self._client_factory(self._config).messages.create(**kwargs)
            sid = getattr(message, "sid", None)
            state = str(getattr(message, "status", "") or "").lower()
        except Exception as error:  # noqa: BLE001 - any failure is classified; its text is never kept
            status, code, text = classify_error(error)
            return status, None, code, text
        if not isinstance(sid, str) or not sid:  # never invent a provider message id
            return NotificationStatus.UNCERTAIN, None, "PROVIDER_NO_MESSAGE_ID", UNCERTAIN_MESSAGE
        if state in ACCEPTED_STATES:
            return NotificationStatus.SENT, sid, None, None  # accepted by the provider, not delivered
        return NotificationStatus.FAILED, sid, "PROVIDER_REJECTED", f"The provider did not accept the message (status {state or 'unknown'})."

    def commit(self) -> None:  # every live attempt commits itself
        return None

    def rollback(self) -> None:
        return None


class LiveSmsSender:
    """Entry point for the controlled test send. `provider` is None in DEMO mode, which disables it."""

    def __init__(self, provider: NotificationProvider | None) -> None:
        self._provider = provider

    def send_test(self, request: LiveTestSmsRequest) -> ProviderResult:
        if self._provider is None:
            raise LiveSmsDisabled("Live SMS is disabled: the backend is in DEMO mode.")
        title, body = render_template(request.template_id, request.blood_request_code)
        try:
            data = NotificationCreate(
                event_type=NotificationEventType.SYSTEM_NOTICE, recipient_role=NotificationRecipientRole.COORDINATOR,
                recipient_ref=request.recipient_code, blood_request_code=request.blood_request_code,
                channel=NotificationChannel.SMS, title=title, body=body, idempotency_key=request.idempotency_key,
            )
        except ValidationError as error:
            raise SendNotAuthorized("MESSAGE_NOT_APPROVED", "The message did not pass content validation.") from error
        return self._provider.deliver(data)
