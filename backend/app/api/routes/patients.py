from fastapi import APIRouter, HTTPException, status

from app.api.deps import DatasetServiceDep, DigitalTwinServiceDep, PageParamsDep
from app.schemas.common import Page
from app.schemas.dataset import PatientOut
from app.schemas.digital_twin import DigitalTwinState

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=Page[PatientOut])
def list_patients(service: DatasetServiceDep, params: PageParamsDep) -> Page[PatientOut]:
    return service.list_patients(params)


@router.get("/{patient_code}/digital-twin", response_model=DigitalTwinState, tags=["digital-twin"])
def patient_digital_twin(patient_code: str, service: DigitalTwinServiceDep) -> DigitalTwinState:
    twin = service.build(patient_code)
    if twin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Patient {patient_code} not found")
    return twin
