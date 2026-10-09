"""Read-only data access for the dataset browsing endpoints."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.interfaces import LoaderOption

from app.models import (
    BloodRequest,
    BridgeGroup,
    CoordinationAttempt,
    Donor,
    DonorInteraction,
    DonorState,
    Failure,
    LearningEvent,
    Patient,
    RecoveryAction,
)

COUNTED_MODELS: dict[str, type[Any]] = {
    "patients": Patient,
    "donors": Donor,
    "donor_states": DonorState,
    "bridge_groups": BridgeGroup,
    "blood_requests": BloodRequest,
    "donor_interactions": DonorInteraction,
    "coordination_attempts": CoordinationAttempt,
    "failures": Failure,
    "recovery_actions": RecoveryAction,
    "learning_events": LearningEvent,
}


class DatasetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def count(self, model: type[Any]) -> int:
        return self._session.scalar(select(func.count()).select_from(model)) or 0

    def counts(self) -> dict[str, int]:
        return {name: self.count(model) for name, model in COUNTED_MODELS.items()}

    def _page[M](self, model: type[M], offset: int, limit: int, *options: LoaderOption) -> Sequence[M]:
        statement = select(model).options(*options).order_by(model.id).offset(offset).limit(limit)  # type: ignore[attr-defined]
        return self._session.scalars(statement).all()

    def list_patients(self, offset: int, limit: int) -> Sequence[Patient]:
        return self._page(Patient, offset, limit, selectinload(Patient.bridge_group))

    def list_donors(self, offset: int, limit: int) -> Sequence[Donor]:
        return self._page(Donor, offset, limit, selectinload(Donor.bridge_group), selectinload(Donor.state_record))

    def list_bridge_groups(self, offset: int, limit: int) -> Sequence[BridgeGroup]:
        return self._page(BridgeGroup, offset, limit)

    def list_blood_requests(self, offset: int, limit: int, search: str | None = None) -> Sequence[BloodRequest]:
        if search is None:
            return self._page(
                BloodRequest, offset, limit, selectinload(BloodRequest.patient), selectinload(BloodRequest.bridge_group)
            )
        # Code search: an exact match first, then other codes containing the text (wildcards are escaped).
        exact_first = case((func.upper(BloodRequest.request_code) == search.upper(), 0), else_=1)
        return self._session.scalars(
            select(BloodRequest)
            .options(selectinload(BloodRequest.patient), selectinload(BloodRequest.bridge_group))
            .where(BloodRequest.request_code.icontains(search, autoescape=True))
            .order_by(exact_first, BloodRequest.id).offset(offset).limit(limit)
        ).all()

    def count_blood_requests(self, search: str | None = None) -> int:
        statement = select(func.count()).select_from(BloodRequest)
        if search is not None:
            statement = statement.where(BloodRequest.request_code.icontains(search, autoescape=True))
        return self._session.scalar(statement) or 0

    def get_blood_request_by_code(self, request_code: str) -> BloodRequest | None:
        return self._session.scalar(select(BloodRequest).where(BloodRequest.request_code == request_code))
