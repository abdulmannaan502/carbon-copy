from app.core.config import DATA_NOTICE
from app.models import BloodRequest, BridgeGroup, Donor, Patient
from app.repositories.dataset_repository import DatasetRepository
from app.schemas.common import Page, PageParams
from app.schemas.dataset import BloodRequestOut, BridgeGroupOut, DatasetStats, DonorOut, PatientOut


class DatasetService:
    """Read-only access to the synthetic dataset."""

    def __init__(self, repository: DatasetRepository) -> None:
        self._repo = repository

    def stats(self) -> DatasetStats:
        counts = self._repo.counts()
        return DatasetStats(**counts, seeded=counts["donors"] > 0, data_notice=DATA_NOTICE)

    def list_patients(self, params: PageParams) -> Page[PatientOut]:
        items = self._repo.list_patients(params.offset, params.page_size)
        return Page.build([PatientOut.from_model(p) for p in items], params, self._repo.count(Patient))

    def list_donors(self, params: PageParams) -> Page[DonorOut]:
        items = self._repo.list_donors(params.offset, params.page_size)
        return Page.build([DonorOut.from_model(d) for d in items], params, self._repo.count(Donor))

    def list_bridge_groups(self, params: PageParams) -> Page[BridgeGroupOut]:
        items = self._repo.list_bridge_groups(params.offset, params.page_size)
        return Page.build([BridgeGroupOut.from_model(g) for g in items], params, self._repo.count(BridgeGroup))

    def list_blood_requests(self, params: PageParams, search: str | None = None) -> Page[BloodRequestOut]:
        """`search` finds requests whose code contains the text (case-insensitive), exact match first."""
        items = self._repo.list_blood_requests(params.offset, params.page_size, search)
        return Page.build([BloodRequestOut.from_model(r) for r in items], params, self._repo.count_blood_requests(search))
