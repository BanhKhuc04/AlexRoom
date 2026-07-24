from __future__ import annotations

import os
from dataclasses import dataclass


BRAIN_API_KEY_ENV = "ALEX_BRAIN_API_KEY"
PROVIDER_ENV = "ALEX_BRAIN_PROVIDER"
PROVIDER_URL_ENV = "ALEX_BRAIN_PROVIDER_URL"
PROVIDER_MODEL_ENV = "ALEX_BRAIN_MODEL"
PROVIDER_API_KEY_ENV = "ALEX_BRAIN_PROVIDER_API_KEY"
PROVIDER_TIMEOUT_ENV = "ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS"
WARMUP_TIMEOUT_ENV = "ALEX_BRAIN_WARMUP_TIMEOUT_SECONDS"
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 25.0
MAX_PROVIDER_TIMEOUT_SECONDS = 25.0
DEFAULT_WARMUP_TIMEOUT_SECONDS = 60.0
MAX_WARMUP_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class BrainServiceConfig:
    """Process-local Brain configuration with no dependency on ALEX Core."""

    api_key: str | None
    provider: str = "disabled"
    provider_url: str | None = None
    provider_model: str | None = None
    provider_api_key: str | None = None
    provider_timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS
    warmup_timeout_seconds: float = DEFAULT_WARMUP_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> "BrainServiceConfig":
        timeout = cls._parse_bounded_timeout(
            os.getenv(PROVIDER_TIMEOUT_ENV),
            env_name=PROVIDER_TIMEOUT_ENV,
            default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
            maximum=MAX_PROVIDER_TIMEOUT_SECONDS,
        )
        warmup_timeout = cls._parse_bounded_timeout(
            os.getenv(WARMUP_TIMEOUT_ENV),
            env_name=WARMUP_TIMEOUT_ENV,
            default=DEFAULT_WARMUP_TIMEOUT_SECONDS,
            maximum=MAX_WARMUP_TIMEOUT_SECONDS,
        )
        return cls(
            api_key=os.getenv(BRAIN_API_KEY_ENV),
            provider=os.getenv(PROVIDER_ENV, "disabled").strip().lower(),
            provider_url=os.getenv(PROVIDER_URL_ENV),
            provider_model=os.getenv(PROVIDER_MODEL_ENV),
            provider_api_key=os.getenv(PROVIDER_API_KEY_ENV),
            provider_timeout_seconds=timeout,
            warmup_timeout_seconds=warmup_timeout,
        )

    @staticmethod
    def _parse_bounded_timeout(
        raw_value: str | None,
        *,
        env_name: str,
        default: float,
        maximum: float,
    ) -> float:
        if raw_value is None:
            return default
        try:
            value = float(raw_value)
        except ValueError as error:
            raise ValueError(f"{env_name} must be numeric") from error
        if not 0 < value <= maximum:
            raise ValueError(
                f"{env_name} must be greater than 0 and at most "
                f"{maximum:g}"
            )
        return value
