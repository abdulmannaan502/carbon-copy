"""Blood requests and everything that happens while coordinating them."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import enum_column, utc_now
from app.models.enums import (
    BloodGroup,
    CoordinationOutcome,
    CoordinationStatus,
    FailureCategory,
    FailureSeverity,
    InteractionChannel,
    InteractionResponseStatus,
    InteractionType,
    LearningEventType,
    LearningOutcome,
    LearningSourceType,
    RecoveryActionType,
    RecoveryStatus,
    RequestStatus,
    UrgencyLevel,
)
from app.models.people import LocationMixin

if TYPE_CHECKING:
    from app.models.people import BridgeGroup, Donor, Patient

# Ownership: a BloodRequest owns its interactions, attempts and learning events;
# an attempt owns its Failure; a Failure owns its RecoveryActions. Donors are
# never deleted through these relationships (history must not vanish silently).
_OWNED = {"cascade": "all, delete-orphan", "passive_deletes": True}


class BloodRequest(LocationMixin, Base):
    __tablename__ = "blood_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    bridge_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("bridge_groups.id", ondelete="SET NULL"), index=True
    )
    blood_group: Mapped[BloodGroup] = mapped_column(enum_column(BloodGroup))
    units_required: Mapped[int] = mapped_column(Integer)
    urgency_level: Mapped[UrgencyLevel] = mapped_column(enum_column(UrgencyLevel))
    requested_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    required_by: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[RequestStatus] = mapped_column(enum_column(RequestStatus), index=True)

    patient: Mapped[Patient] = relationship(back_populates="blood_requests")
    bridge_group: Mapped[BridgeGroup | None] = relationship()
    interactions: Mapped[list[DonorInteraction]] = relationship(back_populates="blood_request", **_OWNED)
    coordination_attempts: Mapped[list[CoordinationAttempt]] = relationship(
        back_populates="blood_request", order_by="CoordinationAttempt.sequence_number", **_OWNED
    )
    learning_events: Mapped[list[LearningEvent]] = relationship(back_populates="blood_request", **_OWNED)
    # Recovery actions are owned through Failure; this is a read-only shortcut.
    recovery_actions: Mapped[list[RecoveryAction]] = relationship(viewonly=True)


class CoordinationAttempt(Base):
    """One step of the cascade: the system commits to contacting a specific donor."""

    __tablename__ = "coordination_attempts"
    __table_args__ = (UniqueConstraint("blood_request_id", "sequence_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    blood_request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id", ondelete="CASCADE"), index=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id", ondelete="RESTRICT"), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer)
    priority_score: Mapped[float] = mapped_column(Float)
    status: Mapped[CoordinationStatus] = mapped_column(enum_column(CoordinationStatus))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome: Mapped[CoordinationOutcome | None] = mapped_column(enum_column(CoordinationOutcome))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    blood_request: Mapped[BloodRequest] = relationship(back_populates="coordination_attempts")
    donor: Mapped[Donor] = relationship()
    failure: Mapped[Failure | None] = relationship(back_populates="coordination_attempt", uselist=False, **_OWNED)
    interactions: Mapped[list[DonorInteraction]] = relationship(back_populates="coordination_attempt")


class DonorInteraction(Base):
    """A single simulated outreach message or call and the donor's response."""

    __tablename__ = "donor_interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    interaction_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    blood_request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id", ondelete="CASCADE"), index=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id", ondelete="RESTRICT"), index=True)
    # Set when the interaction belongs to a cascade attempt (null for broadcast availability checks).
    coordination_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("coordination_attempts.id", ondelete="SET NULL"), index=True
    )
    interaction_type: Mapped[InteractionType] = mapped_column(enum_column(InteractionType))
    channel: Mapped[InteractionChannel] = mapped_column(enum_column(InteractionChannel))
    initiated_at: Mapped[datetime] = mapped_column(DateTime)
    response_status: Mapped[InteractionResponseStatus] = mapped_column(enum_column(InteractionResponseStatus))
    response_at: Mapped[datetime | None] = mapped_column(DateTime)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attempt_number: Mapped[int] = mapped_column(Integer)

    blood_request: Mapped[BloodRequest] = relationship(back_populates="interactions")
    donor: Mapped[Donor] = relationship()
    coordination_attempt: Mapped[CoordinationAttempt | None] = relationship(back_populates="interactions")


class Failure(Base):
    """Structured record of why a coordination attempt failed."""

    __tablename__ = "failures"

    id: Mapped[int] = mapped_column(primary_key=True)
    failure_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    coordination_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("coordination_attempts.id", ondelete="CASCADE"), unique=True
    )
    failure_category: Mapped[FailureCategory] = mapped_column(enum_column(FailureCategory), index=True)
    failure_reason: Mapped[str] = mapped_column(Text)
    severity: Mapped[FailureSeverity] = mapped_column(enum_column(FailureSeverity))
    detected_at: Mapped[datetime] = mapped_column(DateTime)
    recommended_action: Mapped[str] = mapped_column(Text)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    coordination_attempt: Mapped[CoordinationAttempt] = relationship(back_populates="failure")
    recovery_actions: Mapped[list[RecoveryAction]] = relationship(back_populates="failure", **_OWNED)


class RecoveryAction(Base):
    """The alternative pathway chosen in response to a failure."""

    __tablename__ = "recovery_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    recovery_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    failure_id: Mapped[int] = mapped_column(ForeignKey("failures.id", ondelete="CASCADE"), index=True)
    blood_request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[RecoveryActionType] = mapped_column(enum_column(RecoveryActionType))
    description: Mapped[str] = mapped_column(Text)
    target_donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id", ondelete="SET NULL"))
    target_bridge_group_id: Mapped[int | None] = mapped_column(ForeignKey("bridge_groups.id", ondelete="SET NULL"))
    status: Mapped[RecoveryStatus] = mapped_column(enum_column(RecoveryStatus))
    initiated_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    failure: Mapped[Failure] = relationship(back_populates="recovery_actions")
    target_donor: Mapped[Donor | None] = relationship()
    target_bridge_group: Mapped[BridgeGroup | None] = relationship()


class LearningEvent(Base):
    """A structured signal derived from an outcome, for the future Learning Engine."""

    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    blood_request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id", ondelete="CASCADE"), index=True)
    donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id", ondelete="SET NULL"), index=True)
    source_type: Mapped[LearningSourceType] = mapped_column(enum_column(LearningSourceType))
    # Code of the attempt or recovery action that produced this event (e.g. "ATT-00012").
    source_reference: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[LearningEventType] = mapped_column(enum_column(LearningEventType), index=True)
    outcome: Mapped[LearningOutcome] = mapped_column(enum_column(LearningOutcome))
    # Signed strength in [-1, 1]: positive reinforces the pathway/donor, negative weakens it.
    signal: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    blood_request: Mapped[BloodRequest] = relationship(back_populates="learning_events")
    donor: Mapped[Donor | None] = relationship()
