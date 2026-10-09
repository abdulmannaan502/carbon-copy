"""Provider-agnostic interface for AI assistance.

Guardrail: AI providers *explain and communicate*; they never *decide*.
Compatibility, eligibility, distance, availability, reliability, fatigue and
donor prioritisation are computed by deterministic services. Those results are
passed to a provider as read-only `context`, and whatever the provider returns
is advisory text for a human coordinator.
"""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AITask(StrEnum):
    EXPLAIN_PRIORITIZATION = "explain_prioritization"
    ANALYZE_FAILURE = "analyze_failure"
    SUMMARIZE = "summarize"
    DRAFT_MESSAGE = "draft_message"
    COORDINATOR_ASSIST = "coordinator_assist"


class AIRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: AITask
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured facts produced by deterministic engines.",
    )
    instructions: str | None = None


class AIResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    provider: str
    generated: bool = Field(description="False when no model was called (fallback text).")


class AIProvider(ABC):
    name: str

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    async def generate(self, request: AIRequest) -> AIResult: ...
