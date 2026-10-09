"""Notifications: a persistent record of a message the coordination system intends for a recipient.

Phase 10A stores records only. Nothing is sent: DEMO notifications are SIMULATED (or QUEUED) and the
database refuses SENT/DELIVERED for them. Recipients and requests are referenced by public code (not by
foreign key) so notifications survive a reseed of the synthetic dataset without dangling ids.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column, utc_now
from app.models.enums import (
    NotificationChannel,
    NotificationEventType,
    NotificationMode,
    NotificationRecipientRole,
    NotificationStatus,
)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # Truthfulness is enforced by the database too: a demo notification is never "sent" or "delivered",
        # and only a live one can carry a provider message id.
        CheckConstraint("NOT (mode = 'DEMO' AND status IN ('SENT', 'DELIVERED'))", name="demo_never_delivered"),
        CheckConstraint("provider_message_id IS NULL OR mode = 'LIVE'", name="provider_id_only_live"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    event_type: Mapped[NotificationEventType] = mapped_column(enum_column(NotificationEventType), index=True)
    recipient_role: Mapped[NotificationRecipientRole] = mapped_column(enum_column(NotificationRecipientRole), index=True)
    recipient_ref: Mapped[str | None] = mapped_column(String(32), index=True)  # donor/patient code or coordinator label
    blood_request_code: Mapped[str | None] = mapped_column(String(24), index=True)
    channel: Mapped[NotificationChannel] = mapped_column(enum_column(NotificationChannel), index=True)
    mode: Mapped[NotificationMode] = mapped_column(enum_column(NotificationMode), index=True)
    status: Mapped[NotificationStatus] = mapped_column(enum_column(NotificationStatus), index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)  # in-app read state only
    provider_message_id: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(48))
    failure_message: Mapped[str | None] = mapped_column(String(240))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    # Set explicitly by the service from the operational clock (an `onupdate` would fall back to wall-clock
    # time whenever the new value equals the old one).
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
