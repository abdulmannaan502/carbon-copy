"""Notification service (Phase 10A: record keeping only).

Creates, lists, reads and summarises notifications. It never sends anything: there is no provider, no
network call and no messaging client in this module, and DEMO notifications can only be SIMULATED or
QUEUED. A future provider layer will take QUEUED notifications and report real SENT / DELIVERED / FAILED
transitions for LIVE mode; until then a successful response proves nothing about delivery.

Timestamps use the injected operational clock, so behaviour is deterministic in tests and demos.
Synthetic demonstration data — not for clinical use.
"""

import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.models import Notification
from app.models.enums import (
    NotificationChannel,
    NotificationMode,
    NotificationRecipientRole,
    NotificationStatus,
)
from app.repositories.notification_repository import NotificationFilters, NotificationRepository
from app.schemas.common import Page, PageParams
from app.schemas.notification import (
    QUEUED_NOTE,
    SIMULATED_NOTE,
    NotificationCreate,
    NotificationOut,
    NotificationSummary,
)

# Fields that define "the same notification" for idempotent repeats.
_IDENTITY = ("event_type", "recipient_role", "recipient_ref", "blood_request_code", "channel", "title", "body")


class NotificationNotFound(LookupError):
    """No notification has this code."""


class NotificationConflict(ValueError):
    """The request conflicts with existing state (reused idempotency key, or an invalid read)."""


class InvalidNotificationReference(ValueError):
    """The recipient or request the notification refers to does not exist."""


def delivery_note(status: NotificationStatus, mode: NotificationMode) -> str:
    if mode is NotificationMode.LIVE:
        return {
            NotificationStatus.QUEUED: "Live send in progress or interrupted: no provider outcome is recorded. It is never resent automatically; check the provider's logs.",
            NotificationStatus.SENT: "Accepted by the SMS provider. This is not a delivery confirmation; the message may not have reached the phone.",
            NotificationStatus.FAILED: "The provider rejected the request; nothing was sent.",
            NotificationStatus.UNCERTAIN: "Outcome unknown: the request may or may not have reached the provider. It is never resent automatically.",
            NotificationStatus.DELIVERED: "Delivery confirmed by trusted provider status evidence.",
            NotificationStatus.CANCELLED: "Cancelled before sending.",
        }.get(status, f"{status.value.capitalize()}.")
    if mode is NotificationMode.DEMO and status is NotificationStatus.SIMULATED:
        return SIMULATED_NOTE
    if status is NotificationStatus.QUEUED:
        return QUEUED_NOTE
    if status in (NotificationStatus.FAILED, NotificationStatus.CANCELLED):
        return f"{status.value.capitalize()}: nothing was delivered."
    return f"{status.value.capitalize()}: reported by a provider."


def to_out(row: Notification) -> NotificationOut:
    return NotificationOut.model_validate({
        "notification_code": row.notification_code, "event_type": row.event_type,
        "recipient_role": row.recipient_role, "recipient_ref": row.recipient_ref,
        "blood_request_code": row.blood_request_code, "channel": row.channel, "mode": row.mode, "status": row.status,
        "title": row.title, "body": row.body, "read": row.read_at is not None, "read_at": row.read_at,
        "provider_message_id": row.provider_message_id, "failure_code": row.failure_code,
        "failure_message": row.failure_message, "idempotency_key": row.idempotency_key,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "delivery_note": delivery_note(row.status, row.mode),
    })


