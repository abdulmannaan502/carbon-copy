"""Data access for the Failure Autopsy Engine's RECORDED path.

Reuses the existing `Failure` / `CoordinationAttempt` / `Donor` / `DonorInteraction` models — no new
tables. Everything is one or two queries per request; no per-donor queries.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import BloodRequest, CoordinationAttempt, Donor, DonorInteraction, Failure, Patient
from app.models.enums import FailureCategory, InteractionChannel


@dataclass(frozen=True)
class RecordedFailureRow:
    failure_code: str
    attempt_code: str
    failure_category: FailureCategory
    failure_reason: str
    detected_at: datetime
    donor_id: int
    donor_code: str
    display_name: str
    blood_group: str
    bridge_group_id: int | None
    channel: InteractionChannel | None
    window_expired: bool


class FailureAutopsyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_request(self, request_code: str) -> BloodRequest | None:
        return self._session.scalar(
            select(BloodRequest)
            .options(selectinload(BloodRequest.patient).selectinload(Patient.bridge_group))
            .where(BloodRequest.request_code == request_code)
        )

    def _first_interaction_channel(self, attempt_id: int) -> InteractionChannel | None:
        return self._session.scalar(
            select(DonorInteraction.channel)
            .where(DonorInteraction.coordination_attempt_id == attempt_id)
            .order_by(DonorInteraction.initiated_at, DonorInteraction.id)
            .limit(1)
        )

    def recorded_failures(self, request_id: int) -> Sequence[RecordedFailureRow]:
        """Every recorded Failure for this request's coordination attempts, oldest first."""
        rows = self._session.execute(
            select(Failure, CoordinationAttempt, Donor)
            .join(CoordinationAttempt, CoordinationAttempt.id == Failure.coordination_attempt_id)
            .join(Donor, Donor.id == CoordinationAttempt.donor_id)
            .where(CoordinationAttempt.blood_request_id == request_id)
            .order_by(CoordinationAttempt.sequence_number)
        ).all()
        return [self._row(failure, attempt, donor) for failure, attempt, donor in rows]

    def get_failure(self, request_id: int, failure_code: str) -> RecordedFailureRow | None:
        row = self._session.execute(
            select(Failure, CoordinationAttempt, Donor)
            .join(CoordinationAttempt, CoordinationAttempt.id == Failure.coordination_attempt_id)
            .join(Donor, Donor.id == CoordinationAttempt.donor_id)
            .where(CoordinationAttempt.blood_request_id == request_id, Failure.failure_code == failure_code)
        ).first()
        return self._row(*row) if row else None

    def _row(self, failure: Failure, attempt: CoordinationAttempt, donor: Donor) -> RecordedFailureRow:
        return RecordedFailureRow(
            failure_code=failure.failure_code,
            attempt_code=attempt.attempt_code,
            failure_category=failure.failure_category,
            failure_reason=failure.failure_reason,
            detected_at=failure.detected_at,
            donor_id=donor.id,
            donor_code=donor.donor_code,
            display_name=donor.display_name,
            blood_group=donor.blood_group.value,
            bridge_group_id=donor.bridge_group_id,
            channel=self._first_interaction_channel(attempt.id),
            # Every recorded NO_RESPONSE failure in the synthetic dataset is, by construction,
            # a response-window expiry (see app/db/synthetic.py); other categories are explicit replies.
            window_expired=failure.failure_category is FailureCategory.NO_RESPONSE,
        )
