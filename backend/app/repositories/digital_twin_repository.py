"""Data access for the Living Digital Twin.

A patient's history is small (a handful of requests and attempts), so it is
loaded as objects. For the donor network this repository only returns donor
ids; their state is assessed by the Donor State Engine.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, and_, case, func, select, union
from sqlalchemy.orm import Session, selectinload

from app.models import (
    BloodRequest,
    CoordinationAttempt,
    Donor,
    DonorInteraction,
    DonorState,
    Failure,
    Patient,
    RecoveryAction,
)
from app.models.enums import AvailabilityStatus, BloodGroup, EligibilityStatus, InteractionResponseStatus, InteractionType


@dataclass(frozen=True)
class CheckStats:
    """Broadcast availability checks sent for one request."""

    total: int = 0
    responded: int = 0
    pending: int = 0
    first_sent_at: datetime | None = None


class DigitalTwinRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_patient(self, patient_code: str) -> Patient | None:
        return self._session.scalar(
            select(Patient).options(selectinload(Patient.bridge_group)).where(Patient.patient_code == patient_code)
        )

    def get_request(self, request_code: str) -> BloodRequest | None:
        return self._session.scalar(
            select(BloodRequest)
            .options(selectinload(BloodRequest.patient).selectinload(Patient.bridge_group))
            .where(BloodRequest.request_code == request_code)
        )

    def patient_requests(self, patient_id: int) -> Sequence[BloodRequest]:
        """All of a patient's requests with their full coordination history, oldest first."""
        attempts = selectinload(BloodRequest.coordination_attempts)
        return self._session.scalars(
            select(BloodRequest)
            .where(BloodRequest.patient_id == patient_id)
            .options(
                attempts.selectinload(CoordinationAttempt.donor),
                attempts.selectinload(CoordinationAttempt.interactions),
                attempts.selectinload(CoordinationAttempt.failure)
                .selectinload(Failure.recovery_actions)
                .selectinload(RecoveryAction.target_donor),
            )
            .order_by(BloodRequest.requested_at, BloodRequest.id)
        ).all()

    def _network_donor_ids(
        self, patient_id: int, bridge_group_id: int | None, compatible: Sequence[BloodGroup]
    ) -> Select[tuple[int]]:
        """Donors who have been contacted for this patient, plus compatible members of the patient's bridge group."""
        contacted = (
            select(DonorInteraction.donor_id)
            .join(BloodRequest, BloodRequest.id == DonorInteraction.blood_request_id)
            .where(BloodRequest.patient_id == patient_id)
        )
        if bridge_group_id is None:
            return contacted
        members = select(Donor.id).where(Donor.bridge_group_id == bridge_group_id, Donor.blood_group.in_(compatible))
        return select(union(contacted, members).subquery().c[0])

    def network_donor_ids(
        self, patient_id: int, bridge_group_id: int | None, compatible: Sequence[BloodGroup]
    ) -> list[int]:
        return list(self._session.scalars(self._network_donor_ids(patient_id, bridge_group_id, compatible)))

    def interaction_count(self, patient_id: int, since: datetime, until: datetime) -> int:
        return self._session.scalar(
            select(func.count(DonorInteraction.id))
            .join(BloodRequest, BloodRequest.id == DonorInteraction.blood_request_id)
            .where(
                BloodRequest.patient_id == patient_id,
                DonorInteraction.initiated_at > since,
                DonorInteraction.initiated_at <= until,
            )
        ) or 0

    def check_stats(self, request_id: int) -> CheckStats:
        rows = self._session.execute(
            select(DonorInteraction.response_status, func.count(), func.min(DonorInteraction.initiated_at))
            .where(
                DonorInteraction.blood_request_id == request_id,
                DonorInteraction.interaction_type == InteractionType.AVAILABILITY_CHECK,
            )
            .group_by(DonorInteraction.response_status)
        ).all()
        if not rows:
            return CheckStats()
        by_status = {status: count for status, count, _ in rows}
        return CheckStats(
            total=sum(by_status.values()),
            responded=by_status.get(InteractionResponseStatus.RESPONDED, 0),
            pending=by_status.get(InteractionResponseStatus.PENDING, 0),
            first_sent_at=min(first for _, _, first in rows),
        )
