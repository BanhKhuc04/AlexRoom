from __future__ import annotations

from brain_service.config import BrainServiceConfig
from brain_service.provider import BrainTextProvider, DisabledProvider
from brain_service.providers.ollama_native import OllamaNativeProvider
from brain_service.providers.openai_compatible import OpenAICompatibleProvider


def build_provider(config: BrainServiceConfig) -> BrainTextProvider:
    if config.provider == "ollama_native":
        return OllamaNativeProvider(
            base_url=config.provider_url,
            model=config.provider_model,
            api_key=config.provider_api_key,
            timeout_seconds=config.provider_timeout_seconds,
            stream_first_token_timeout_seconds=config.stream_first_token_timeout_seconds,
            stream_idle_timeout_seconds=config.stream_idle_timeout_seconds,
            stream_hard_deadline_seconds=config.stream_hard_deadline_seconds,
        )
    if config.provider == "openai_compatible":
        return OpenAICompatibleProvider(
            url=config.provider_url,
            model=config.provider_model,
            api_key=config.provider_api_key,
            timeout_seconds=config.provider_timeout_seconds,
            stream_first_token_timeout_seconds=config.stream_first_token_timeout_seconds,
            stream_idle_timeout_seconds=config.stream_idle_timeout_seconds,
            stream_hard_deadline_seconds=config.stream_hard_deadline_seconds,
        )
    return DisabledProvider()
