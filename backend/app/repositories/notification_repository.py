"""Data access for notifications: targeted queries only, no per-row lookups."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BloodRequest, Donor, Notification, Patient, TestRecipient
from app.models.enums import (
    NotificationChannel,
    NotificationMode,
    NotificationRecipientRole,
    NotificationStatus,
)


@dataclass(frozen=True)
class NotificationFilters:
    recipient_role: NotificationRecipientRole | None = None
    recipient_ref: str | None = None
    blood_request_code: str | None = None
    channel: NotificationChannel | None = None
    mode: NotificationMode | None = None
    status: NotificationStatus | None = None
    unread_only: bool = False


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _filtered(statement: Select, filters: NotificationFilters) -> Select:  # type: ignore[type-arg]
        conditions = {
            Notification.recipient_role: filters.recipient_role,
            Notification.recipient_ref: filters.recipient_ref,
            Notification.blood_request_code: filters.blood_request_code,
            Notification.channel: filters.channel,
            Notification.mode: filters.mode,
            Notification.status: filters.status,
        }
        for column, value in conditions.items():
            if value is not None:
                statement = statement.where(column == value)
        if filters.unread_only:
            statement = statement.where(
                Notification.channel == NotificationChannel.IN_APP, Notification.read_at.is_(None),
                Notification.status != NotificationStatus.CANCELLED,
            )
        return statement

    def list(self, filters: NotificationFilters, offset: int, limit: int) -> tuple[Sequence[Notification], int]:
        total = self._session.scalar(self._filtered(select(func.count()).select_from(Notification), filters)) or 0
        rows = self._session.scalars(
            self._filtered(select(Notification), filters)
            .order_by(Notification.created_at.desc(), Notification.id.desc()).offset(offset).limit(limit)
        ).all()
        return rows, total

    def get_by_code(self, notification_code: str) -> Notification | None:
        return self._session.scalar(select(Notification).where(Notification.notification_code == notification_code))

    def get_by_idempotency_key(self, key: str) -> Notification | None:
        return self._session.scalar(select(Notification).where(Notification.idempotency_key == key))

    def counts(self, column, filters: NotificationFilters) -> dict:  # type: ignore[no-untyped-def]
        rows = self._session.execute(
            self._filtered(select(column, func.count()).select_from(Notification), filters).group_by(column)
        ).all()
        return {key: count for key, count in rows}

    def unread_in_app(self, filters: NotificationFilters) -> int:
        scoped = NotificationFilters(**{**filters.__dict__, "unread_only": True})
        return self._session.scalar(self._filtered(select(func.count()).select_from(Notification), scoped)) or 0

    def get_test_recipient(self, recipient_code: str) -> TestRecipient | None:
        return self._session.scalar(select(TestRecipient).where(TestRecipient.recipient_code == recipient_code))

    def count_live_attempts(self, recipient_code: str) -> int:
        return self._session.scalar(
            select(func.count()).select_from(Notification)
            .where(Notification.mode == NotificationMode.LIVE, Notification.recipient_ref == recipient_code)
        ) or 0

    def donor_exists(self, donor_code: str) -> bool:
        return self._session.scalar(select(Donor.id).where(Donor.donor_code == donor_code)) is not None

    def patient_exists(self, patient_code: str) -> bool:
        return self._session.scalar(select(Patient.id).where(Patient.patient_code == patient_code)) is not None

    def request_exists(self, request_code: str) -> bool:
        return self._session.scalar(select(BloodRequest.id).where(BloodRequest.request_code == request_code)) is not None

    def add(self, notification: Notification, *, commit: bool = True) -> Notification:
        """Insert. With commit=True (default) it commits; with commit=False it only flushes, leaving the
        transaction open so a caller can store a whole set of notifications atomically (see commit/rollback).
        Raises IntegrityError if the idempotency key or code already exists (the session is rolled back)."""
        self._session.add(notification)
        try:
            self._session.commit() if commit else self._session.flush()
        except IntegrityError:
            self._session.rollback()
            raise
        return notification

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def save(self, notification: Notification) -> Notification:
        self._session.commit()
        return notification
