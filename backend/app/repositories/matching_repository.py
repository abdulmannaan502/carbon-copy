"""Data access for the Matching Engine.

Candidate discovery happens entirely in SQL: active, compatible donors inside a
bounding box around the request, nearest first, capped. Request-specific history
is fetched with a handful of grouped queries; nothing is queried per donor.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import BloodRequest, CoordinationAttempt, Donor, DonorInteraction, Patient
from app.models.enums import BloodGroup, CoordinationStatus, InteractionResponseStatus, InteractionType


@dataclass(frozen=True)
class DiscoveryCounts:
    total: int
    inactive: int
    incompatible: int  # active donors with an incompatible blood group
    compatible_in_area: int  # active, compatible and inside the box
    compatible_total: int  # active and compatible anywhere


@dataclass
class RequestHistory:
    """What happened with each donor for this request, and nearby, before the evaluation time."""

    # donor_id -> latest availability-check reply for this request
    check_reply: dict[int, InteractionResponseStatus] = field(default_factory=dict)
    # donor_id -> attempts for this request that already failed
    failed_here: set[int] = field(default_factory=set)
    # donor_id -> attempts for this request that are still open or succeeded
    engaged_here: set[int] = field(default_factory=set)
    # donor_id -> failed attempts on any request in the recent window
    recent_failures: dict[int, int] = field(default_factory=dict)
    # donors who successfully donated for this patient before
    donated_for_patient: set[int] = field(default_factory=set)


class MatchingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_request(self, request_code: str) -> BloodRequest | None:
        return self._session.scalar(
            select(BloodRequest)
            .options(selectinload(BloodRequest.patient).selectinload(Patient.bridge_group))
            .where(BloodRequest.request_code == request_code)
        )

    def city_centroid(self, city: str) -> tuple[float, float] | None:
        """Request location: centroid of the synthetic donor coordinates in the request's city."""
        lat, lon = self._session.execute(
            select(func.avg(Donor.latitude), func.avg(Donor.longitude)).where(Donor.city == city)
        ).one()
        return (float(lat), float(lon)) if lat is not None else None

    @staticmethod
    def _in_box(box: tuple[float, float, float, float] | None):  # type: ignore[no-untyped-def]
        if box is None:
            return True
        min_lat, max_lat, min_lon, max_lon = box
        return and_(Donor.latitude.between(min_lat, max_lat), Donor.longitude.between(min_lon, max_lon))

    def discovery_counts(
        self, compatible: Sequence[BloodGroup], box: tuple[float, float, float, float] | None
    ) -> DiscoveryCounts:
        active = Donor.active.is_(True)
        compatible_active = and_(active, Donor.blood_group.in_(compatible))

        def count(condition):  # type: ignore[no-untyped-def]
            return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

        row = self._session.execute(
            select(
                func.count(Donor.id),
                count(~active),
                count(and_(active, ~Donor.blood_group.in_(compatible))),
                count(and_(compatible_active, self._in_box(box))),
                count(compatible_active),
            )
        ).one()
        return DiscoveryCounts(*row)

    def discover(
        self,
        compatible: Sequence[BloodGroup],
        center: tuple[float, float] | None,
        box: tuple[float, float, float, float] | None,
        lon_scale: float,
        cap: int,
    ) -> Sequence[Donor]:
        """Active, compatible donors inside the box, nearest first (planar approximation), capped."""
        statement = (
            select(Donor)
            .options(selectinload(Donor.state_record), selectinload(Donor.bridge_group))
            .where(Donor.active.is_(True), Donor.blood_group.in_(compatible), self._in_box(box))
        )
        if center is not None:
            lat, lon = center
            approx = (Donor.latitude - lat) * (Donor.latitude - lat) + (
                (Donor.longitude - lon) * lon_scale
            ) * ((Donor.longitude - lon) * lon_scale)
            statement = statement.order_by(approx, Donor.donor_code)
        else:
            statement = statement.order_by(Donor.donor_code)
        return self._session.scalars(statement.limit(cap)).all()

    def request_history(
        self,
        request: BloodRequest,
        donor_ids: Sequence[int],
        as_of: datetime,
        window_start: datetime,
    ) -> RequestHistory:
        history = RequestHistory()
        if not donor_ids:
            return history

        # Latest availability-check reply per donor for this request (answered by the evaluation time).
        replies = self._session.execute(
            select(DonorInteraction.donor_id, DonorInteraction.response_status)
            .where(
                DonorInteraction.blood_request_id == request.id,
                DonorInteraction.interaction_type == InteractionType.AVAILABILITY_CHECK,
                DonorInteraction.initiated_at < as_of,
            )
            .order_by(DonorInteraction.donor_id, DonorInteraction.initiated_at, DonorInteraction.id)
        ).all()
        for donor_id, status in replies:
            history.check_reply[donor_id] = status

        # Attempts for this request started before the evaluation time.
        attempts = self._session.execute(
            select(CoordinationAttempt.donor_id, CoordinationAttempt.status, CoordinationAttempt.completed_at)
            .where(CoordinationAttempt.blood_request_id == request.id, CoordinationAttempt.started_at < as_of)
        ).all()
        for donor_id, status, completed_at in attempts:
            if status is CoordinationStatus.FAILED and completed_at is not None and completed_at <= as_of:
                history.failed_here.add(donor_id)
            else:
                history.engaged_here.add(donor_id)

        # Recent failed attempts anywhere, for the pool only.
        failures = self._session.execute(
            select(CoordinationAttempt.donor_id, func.count())
            .where(
                CoordinationAttempt.donor_id.in_(donor_ids),
                CoordinationAttempt.status == CoordinationStatus.FAILED,
                CoordinationAttempt.completed_at >= window_start,
                CoordinationAttempt.completed_at <= as_of,
            )
            .group_by(CoordinationAttempt.donor_id)
        ).all()
        history.recent_failures = {donor_id: count for donor_id, count in failures}

        # Donors who already donated successfully for this patient.
        history.donated_for_patient = set(
            self._session.scalars(
                select(CoordinationAttempt.donor_id)
                .join(BloodRequest, BloodRequest.id == CoordinationAttempt.blood_request_id)
                .where(
                    BloodRequest.patient_id == request.patient_id,
                    CoordinationAttempt.status == CoordinationStatus.SUCCESS,
                    CoordinationAttempt.completed_at <= as_of,
                )
            )
        )
        return history