class NotificationService:
    def __init__(self, repository: NotificationRepository, now: datetime) -> None:
        self._repo = repository
        self._now = now

    # ---- create -----------------------------------------------------------------------------------

    def create(self, data: NotificationCreate, *, commit: bool = True) -> tuple[NotificationOut, bool]:
        """Returns (notification, created). A repeat of an idempotency key returns the original with
        created=False; reusing a key for a different notification raises NotificationConflict.
        With commit=False the row is only flushed: the caller owns the transaction and must call commit() or
        rollback(), which is how a set of notifications is stored all-or-nothing."""
        if data.idempotency_key:
            existing = self._repo.get_by_idempotency_key(data.idempotency_key)
            if existing is not None:
                return self._same_or_conflict(existing, data), False
        self._validate_references(data)
        row = Notification(
            notification_code=f"NTF-{uuid.uuid4().hex[:12].upper()}", event_type=data.event_type,
            recipient_role=data.recipient_role, recipient_ref=data.recipient_ref,
            blood_request_code=data.blood_request_code, channel=data.channel, mode=data.mode, status=data.status,
            title=data.title, body=data.body, idempotency_key=data.idempotency_key,
            created_at=self._now, updated_at=self._now,
        )
        try:
            self._repo.add(row, commit=commit)
        except IntegrityError:  # a concurrent request used the same idempotency key
            if not commit:  # the whole open set was rolled back with it
                raise NotificationConflict("A concurrent request recorded the same notification; nothing was stored.")
            existing = self._repo.get_by_idempotency_key(data.idempotency_key) if data.idempotency_key else None
            if existing is None:
                raise
            return self._same_or_conflict(existing, data), False
        return to_out(row), True

    @staticmethod
    def _same_or_conflict(existing: Notification, data: NotificationCreate) -> NotificationOut:
        if any(getattr(existing, field) != getattr(data, field) for field in _IDENTITY):
            raise NotificationConflict("This idempotency key was already used for a different notification.")
        return to_out(existing)

    def _validate_references(self, data: NotificationCreate) -> None:
        if data.recipient_role is NotificationRecipientRole.DONOR and not self._repo.donor_exists(data.recipient_ref or ""):
            raise InvalidNotificationReference(f"Unknown donor {data.recipient_ref}")
        if data.recipient_role is NotificationRecipientRole.PATIENT and not self._repo.patient_exists(data.recipient_ref or ""):
            raise InvalidNotificationReference(f"Unknown patient {data.recipient_ref}")
        if data.blood_request_code and not self._repo.request_exists(data.blood_request_code):
            raise InvalidNotificationReference(f"Unknown blood request {data.blood_request_code}")

    # ---- live sending (Phase 10E.1) -----------------------------------------------------------------

    def create_live_attempt(self, data: NotificationCreate) -> tuple[NotificationOut, bool]:
        """Commits a LIVE notification as QUEUED, before any provider call: the durable record of an attempt.
        The idempotency key is required and unique, so concurrent identical submissions cannot both insert (and
        so cannot both send). Returns (record, created); created=False means the key was already used."""
        assert data.idempotency_key, "a live attempt needs an idempotency key"
        existing = self._repo.get_by_idempotency_key(data.idempotency_key)
        if existing is not None:
            if existing.mode is not NotificationMode.LIVE:
                raise NotificationConflict("This idempotency key already belongs to a demo notification.")
            return self._same_or_conflict(existing, data), False
        if data.blood_request_code and not self._repo.request_exists(data.blood_request_code):
            raise InvalidNotificationReference(f"Unknown blood request {data.blood_request_code}")
        row = Notification(
            notification_code=f"NTF-{uuid.uuid4().hex[:12].upper()}", event_type=data.event_type,
            recipient_role=data.recipient_role, recipient_ref=data.recipient_ref,
            blood_request_code=data.blood_request_code, channel=data.channel, mode=NotificationMode.LIVE,
            status=NotificationStatus.QUEUED, title=data.title, body=data.body, idempotency_key=data.idempotency_key,
            created_at=self._now, updated_at=self._now,
        )
        try:
            self._repo.add(row)
        except IntegrityError:  # a concurrent submission won the insert
            existing = self._repo.get_by_idempotency_key(data.idempotency_key)
            if existing is None:
                raise
            return self._same_or_conflict(existing, data), False
        return to_out(row), True

    def record_live_outcome(
        self, notification_code: str, status: NotificationStatus, *, provider_message_id: str | None = None,
        failure_code: str | None = None, failure_message: str | None = None,
    ) -> NotificationOut:
        """Records what the provider answered for a QUEUED live attempt. Only SENT (provider accepted), FAILED
        and UNCERTAIN are possible: DELIVERED needs trusted status evidence and has no code path here, and a DEMO
        notification can never be touched."""
        row = self._repo.get_by_code(notification_code)
        if row is None:
            raise NotificationNotFound(f"Notification {notification_code} not found")
        if row.mode is not NotificationMode.LIVE or row.status is not NotificationStatus.QUEUED:
            raise NotificationConflict("Only a queued live notification can record a provider outcome.")
        if status not in (NotificationStatus.SENT, NotificationStatus.FAILED, NotificationStatus.UNCERTAIN):
            raise NotificationConflict(f"{status.value} cannot be recorded from a provider response.")
        if status is NotificationStatus.SENT and not provider_message_id:
            raise NotificationConflict("SENT requires the provider's message id.")
        row.status = status
        row.provider_message_id = provider_message_id
        row.failure_code = failure_code
        row.failure_message = failure_message
        row.updated_at = self._now
        self._repo.save(row)
        return to_out(row)

    def commit(self) -> None:
        self._repo.commit()

    def rollback(self) -> None:
        self._repo.rollback()

    # ---- read -------------------------------------------------------------------------------------

    def list(self, filters: NotificationFilters, params: PageParams) -> Page[NotificationOut]:
        rows, total = self._repo.list(filters, params.offset, params.page_size)
        return Page.build([to_out(row) for row in rows], params, total)

    def get(self, notification_code: str) -> NotificationOut:
        row = self._repo.get_by_code(notification_code)
        if row is None:
            raise NotificationNotFound(f"Notification {notification_code} not found")
        return to_out(row)

    def summary(self, filters: NotificationFilters) -> NotificationSummary:
        by_status = self._repo.counts(Notification.status, filters)
        by_mode = self._repo.counts(Notification.mode, filters)
        by_channel = self._repo.counts(Notification.channel, filters)
        return NotificationSummary(
            total=sum(by_status.values()),
            by_status={status: by_status.get(status, 0) for status in NotificationStatus},
            by_mode={mode: by_mode.get(mode, 0) for mode in NotificationMode},
            by_channel={channel: by_channel.get(channel, 0) for channel in NotificationChannel},
            unread_in_app=self._repo.unread_in_app(filters),
        )

    # ---- read state -------------------------------------------------------------------------------

    def mark_read(self, notification_code: str) -> NotificationOut:
        """Marks an in-app notification as read. Repeating it keeps the first read time."""
        row = self._repo.get_by_code(notification_code)
        if row is None:
            raise NotificationNotFound(f"Notification {notification_code} not found")
        if row.channel is not NotificationChannel.IN_APP:
            raise NotificationConflict("Only in-app notifications have a read state.")
        if row.status is NotificationStatus.CANCELLED:
            raise NotificationConflict("A cancelled notification cannot be marked as read.")
        if row.read_at is None:
            row.read_at = self._now
            row.updated_at = self._now
            self._repo.save(row)
        return to_out(row)
