from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DatabaseState = Literal["connected", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    database: DatabaseState
    timestamp: datetime


class AIStatus(BaseModel):
    provider: str
    enabled: bool


class SystemStatusResponse(BaseModel):
    service: str
    version: str
    environment: str
    database: DatabaseState
    ai: AIStatus
    demo_mode: bool
    disclaimer: str
