"""ORM models.

Every model must be imported here so `init_db()` registers it on `Base.metadata`.
"""

from app.db.base import Base
from app.models.coordination import (
    BloodRequest,
    CoordinationAttempt,
    DonorInteraction,
    Failure,
    LearningEvent,
    RecoveryAction,
)
from app.models.messaging import TestRecipient
from app.models.notification import Notification
from app.models.people import BridgeGroup, Donor, DonorState, Patient

__all__ = [
    "Base",
    "BloodRequest",
    "BridgeGroup",
    "CoordinationAttempt",
    "Donor",
    "DonorInteraction",
    "DonorState",
    "Failure",
    "LearningEvent",
    "Notification",
    "Patient",
    "RecoveryAction",
    "TestRecipient",
]
