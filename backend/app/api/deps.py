"""FastAPI dependency providers. Route handlers receive fully built services
from here, which keeps handlers thin and lets tests override any layer."""

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.ai import AIProvider, build_ai_provider
from app.core.clock import operational_now
from app.core.config import DATA_NOTICE, Settings, get_settings
from app.db.session import get_db
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.digital_twin_repository import DigitalTwinRepository
from app.repositories.donor_state_repository import DonorStateRepository
from app.repositories.failure_autopsy_repository import FailureAutopsyRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.matching_repository import MatchingRepository
from app.repositories.notification_repository import NotificationRepository
from app.schemas.common import MAX_PAGE_SIZE, PageParams
from app.services.dataset_service import DatasetService
from app.services.digital_twin import DigitalTwinService
from app.services.donor_state import DonorStateEngine
from app.services.cascade import AdaptiveCascadeEngine
from app.services.failure_autopsy import FailureAutopsyEngine
from app.services.coordination_notifications import CoordinationNotifier
from app.services.learning import LearningEngine
from app.services.live_sms import LiveSmsSender, RecipientAuthorizer, TwilioConfig, TwilioSmsProvider
from app.services.notification_provider import DemoMessagingProvider
from app.services.learning_report import LearningReportService
from app.services.matching import MatchingEngine
from app.services.notifications import NotificationService
from app.services.self_healing import SelfHealingEngine
from app.services.self_healing_report import SelfHealingReportService
from app.services.system_service import SystemService

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[Session, Depends(get_db)]


def get_ai_provider(settings: SettingsDep) -> AIProvider:
    return build_ai_provider(settings)


AIProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]


def get_system_service(db: DbSession, settings: SettingsDep, ai: AIProviderDep) -> SystemService:
    return SystemService(db, settings, ai)


SystemServiceDep = Annotated[SystemService, Depends(get_system_service)]


def get_dataset_service(db: DbSession) -> DatasetService:
    return DatasetService(DatasetRepository(db))


DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]


def get_page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


PageParamsDep = Annotated[PageParams, Depends(get_page_params)]


def get_donor_state_engine(db: DbSession, settings: SettingsDep) -> DonorStateEngine:
    return DonorStateEngine(DonorStateRepository(db), operational_now(settings))


DonorStateEngineDep = Annotated[DonorStateEngine, Depends(get_donor_state_engine)]


def get_digital_twin_service(
    db: DbSession, settings: SettingsDep, donor_states: DonorStateEngineDep
) -> DigitalTwinService:
    return DigitalTwinService(DigitalTwinRepository(db), donor_states, operational_now(settings))


DigitalTwinServiceDep = Annotated[DigitalTwinService, Depends(get_digital_twin_service)]


def get_matching_engine(
    db: DbSession, donor_states: DonorStateEngineDep, digital_twins: DigitalTwinServiceDep
) -> MatchingEngine:
    return MatchingEngine(MatchingRepository(db), donor_states, digital_twins)


MatchingEngineDep = Annotated[MatchingEngine, Depends(get_matching_engine)]


def get_failure_autopsy_engine(
    db: DbSession, matching: MatchingEngineDep, settings: SettingsDep
) -> FailureAutopsyEngine:
    return FailureAutopsyEngine(FailureAutopsyRepository(db), matching, operational_now(settings), DATA_NOTICE)


FailureAutopsyEngineDep = Annotated[FailureAutopsyEngine, Depends(get_failure_autopsy_engine)]


def get_cascade_engine(
    db: DbSession, matching: MatchingEngineDep, failure_autopsy: FailureAutopsyEngineDep
) -> AdaptiveCascadeEngine:
    return AdaptiveCascadeEngine(db, matching, failure_autopsy)


CascadeEngineDep = Annotated[AdaptiveCascadeEngine, Depends(get_cascade_engine)]


def get_self_healing_report_service(
    cascade: CascadeEngineDep, failure_autopsy: FailureAutopsyEngineDep, matching: MatchingEngineDep
) -> SelfHealingReportService:
    return SelfHealingReportService(cascade, failure_autopsy, matching, SelfHealingEngine(), DATA_NOTICE)


SelfHealingReportServiceDep = Annotated[SelfHealingReportService, Depends(get_self_healing_report_service)]


def get_notification_service(db: DbSession, settings: SettingsDep) -> NotificationService:
    return NotificationService(NotificationRepository(db), operational_now(settings))


NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


def get_live_sms_sender(db: DbSession, settings: SettingsDep, notifications: NotificationServiceDep) -> LiveSmsSender:
    """DEMO (the default) gives a sender with no provider, which refuses to send. Only MESSAGING_MODE=LIVE builds
    the Twilio provider; the credentials stay inside this backend process."""
    config = TwilioConfig.from_settings(settings)
    if config is None:
        return LiveSmsSender(None)
    return LiveSmsSender(TwilioSmsProvider(config, notifications, RecipientAuthorizer(NotificationRepository(db))))


LiveSmsSenderDep = Annotated[LiveSmsSender, Depends(get_live_sms_sender)]


def get_coordination_notifier(cascade: CascadeEngineDep, notifications: NotificationServiceDep) -> CoordinationNotifier:
    return CoordinationNotifier(cascade, DemoMessagingProvider(notifications))


CoordinationNotifierDep = Annotated[CoordinationNotifier, Depends(get_coordination_notifier)]


def get_learning_engine(db: DbSession, settings: SettingsDep) -> LearningEngine:
    return LearningEngine(LearningRepository(db), DATA_NOTICE, settings.learning_adjustments_enabled)


LearningEngineDep = Annotated[LearningEngine, Depends(get_learning_engine)]


def get_learning_report_service(cascade: CascadeEngineDep, learning: LearningEngineDep) -> LearningReportService:
    return LearningReportService(cascade, learning)


LearningReportServiceDep = Annotated[LearningReportService, Depends(get_learning_report_service)]
