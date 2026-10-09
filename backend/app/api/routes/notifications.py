"""Notification endpoints (Phase 10A).

DEMO ONLY AND NOT PRODUCTION-SECURE: the prototype has no authentication or authorisation, so anyone who can
reach the API can read and create notifications. Creating one only records it; nothing is sent.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from app.api.deps import LiveSmsSenderDep, NotificationServiceDep, PageParamsDep
from app.models.enums import (
    NotificationChannel,
    NotificationMode,
    NotificationRecipientRole,
    NotificationStatus,
)
from app.repositories.notification_repository import NotificationFilters
from app.schemas.common import Page
from app.schemas.notification import LiveTestSmsRequest, LiveTestSmsResult, NotificationCreate, NotificationOut, NotificationSummary
from app.services.live_sms import LiveSmsDisabled, SendNotAuthorized
from app.services.notifications import InvalidNotificationReference, NotificationConflict, NotificationNotFound

router = APIRouter(prefix="/notifications", tags=["notifications"])

NotificationId = Annotated[str, Path(pattern=r"^NTF-[0-9A-F]{12}$", description="Notification code, e.g. NTF-0A1B2C3D4E5F.")]


def get_filters(
    recipient_role: Annotated[NotificationRecipientRole | None, Query()] = None,
    recipient_ref: Annotated[str | None, Query(max_length=32, description="Donor/patient code or coordinator label.")] = None,
    request_code: Annotated[str | None, Query(max_length=24)] = None,
    channel: Annotated[NotificationChannel | None, Query()] = None,
    mode: Annotated[NotificationMode | None, Query()] = None,
    status_filter: Annotated[NotificationStatus | None, Query(alias="status")] = None,
    unread_only: Annotated[bool, Query(description="In-app notifications not yet read.")] = False,
) -> NotificationFilters:
    return NotificationFilters(recipient_role, recipient_ref, request_code, channel, mode, status_filter, unread_only)


FiltersDep = Annotated[NotificationFilters, Depends(get_filters)]


@router.get("", response_model=Page[NotificationOut])
def list_notifications(service: NotificationServiceDep, params: PageParamsDep, filters: FiltersDep) -> Page[NotificationOut]:
    """Newest first. Filters: recipient_role, recipient_ref, request_code, channel, mode, status, unread_only."""
    return service.list(filters, params)


@router.get("/summary", response_model=NotificationSummary)
def notification_summary(service: NotificationServiceDep, filters: FiltersDep) -> NotificationSummary:
    return service.summary(filters)


_REFUSAL_STATUS = {
    "SEND_LIMIT_REACHED": status.HTTP_429_TOO_MANY_REQUESTS,
    "MESSAGE_NOT_APPROVED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "INVALID_SEND_REQUEST": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "UNKNOWN_REQUEST": status.HTTP_422_UNPROCESSABLE_CONTENT,
}
_OUTCOME_NOTE = {
    "RECORDED": "The SMS provider accepted the request. This is not a delivery confirmation.",
    "DUPLICATE": "This idempotency key was already used: the stored record is returned and nothing was sent.",
    "FAILED": "The provider rejected the request; nothing was sent.",
    "UNCERTAIN": "The request may or may not have reached the provider. It was not resent and will not be resent automatically.",
}


@router.post(
    "/test-sms", response_model=LiveTestSmsResult, status_code=status.HTTP_201_CREATED, tags=["live-sms"],
    responses={
        200: {"description": "Idempotent repeat: the stored record; nothing was sent."},
        403: {"description": "Recipient not authorised (unknown, unverified, no consent, or opted out)."},
        409: {"description": "DEMO mode, or the idempotency key was used for something else."},
        429: {"description": "The per-recipient test-send limit was reached."},
        502: {"description": "The provider rejected the request; nothing was sent."},
        504: {"description": "Outcome uncertain; never resent automatically."},
    },
)
def send_test_sms(body: LiveTestSmsRequest, sender: LiveSmsSenderDep, response: Response) -> LiveTestSmsResult:
    """One controlled test SMS to an operator-registered, verified, consenting test recipient, using an approved
    template. Refused unless the backend runs with MESSAGING_MODE=LIVE. Never accepts a phone number or a recipient
    list, never returns credentials. Demo-only access control: the prototype has no authentication."""
    try:
        result = sender.send_test(body)
    except LiveSmsDisabled as error:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "LIVE_MODE_DISABLED", "message": str(error)}) from error
    except SendNotAuthorized as error:
        raise HTTPException(
            _REFUSAL_STATUS.get(error.code, status.HTTP_403_FORBIDDEN), {"code": error.code, "message": error.message}
        ) from error
    except (NotificationConflict, InvalidNotificationReference) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "IDEMPOTENCY_KEY_CONFLICT", "message": str(error)}) from error
    outcome = result.outcome.value
    assert result.notification is not None
    response.status_code = {
        "RECORDED": status.HTTP_201_CREATED, "DUPLICATE": status.HTTP_200_OK,
        "FAILED": status.HTTP_502_BAD_GATEWAY, "UNCERTAIN": status.HTTP_504_GATEWAY_TIMEOUT,
    }[outcome]
    return LiveTestSmsResult(
        notification=result.notification, outcome=outcome,  # type: ignore[arg-type]
        provider_accepted=result.notification.status.value in ("SENT", "DELIVERED"), note=_OUTCOME_NOTE[outcome],
    )


@router.get("/{notification_id}", response_model=NotificationOut)
def get_notification(notification_id: NotificationId, service: NotificationServiceDep) -> NotificationOut:
    try:
        return service.get(notification_id)
    except NotificationNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.post(
    "", response_model=NotificationOut, status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Idempotent repeat: the original notification."}},
)
def create_notification(body: NotificationCreate, service: NotificationServiceDep, response: Response) -> NotificationOut:
    """Records a DEMO notification (SIMULATED or QUEUED). Nothing is sent to anyone; the response is not
    evidence of delivery. A repeated idempotency_key returns the original with 200."""
    try:
        notification, created = service.create(body)
    except InvalidNotificationReference as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except NotificationConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    if not created:
        response.status_code = status.HTTP_200_OK
    return notification


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(notification_id: NotificationId, service: NotificationServiceDep) -> NotificationOut:
    try:
        return service.mark_read(notification_id)
    except NotificationNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except NotificationConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
