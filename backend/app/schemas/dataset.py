"""Read models for the dataset browsing endpoints. Records are identified by
their public codes; internal database ids are not exposed."""

from datetime import date, datetime

from pydantic import BaseModel

from app.models import BloodRequest, BridgeGroup, Donor, DonorState, Patient
from app.models.enums import (
    AvailabilityStatus,
    BloodGroup,
    BridgeGroupType,
    EligibilityStatus,
    RequestStatus,
    UrgencyLevel,
)


class Location(BaseModel):
    city: str
    district: str
    state: str


class BridgeGroupOut(Location):
    group_code: str
    name: str
    group_type: BridgeGroupType
    active: bool

    @classmethod
    def from_model(cls, group: BridgeGroup) -> "BridgeGroupOut":
        return cls(
            group_code=group.group_code, name=group.name, group_type=group.group_type, active=group.active,
            city=group.city, district=group.district, state=group.state,
        )


class PatientOut(Location):
    patient_code: str
    display_name: str
    blood_group: BloodGroup
    urgency_level: UrgencyLevel
    transfusion_frequency_days: int
    last_transfusion_date: date | None
    next_expected_requirement: date | None
    bridge_group_code: str | None
    active: bool

    @classmethod
    def from_model(cls, patient: Patient) -> "PatientOut":
        return cls(
            patient_code=patient.patient_code,
            display_name=patient.display_name,
            blood_group=patient.blood_group,
            urgency_level=patient.urgency_level,
            transfusion_frequency_days=patient.transfusion_frequency_days,
            last_transfusion_date=patient.last_transfusion_date,
            next_expected_requirement=patient.next_expected_requirement,
            bridge_group_code=patient.bridge_group.group_code if patient.bridge_group else None,
            active=patient.active,
            city=patient.city, district=patient.district, state=patient.state,
        )


class DonorStateOut(BaseModel):
    availability_status: AvailabilityStatus
    eligibility_status: EligibilityStatus
    reliability_score: float
    response_rate: float
    fatigue_score: float
    donation_count: int
    days_since_last_donation: int | None
    days_since_last_contact: int | None
    current_priority_score: float

    @classmethod
    def from_model(cls, state: DonorState) -> "DonorStateOut":
        return cls(
            availability_status=state.availability_status,
            eligibility_status=state.eligibility_status,
            reliability_score=state.reliability_score,
            response_rate=state.response_rate,
            fatigue_score=state.fatigue_score,
            donation_count=state.donation_count,
            days_since_last_donation=state.days_since_last_donation,
            days_since_last_contact=state.days_since_last_contact,
            current_priority_score=state.current_priority_score,
        )


class DonorOut(Location):
    donor_code: str
    display_name: str
    blood_group: BloodGroup
    latitude: float
    longitude: float
    bridge_group_code: str | None
    active: bool
    state_snapshot: DonorStateOut | None

    @classmethod
    def from_model(cls, donor: Donor) -> "DonorOut":
        return cls(
            donor_code=donor.donor_code,
            display_name=donor.display_name,
            blood_group=donor.blood_group,
            latitude=donor.latitude,
            longitude=donor.longitude,
            bridge_group_code=donor.bridge_group.group_code if donor.bridge_group else None,
            active=donor.active,
            state_snapshot=DonorStateOut.from_model(donor.state_record) if donor.state_record else None,
            city=donor.city, district=donor.district, state=donor.state,
        )


class BloodRequestOut(Location):
    request_code: str
    patient_code: str
    bridge_group_code: str | None
    blood_group: BloodGroup
    units_required: int
    urgency_level: UrgencyLevel
    requested_at: datetime
    required_by: datetime
    status: RequestStatus

    @classmethod
    def from_model(cls, request: BloodRequest) -> "BloodRequestOut":
        return cls(
            request_code=request.request_code,
            patient_code=request.patient.patient_code,
            bridge_group_code=request.bridge_group.group_code if request.bridge_group else None,
            blood_group=request.blood_group,
            units_required=request.units_required,
            urgency_level=request.urgency_level,
            requested_at=request.requested_at,
            required_by=request.required_by,
            status=request.status,
            city=request.city, district=request.district, state=request.state,
        )


class DatasetStats(BaseModel):
    patients: int
    donors: int
    donor_states: int
    bridge_groups: int
    blood_requests: int
    donor_interactions: int
    coordination_attempts: int
    failures: int
    recovery_actions: int
    learning_events: int
    seeded: bool
    data_notice: str
