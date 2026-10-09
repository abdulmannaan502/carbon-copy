from app.ai.base import AIProvider, AIRequest, AIResult


class DisabledAIProvider(AIProvider):
    """Used when no model is configured. The application must remain fully
    functional with this provider, because no operational decision depends on AI."""

    name = "disabled"

    @property
    def enabled(self) -> bool:
        return False

    async def generate(self, request: AIRequest) -> AIResult:
        return AIResult(
            text=f"AI assistance is not configured; no '{request.task}' text was generated.",
            provider=self.name,
            generated=False,
        )
