"""Messaging provider interface and the DEMO provider (Phase 10B).

A provider takes a validated notification request and records it through the existing NotificationService
(one table, one idempotency mechanism). The only provider in this phase is the DemoMessagingProvider: it
always records mode DEMO with status SIMULATED, never SENT or DELIVERED, never creates a provider message
id and never touches a network. A later phase can add a live provider behind the same interface.

A returned result means "recorded", never "delivered". Synthetic demonstration data — not for clinical use.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from app.models.enums import NotificationMode, NotificationStatus
from app.schemas.notification import NotificationCreate, NotificationOut
from app.services.notifications import InvalidNotificationReference, NotificationConflict, NotificationService


class DeliveryOutcome(StrEnum):
    RECORDED = "RECORDED"    # a new simulated notification was stored
    DUPLICATE = "DUPLICATE"  # the idempotency key was already used for this same notification
    REJECTED = "REJECTED"    # not stored: unknown reference or an idempotency-key conflict
    FAILED = "FAILED"        # live: the provider definitely rejected the request; nothing was sent
    UNCERTAIN = "UNCERTAIN"  # live: it may or may not have been sent; never resent automatically


@dataclass(frozen=True)
class ProviderResult:
    outcome: DeliveryOutcome
    notification: NotificationOut | None = None
    error: str | None = None

    @property
    def recorded(self) -> bool:
        return self.outcome is DeliveryOutcome.RECORDED


@runtime_checkable
class NotificationProvider(Protocol):
    name: str
    mode: NotificationMode

    def deliver(self, request: NotificationCreate, *, commit: bool = True) -> ProviderResult: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class DemoMessagingProvider:
    """Records demo notifications as SIMULATED. Nothing leaves the system."""

    name = "demo"
    mode = NotificationMode.DEMO

    def __init__(self, service: NotificationService) -> None:
        self._service = service

    def deliver(self, request: NotificationCreate, *, commit: bool = True) -> ProviderResult:
        # Whatever the caller asked for, the demo provider only ever produces a simulated demo record.
        simulated = request.model_copy(update={"mode": NotificationMode.DEMO, "status": NotificationStatus.SIMULATED})
        try:
            notification, created = self._service.create(simulated, commit=commit)
        except (NotificationConflict, InvalidNotificationReference) as error:
            return ProviderResult(DeliveryOutcome.REJECTED, error=str(error))
        return ProviderResult(DeliveryOutcome.RECORDED if created else DeliveryOutcome.DUPLICATE, notification)

    def commit(self) -> None:
        self._service.commit()

    def rollback(self) -> None:
        self._service.rollback()
