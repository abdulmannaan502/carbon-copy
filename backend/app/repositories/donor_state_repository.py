"""Data access for the Donor State Intelligence Engine.

Works on explicit sets of donors: interaction and attempt history is aggregated
per donor in SQL (GROUP BY donor_id), so assessing one donor or a hundred costs
the same few queries and no unrelated donor is ever loaded.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import BloodRequest, CoordinationAttempt, Donor, DonorInteraction, Patient
from app.models.enums import CoordinationOutcome, CoordinationStatus, InteractionResponseStatus, InteractionType


@dataclass(frozen=True)
class DonorObservations:
    """Everything observed about one donor's coordination history before a point in time."""

    # Interactions (pending = sent but not answered by the evaluation time)
    interactions: int = 0
    responded: int = 0
    accepted: int = 0
    declined: int = 0
    unavailable: int = 0
    no_response: int = 0
    pending: int = 0
    donation_requests: int = 0
    last_contact_at: datetime | None = None
    last_unavailable_reply_at: datetime | None = None
    contacts_in_window: int = 0
    requests_in_window: int = 0
    # Coordination attempts completed by the evaluation time
    successes: int = 0
    no_response_failures: int = 0
    declined_failures: int = 0
    other_failures: int = 0
    last_success_at: datetime | None = None
    # Successful attempts completed after the evaluation time (used to rewind registry counts)
    successes_after: int = 0


def _count(condition):  # type: ignore[no-untyped-def]
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


class DonorStateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _donors(self):  # type: ignore[no-untyped-def]
        return select(Donor).options(selectinload(Donor.state_record), selectinload(Donor.bridge_group))

    def get_donor(self, donor_code: str) -> Donor | None:
        return self._session.scalar(self._donors().where(Donor.donor_code == donor_code))

    def get_donors_by_codes(self, donor_codes: Iterable[str]) -> Sequence[Donor]:
        return self._session.scalars(self._donors().where(Donor.donor_code.in_(list(donor_codes)))).all()

    def get_donors_by_ids(self, donor_ids: Iterable[int]) -> Sequence[Donor]:
        return self._session.scalars(self._donors().where(Donor.id.in_(list(donor_ids)))).all()

    def get_request(self, request_code: str) -> BloodRequest | None:
        return self._session.scalar(
            select(BloodRequest)
            .options(selectinload(BloodRequest.patient).selectinload(Patient.bridge_group))
            .where(BloodRequest.request_code == request_code)
        )

    def attempted_donor_codes(self, request_id: int) -> list[str]:
        """Donors that the request's cascade contacted, in cascade order."""
        return list(
            self._session.scalars(
                select(Donor.donor_code)
                .join(CoordinationAttempt, CoordinationAttempt.donor_id == Donor.id)
                .where(CoordinationAttempt.blood_request_id == request_id)
                .order_by(CoordinationAttempt.sequence_number)
            )
        )

    def observations(
        self, donor_ids: Sequence[int], as_of: datetime, window_start: datetime
    ) -> dict[int, DonorObservations]:
        if not donor_ids:
            return {}
        i = DonorInteraction
        R = InteractionResponseStatus
        seen = i.initiated_at < as_of
        pending = and_(seen, or_(i.response_status == R.PENDING, and_(i.response_at.is_not(None), i.response_at > as_of)))
        settled = and_(seen, ~or_(i.response_status == R.PENDING, and_(i.response_at.is_not(None), i.response_at > as_of)))
        in_window = and_(seen, i.initiated_at >= window_start)

        interaction_rows = self._session.execute(
            select(
                i.donor_id,
                _count(settled),
                _count(and_(settled, i.response_status == R.RESPONDED)),
                _count(and_(settled, i.response_status == R.ACCEPTED)),
                _count(and_(settled, i.response_status == R.DECLINED)),
                _count(and_(settled, i.response_status == R.UNAVAILABLE)),
                _count(and_(settled, i.response_status == R.NO_RESPONSE)),
                _count(pending),
                _count(and_(settled, i.interaction_type == InteractionType.DONATION_REQUEST)),
                func.max(case((seen, i.initiated_at))),
                func.max(case((and_(settled, i.response_status == R.UNAVAILABLE), i.response_at))),
                _count(in_window),
                func.count(func.distinct(case((in_window, i.blood_request_id)))),
            )
            .where(i.donor_id.in_(donor_ids))
            .group_by(i.donor_id)
        ).all()

        a = CoordinationAttempt
        S, O = CoordinationStatus, CoordinationOutcome
        done = and_(a.completed_at.is_not(None), a.completed_at <= as_of)
        failed = and_(done, a.status == S.FAILED)
        attempt_rows = self._session.execute(
            select(
                a.donor_id,
                _count(and_(done, a.status == S.SUCCESS)),
                _count(and_(failed, a.outcome == O.NO_RESPONSE)),
                _count(and_(failed, a.outcome.in_([O.DONOR_DECLINED, O.DONOR_UNAVAILABLE]))),
                _count(and_(failed, a.outcome == O.OTHER)),
                func.max(case((and_(done, a.status == S.SUCCESS), a.completed_at))),
                _count(and_(a.status == S.SUCCESS, a.completed_at > as_of)),
            )
            .where(a.donor_id.in_(donor_ids))
            .group_by(a.donor_id)
        ).all()

        merged: dict[int, dict] = {donor_id: {} for donor_id in donor_ids}
        for row in interaction_rows:
            merged[row[0]].update(zip(
                ("interactions", "responded", "accepted", "declined", "unavailable", "no_response", "pending",
                 "donation_requests", "last_contact_at", "last_unavailable_reply_at", "contacts_in_window",
                 "requests_in_window"),
                row[1:], strict=True,
            ))
        for row in attempt_rows:
            merged[row[0]].update(zip(
                ("successes", "no_response_failures", "declined_failures", "other_failures", "last_success_at",
                 "successes_after"),
                row[1:], strict=True,
            ))
        return {donor_id: DonorObservations(**values) for donor_id, values in merged.items()}
