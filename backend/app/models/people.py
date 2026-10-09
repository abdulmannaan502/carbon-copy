"""Patients, bridge groups, donors and donor state."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import enum_column, utc_now
from app.models.enums import (
    AvailabilityStatus,
    BloodGroup,
    BridgeGroupType,
    EligibilityStatus,
    UrgencyLevel,
)

if TYPE_CHECKING:
    from app.models.coordination import BloodRequest


class LocationMixin:
    city: Mapped[str] = mapped_column(String(64))
    district: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(64))


class BridgeGroup(LocationMixin, Base):
    """A fictional NGO, volunteer network, caregiver group or community group that
    supports a recurring patient and can be escalated to during coordination."""

    __tablename__ = "bridge_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    group_type: Mapped[BridgeGroupType] = mapped_column(enum_column(BridgeGroupType))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    patients: Mapped[list[Patient]] = relationship(back_populates="bridge_group")
    donors: Mapped[list[Donor]] = relationship(back_populates="bridge_group")


class Patient(LocationMixin, Base):
    """A synthetic patient with a recurring transfusion requirement."""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    blood_group: Mapped[BloodGroup] = mapped_column(enum_column(BloodGroup))
    urgency_level: Mapped[UrgencyLevel] = mapped_column(enum_column(UrgencyLevel))
    transfusion_frequency_days: Mapped[int] = mapped_column(Integer)
    last_transfusion_date: Mapped[date | None] = mapped_column(Date)
    next_expected_requirement: Mapped[date | None] = mapped_column(Date)
    bridge_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("bridge_groups.id", ondelete="SET NULL"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    bridge_group: Mapped[BridgeGroup | None] = relationship(back_populates="patients")
    blood_requests: Mapped[list[BloodRequest]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )


class Donor(LocationMixin, Base):
    """A synthetic donor profile. Contact details are placeholders only."""

    __tablename__ = "donors"

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    blood_group: Mapped[BloodGroup] = mapped_column(enum_column(BloodGroup), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    phone_placeholder: Mapped[str] = mapped_column(String(32))
    bridge_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("bridge_groups.id", ondelete="SET NULL"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    bridge_group: Mapped[BridgeGroup | None] = relationship(back_populates="donors")
    state_record: Mapped[DonorState | None] = relationship(
        back_populates="donor", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class DonorState(Base):
    """Current operational state of a donor. Owned by the (future) Donor State
    Engine; the seed fills it with plausible synthetic values."""

    __tablename__ = "donor_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id", ondelete="CASCADE"), unique=True)
    availability_status: Mapped[AvailabilityStatus] = mapped_column(enum_column(AvailabilityStatus))
    eligibility_status: Mapped[EligibilityStatus] = mapped_column(enum_column(EligibilityStatus))
    reliability_score: Mapped[float] = mapped_column(Float)
    response_rate: Mapped[float] = mapped_column(Float)
    fatigue_score: Mapped[float] = mapped_column(Float)
    donation_count: Mapped[int] = mapped_column(Integer, default=0)
    days_since_last_donation: Mapped[int | None] = mapped_column(Integer)
    days_since_last_contact: Mapped[int | None] = mapped_column(Integer)
    current_priority_score: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    donor: Mapped[Donor] = relationship(back_populates="state_record")
