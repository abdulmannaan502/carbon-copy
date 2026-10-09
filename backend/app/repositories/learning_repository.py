"""Read-only data access for the Learning Engine's RECORDED path.

Reuses the existing tables (no new tables). Counts are SQL aggregations; row-level reads are narrow
column projections of whole tables (no ORM entities, no per-donor or per-request queries).
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BloodRequest,
    CoordinationAttempt,
    Donor,
    DonorInteraction,
    Failure,
    LearningEvent,
    Patient,
    RecoveryAction,
)
from app.models.enums import (
    CoordinationOutcome,
    CoordinationStatus,
    FailureCategory,
    InteractionChannel,
    InteractionResponseStatus,
    InteractionType,
    LearningEventType,
    LearningSourceType,
    RecoveryActionType,
    RecoveryStatus,
    RequestStatus,
    UrgencyLevel,
)


@dataclass(frozen=True)
class InteractionRow:
    donor_id: int
    channel: InteractionChannel
    interaction_type: InteractionType
    initiated_at: datetime
    response_status: InteractionResponseStatus
    response_at: datetime | None


@dataclass(frozen=True)
class FailureRow:
    request_id: int
    urgency: UrgencyLevel
    request_bridge_group_id: int | None
    failure_code: str
    category: FailureCategory
    reason: str
    detected_at: datetime
    donor_code: str
    display_name: str
    blood_group: str
    donor_bridge_group_id: int | None
    channel: InteractionChannel | None


@dataclass(frozen=True)
class AttemptRow:
    request_id: int
    sequence_number: int
    status: CoordinationStatus
    outcome: CoordinationOutcome | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class RequestRow:
    request_id: int
    requested_at: datetime
    required_by: datetime
    status: RequestStatus


class LearningRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def channel_counts(self) -> list[tuple[InteractionChannel, InteractionResponseStatus, int]]:
        """Donation requests only: the like-for-like ask. Availability checks and follow-ups differ in
        purpose and in which channels carry them, so pooling them would compare unlike things."""
        rows = self._session.execute(
            select(DonorInteraction.channel, DonorInteraction.response_status, func.count())
            .where(DonorInteraction.interaction_type == InteractionType.DONATION_REQUEST)
            .group_by(DonorInteraction.channel, DonorInteraction.response_status)
            .order_by(DonorInteraction.channel, DonorInteraction.response_status)
        ).all()
        return [(channel, status, count) for channel, status, count in rows]

    def interaction_window(self) -> tuple[datetime | None, datetime | None]:
        row = self._session.execute(
            select(func.min(DonorInteraction.initiated_at), func.max(DonorInteraction.initiated_at))
        ).one()
        return row[0], row[1]

    def interactions(self) -> list[InteractionRow]:
        """Ordered by donor then time, so contact load can be computed in one pass."""
        rows = self._session.execute(
            select(
                DonorInteraction.donor_id, DonorInteraction.channel, DonorInteraction.interaction_type,
                DonorInteraction.initiated_at,
                DonorInteraction.response_status, DonorInteraction.response_at,
            ).order_by(DonorInteraction.donor_id, DonorInteraction.initiated_at, DonorInteraction.id)
        ).all()
        return [InteractionRow(*row) for row in rows]

    def failure_category_counts(self) -> list[tuple[FailureCategory, int]]:
        rows = self._session.execute(
            select(Failure.failure_category, func.count()).group_by(Failure.failure_category)
            .order_by(Failure.failure_category)
        ).all()
        return [(category, count) for category, count in rows]

    def failure_window(self) -> tuple[datetime | None, datetime | None]:
        row = self._session.execute(select(func.min(Failure.detected_at), func.max(Failure.detected_at))).one()
        return row[0], row[1]

    def failures(self) -> list[FailureRow]:
        first_channel = (
            select(DonorInteraction.channel)
            .where(DonorInteraction.coordination_attempt_id == CoordinationAttempt.id)
            .order_by(DonorInteraction.initiated_at, DonorInteraction.id)
            .limit(1)
            .correlate(CoordinationAttempt)
            .scalar_subquery()
        )
        rows = self._session.execute(
            select(
                BloodRequest.id, BloodRequest.urgency_level, Patient.bridge_group_id, Failure.failure_code,
                Failure.failure_category, Failure.failure_reason, Failure.detected_at, Donor.donor_code,
                Donor.display_name, Donor.blood_group, Donor.bridge_group_id, first_channel,
            )
            .join(CoordinationAttempt, CoordinationAttempt.id == Failure.coordination_attempt_id)
            .join(BloodRequest, BloodRequest.id == CoordinationAttempt.blood_request_id)
            .join(Patient, Patient.id == BloodRequest.patient_id)
            .join(Donor, Donor.id == CoordinationAttempt.donor_id)
            .order_by(BloodRequest.id, CoordinationAttempt.sequence_number)
        ).all()
        return [
            FailureRow(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9].value, r[10], r[11]) for r in rows
        ]

    def recovery_outcomes(self) -> list[tuple[RecoveryActionType, LearningEventType | None, int]]:
        """Each recovery action joined to the recorded learning event that references it (if any)."""
        rows = self._session.execute(
            select(RecoveryAction.action_type, LearningEvent.event_type, func.count())
            .outerjoin(
                LearningEvent,
                (LearningEvent.source_type == LearningSourceType.RECOVERY_ACTION)
                & (LearningEvent.source_reference == RecoveryAction.recovery_code),
            )
            .group_by(RecoveryAction.action_type, LearningEvent.event_type)
            .order_by(RecoveryAction.action_type, LearningEvent.event_type)
        ).all()
        return [(action, event, count) for action, event, count in rows]

    def recovery_status_counts(self) -> list[tuple[RecoveryActionType, RecoveryStatus, int]]:
        rows = self._session.execute(
            select(RecoveryAction.action_type, RecoveryAction.status, func.count())
            .group_by(RecoveryAction.action_type, RecoveryAction.status)
            .order_by(RecoveryAction.action_type, RecoveryAction.status)
        ).all()
        return [(action, status, count) for action, status, count in rows]

    def recovery_window(self) -> tuple[datetime | None, datetime | None]:
        row = self._session.execute(
            select(func.min(RecoveryAction.initiated_at), func.max(RecoveryAction.initiated_at))
        ).one()
        return row[0], row[1]

    def attempts(self) -> list[AttemptRow]:
        rows = self._session.execute(
            select(
                CoordinationAttempt.blood_request_id, CoordinationAttempt.sequence_number,
                CoordinationAttempt.status, CoordinationAttempt.outcome, CoordinationAttempt.started_at,
                CoordinationAttempt.completed_at,
            ).order_by(CoordinationAttempt.blood_request_id, CoordinationAttempt.sequence_number)
        ).all()
        return [AttemptRow(*row) for row in rows]

    def requests(self) -> list[RequestRow]:
        rows = self._session.execute(
            select(BloodRequest.id, BloodRequest.requested_at, BloodRequest.required_by, BloodRequest.status)
            .order_by(BloodRequest.id)
        ).all()
        return [RequestRow(*row) for row in rows]
