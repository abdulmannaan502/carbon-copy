from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.ai.base import AIProvider
from app.core.config import DEMO_DISCLAIMER, Settings
from app.db.session import ping_database
from app.schemas.system import AIStatus, DatabaseState, HealthResponse, SystemStatusResponse


class SystemService:
    def __init__(self, db: Session, settings: Settings, ai: AIProvider) -> None:
        self._db = db
        self._settings = settings
        self._ai = ai

    def _database_state(self) -> DatabaseState:
        return "connected" if ping_database(self._db) else "unavailable"

    def health(self) -> HealthResponse:
        database = self._database_state()
        return HealthResponse(
            status="ok" if database == "connected" else "degraded",
            service=self._settings.service_id,
            version=self._settings.version,
            database=database,
            timestamp=datetime.now(UTC),
        )

    def status(self) -> SystemStatusResponse:
        return SystemStatusResponse(
            service=self._settings.service_id,
            version=self._settings.version,
            environment=self._settings.environment,
            database=self._database_state(),
            ai=AIStatus(provider=self._ai.name, enabled=self._ai.enabled),
            demo_mode=True,
            disclaimer=DEMO_DISCLAIMER,
        )
