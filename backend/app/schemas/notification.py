"""Notifications API schemas.

Phase 10A is a record-keeping foundation: creating a notification never sends anything. Only DEMO mode can
be requested and the only initial statuses are SIMULATED and QUEUED, so a successful response is never
evidence that a message was delivered. Demonstration software; synthetic data — not for clinical use.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    NotificationChannel,
    NotificationEventType,
    NotificationMode,
    NotificationRecipientRole,
    NotificationStatus,
)

DONOR_CODE = re.compile(r"^DON-\d{5}$")
PATIENT_CODE = re.compile(r"^PAT-\d{4}$")
COORDINATOR_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,31}$")
REQUEST_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,23}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
NOTIFICATION_CODE = re.compile(r"^NTF-[0-9A-F]{12}$")
RECIPIENT_CODE = re.compile(r"^TR-[0-9A-F]{8}$")

_ANY_DONOR = re.compile(r"\bDON-\d{3,}\b")
_ANY_PATIENT = re.compile(r"\bPAT-\d{3,}\b")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")

DEMO_NOTICE = "Demonstration only: no real message was sent. Synthetic demonstration data — not for clinical use."
SIMULATED_NOTE = "Simulated: recorded as if sent. Nothing was delivered to any real recipient."
QUEUED_NOTE = "Queued: waiting for processing. Nothing has been sent."


class NotificationCreate(BaseModel):
    """Controlled internal/demo creation. LIVE mode and delivery statuses cannot be requested."""

    model_config = ConfigDict(extra="forbid")

    event_type: NotificationEventType
    recipient_role: NotificationRecipientRole
    recipient_ref: str | None = Field(default=None, description="Donor code, patient code or coordinator label.")
    blood_request_code: str | None = None
    channel: NotificationChannel = NotificationChannel.IN_APP
    mode: Literal[NotificationMode.DEMO] = NotificationMode.DEMO
    status: Literal[NotificationStatus.SIMULATED, NotificationStatus.QUEUED] = NotificationStatus.SIMULATED
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=500)
    idempotency_key: str | None = Field(default=None, description="Repeats of the same key return the original.")

    @field_validator("title", "body")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("blood_request_code")
    @classmethod
    def _request_code(cls, value: str | None) -> str | None:
        if value is not None and not REQUEST_CODE.match(value):
            raise ValueError("is not a valid request code")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str | None) -> str | None:
        if value is not None and not IDEMPOTENCY_KEY.match(value):
            raise ValueError("may contain only letters, digits and . _ : - (max 128)")
        return value

    @model_validator(mode="after")
    def _recipient_and_content(self) -> "NotificationCreate":
        role, ref = self.recipient_role, self.recipient_ref
        if role is NotificationRecipientRole.DONOR and not (ref and DONOR_CODE.match(ref)):
            raise ValueError("a donor notification needs recipient_ref as a donor code (DON-00001)")
        if role is NotificationRecipientRole.PATIENT and not (ref and PATIENT_CODE.match(ref)):
            raise ValueError("a patient notification needs recipient_ref as a patient code (PAT-0001)")
        if role is NotificationRecipientRole.COORDINATOR and ref is not None and not COORDINATOR_LABEL.match(ref):
            raise ValueError("a coordinator recipient_ref must be a short plain label")
        if role is NotificationRecipientRole.SYSTEM and ref is not None:
            raise ValueError("a system notification has no recipient_ref")

        text = f"{self.title}\n{self.body}"
        if _PHONE.search(text) or _EMAIL.search(text):
            raise ValueError("must not contain phone numbers or email addresses")
        # One person's private details must never reach another: donor and patient messages may mention
        # no other donor or patient code (coordinator and system messages are operational and may).
        if role is NotificationRecipientRole.DONOR:
            if any(code != ref for code in _ANY_DONOR.findall(text)) or _ANY_PATIENT.search(text):
                raise ValueError("a donor message must not mention another donor or any patient")
        if role is NotificationRecipientRole.PATIENT:
            if any(code != ref for code in _ANY_PATIENT.findall(text)) or _ANY_DONOR.search(text):
                raise ValueError("a patient message must not mention any donor or another patient")
        return self


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: str = Field(validation_alias="notification_code")
    event_type: NotificationEventType
    recipient_role: NotificationRecipientRole
    recipient_ref: str | None
    blood_request_code: str | None
    channel: NotificationChannel
    mode: NotificationMode
    status: NotificationStatus
    title: str
    body: str
    read: bool
    read_at: datetime | None
    provider_message_id: str | None
    failure_code: str | None
    failure_message: str | None
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime
    delivery_note: str = Field(description="What this status does and does not mean.")


class NotificationSummary(BaseModel):
    total: int
    by_status: dict[NotificationStatus, int]
    by_mode: dict[NotificationMode, int]
    by_channel: dict[NotificationChannel, int]
    unread_in_app: int
    demo_notice: str = DEMO_NOTICE


class NotificationDispatchItem(BaseModel):
    event_type: NotificationEventType
    recipient_role: NotificationRecipientRole
    wave_number: int | None
    outcome: Literal["RECORDED", "DUPLICATE", "REJECTED"]
    notification_id: str | None = None
    error: str | None = None


class NotificationDispatchReport(BaseModel):
    """Result of recording a simulation's events as demo notifications. RECORDED means a simulated record
    was stored: not that anything was sent, delivered or answered."""

    request_code: str
    simulation_id: str = Field(description="Hash of every simulation parameter; part of each idempotency key.")
    parameters: dict[str, str | int]
    mode: NotificationMode = NotificationMode.DEMO
    cascade_outcome: str
    created: int
    duplicates: int
    rejected: int
    items: list[NotificationDispatchItem]
    notice: str = (
        "Demonstration only: the cascade is a simulation, nobody was contacted and no message was sent. "
        "Synthetic demonstration data — not for clinical use."
    )


class LiveTestSmsRequest(BaseModel):
    """One controlled test SMS. The client names an authorised recipient by code and an approved template; it
    can never supply a phone number, free text or a list of recipients."""

    model_config = ConfigDict(extra="forbid")

    recipient_code: str = Field(description="Code of a registered, verified, consenting test recipient (TR-XXXXXXXX).")
    template_id: Literal["CONNECTIVITY_TEST"]
    blood_request_code: str | None = Field(default=None, description="Optional request context; must exist.")
    idempotency_key: str = Field(description="Required. A repeat of the key returns the stored record and never resends.")
    confirm_live_send: Literal[True] = Field(description="Must be true: an explicit acknowledgement that a real SMS may be sent.")

    @field_validator("recipient_code")
    @classmethod
    def _recipient(cls, value: str) -> str:
        if not RECIPIENT_CODE.match(value):
            raise ValueError("is not a test-recipient code (TR-XXXXXXXX)")
        return value

    @field_validator("blood_request_code")
    @classmethod
    def _request(cls, value: str | None) -> str | None:
        if value is not None and not REQUEST_CODE.match(value):
            raise ValueError("is not a valid request code")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not (8 <= len(value) <= 128 and IDEMPOTENCY_KEY.match(value)):
            raise ValueError("must be 8-128 characters: letters, digits and . _ : -")
        return value


class LiveTestSmsResult(BaseModel):
    """What happened to a live test send. `provider_accepted` means the provider took the request; it is never
    a delivery confirmation, so `delivery_confirmed` is always false in this phase."""

    notification: NotificationOut
    outcome: Literal["RECORDED", "DUPLICATE", "FAILED", "UNCERTAIN"]
    provider_accepted: bool
    delivery_confirmed: Literal[False] = False
    note: str
