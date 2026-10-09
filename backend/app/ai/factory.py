from app.ai.base import AIProvider
from app.ai.disabled import DisabledAIProvider
from app.core.config import Settings


def build_ai_provider(settings: Settings) -> AIProvider:
    # A ClaudeAIProvider will be selected here once CLAUDE_API_KEY is set and
    # the integration exists. Until then every environment runs without AI.
    return DisabledAIProvider()
