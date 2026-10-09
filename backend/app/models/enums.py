"""Controlled vocabularies shared by models, schemas and (later) the engines.

Values are stored as strings, so the database stays readable and SQLite needs no
native enum support.
"""

from enum import StrEnum


class BloodGroup(StrEnum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class UrgencyLevel(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BridgeGroupType(StrEnum):
    NGO = "NGO"
    VOLUNTEER_NETWORK = "VOLUNTEER_NETWORK"
    CAREGIVER_GROUP = "CAREGIVER_GROUP"
    COMMUNITY_GROUP = "COMMUNITY_GROUP"


class RequestStatus(StrEnum):
    OPEN = "OPEN"
    MATCHING = "MATCHING"
    COORDINATING = "COORDINATING"
    FULFILLED = "FULFILLED"
    RECOVERING = "RECOVERING"
    CANCELLED = "CANCELLED"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    LIMITED = "LIMITED"
    UNAVAILABLE = "UNAVAILABLE"


class EligibilityStatus(StrEnum):
    """Demo-rule eligibility only. Never a clinical determination."""

    ELIGIBLE = "ELIGIBLE"
    TEMPORARILY_DEFERRED = "TEMPORARILY_DEFERRED"
    INELIGIBLE = "INELIGIBLE"


class InteractionType(StrEnum):
    AVAILABILITY_CHECK = "AVAILABILITY_CHECK"
    DONATION_REQUEST = "DONATION_REQUEST"
    FOLLOW_UP = "FOLLOW_UP"
    CONFIRMATION = "CONFIRMATION"


class InteractionChannel(StrEnum):
    SIMULATED_SMS = "SIMULATED_SMS"
    SIMULATED_CALL = "SIMULATED_CALL"
    SIMULATED_APP = "SIMULATED_APP"


class InteractionResponseStatus(StrEnum):
    PENDING = "PENDING"
    RESPONDED = "RESPONDED"
    NO_RESPONSE = "NO_RESPONSE"
    DECLINED = "DECLINED"
    UNAVAILABLE = "UNAVAILABLE"
    ACCEPTED = "ACCEPTED"


class CoordinationStatus(StrEnum):
    INITIATED = "INITIATED"
    OUTREACH_SENT = "OUTREACH_SENT"
    WAITING = "WAITING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class CoordinationOutcome(StrEnum):
    DONOR_ACCEPTED = "DONOR_ACCEPTED"
    NO_RESPONSE = "NO_RESPONSE"
    DONOR_UNAVAILABLE = "DONOR_UNAVAILABLE"
    DONOR_DECLINED = "DONOR_DECLINED"
    OTHER = "OTHER"


class FailureCategory(StrEnum):
    NO_RESPONSE = "NO_RESPONSE"
    UNAVAILABLE = "UNAVAILABLE"
    DECLINED = "DECLINED"
    CONTACT_FAILURE = "CONTACT_FAILURE"
    FATIGUE = "FATIGUE"
    # Added for the Failure Autopsy Engine: gate exclusions and cascade-level
    # outcomes it can classify, alongside the outreach-outcome categories above.
    RECENT_DONATION = "RECENT_DONATION"
    DEFERRAL = "DEFERRAL"
    ALREADY_CONTACTED = "ALREADY_CONTACTED"
    CASCADE_EXHAUSTED = "CASCADE_EXHAUSTED"
    OTHER = "OTHER"


class FailureSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecoveryActionType(StrEnum):
    NEXT_DONOR = "NEXT_DONOR"
    ALTERNATIVE_DONOR = "ALTERNATIVE_DONOR"
    BRIDGE_GROUP_ESCALATION = "BRIDGE_GROUP_ESCALATION"
    EXPANDED_SEARCH = "EXPANDED_SEARCH"
    BLOOD_BANK_REFERRAL = "BLOOD_BANK_REFERRAL"
    HUMAN_COORDINATOR_REVIEW = "HUMAN_COORDINATOR_REVIEW"


class RecoveryStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LearningSourceType(StrEnum):
    COORDINATION_ATTEMPT = "COORDINATION_ATTEMPT"
    RECOVERY_ACTION = "RECOVERY_ACTION"


class LearningEventType(StrEnum):
    SUCCESSFUL_MATCH = "SUCCESSFUL_MATCH"
    FAILED_MATCH = "FAILED_MATCH"
    NO_RESPONSE = "NO_RESPONSE"
    DONOR_DECLINED = "DONOR_DECLINED"
    RECOVERY_SUCCESS = "RECOVERY_SUCCESS"
    RECOVERY_FAILURE = "RECOVERY_FAILURE"


class LearningOutcome(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class NotificationEventType(StrEnum):
    DONOR_OUTREACH = "DONOR_OUTREACH"
    DONOR_ACCEPTED = "DONOR_ACCEPTED"
    REQUEST_UPDATE = "REQUEST_UPDATE"
    REQUEST_FULFILLED = "REQUEST_FULFILLED"
    RECOVERY_ACTION = "RECOVERY_ACTION"
    ESCALATION = "ESCALATION"
    SYSTEM_NOTICE = "SYSTEM_NOTICE"


class NotificationRecipientRole(StrEnum):
    DONOR = "DONOR"
    PATIENT = "PATIENT"
    COORDINATOR = "COORDINATOR"
    SYSTEM = "SYSTEM"


class NotificationChannel(StrEnum):
    """How a notification is meant to reach its recipient. Distinct from InteractionChannel, which
    describes simulated donor outreach in the cascade."""

    IN_APP = "IN_APP"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"


class NotificationMode(StrEnum):
    DEMO = "DEMO"  # nothing leaves the system; statuses are never SENT or DELIVERED
    LIVE = "LIVE"  # reserved for a future provider integration; cannot be created yet


class NotificationStatus(StrEnum):
    QUEUED = "QUEUED"        # waiting to be processed; nothing has been attempted
    SIMULATED = "SIMULATED"  # demo mode: recorded as if sent; no external message exists
    SENT = "SENT"            # LIVE only: the provider ACCEPTED the request (not a delivery confirmation)
    DELIVERED = "DELIVERED"  # LIVE only: provider confirmed delivery
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"  # LIVE only: the provider call may or may not have gone through; never auto-resent
    CANCELLED = "CANCELLED"
