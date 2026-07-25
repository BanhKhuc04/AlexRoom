from __future__ import annotations

import hashlib
import hmac
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from alex_brain_tools import (
    BrainChatRequest,
    BrainChatResponse,
    BrainSTTRequest,
    BrainSTTResponse,
    BrainTTSRequest,
    BrainTTSResponse,
)
from brain_service.config import BrainServiceConfig
from brain_service.provider import (
    InvalidProviderResponseError,
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from brain_service.providers import build_provider
from brain_service.service import (
    BrainErrorDetail,
    BrainErrorResponse,
    BrainHealthResponse,
    BrainInferenceService,
    BrainReadinessResponse,
)


LOGGER = logging.getLogger("alex.brain.service")
AUTH_HEADER = "X-ALEX-Brain-Key"

_STT_PROVIDER = None
_TTS_PROVIDER = None


def get_stt_provider():
    global _STT_PROVIDER
    if _STT_PROVIDER is None:
        from alex_local_stt import FasterWhisperSTTProvider
        _STT_PROVIDER = FasterWhisperSTTProvider()
    return _STT_PROVIDER


def get_tts_provider():
    global _TTS_PROVIDER
    if _TTS_PROVIDER is None:
        from alex_local_tts import LocalTTSProvider
        _TTS_PROVIDER = LocalTTSProvider()
    return _TTS_PROVIDER


class BrainHttpError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        request_id: str | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id


def secure_credentials_match(provided: str, expected: str) -> bool:
    """Compare fixed-size secret digests using a constant-time primitive."""

    provided_digest = hashlib.sha256(provided.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(provided_digest, expected_digest)


def _error_response(error: BrainHttpError) -> JSONResponse:
    payload = BrainErrorResponse(
        error=BrainErrorDetail(
            code=error.code,
            message=error.message,
            request_id=error.request_id,
        )
    )
    return JSONResponse(
        status_code=error.status_code,
        content=payload.model_dump(mode="json"),
    )


def _log_outcome(
    endpoint: str,
    outcome: str,
    request_id: str | None = None,
    *,
    provider: str = "-",
    tool_count: int = 0,
    latency_ms: int = 0,
) -> None:
    LOGGER.info(
        "brain_http endpoint=%s request_id=%s provider=%s outcome=%s "
        "tool_count=%d latency_ms=%d",
        endpoint,
        request_id or "-",
        provider,
        outcome,
        tool_count,
        latency_ms,
    )


def create_app(
    config: BrainServiceConfig | None = None,
    inference_service: BrainInferenceService | None = None,
) -> FastAPI:
    loaded_config = config or BrainServiceConfig.from_environment()
    service = inference_service or BrainInferenceService(
        provider=build_provider(loaded_config)
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        readiness = service.warmup(
            timeout_seconds=loaded_config.warmup_timeout_seconds
        )
        _log_outcome(
            "/startup",
            readiness.warmup,
            provider=service.provider_name,
        )
        yield

    brain_app = FastAPI(
        title="ALEX Brain Service",
        version="1.0.0",
        lifespan=lifespan,
    )

    def require_brain_api_key(
        x_alex_brain_key: Annotated[str | None, Header(alias=AUTH_HEADER)] = None,
    ) -> None:
        if not loaded_config.api_key_configured:
            raise BrainHttpError(
                503,
                "authentication_not_configured",
                "ALEX Brain API key is not configured.",
            )

        if not x_alex_brain_key:
            raise BrainHttpError(
                401,
                "authentication_required",
                "Missing ALEX Brain API key header.",
            )

        if not secure_credentials_match(
            x_alex_brain_key,
            loaded_config.api_key,
        ):
            raise BrainHttpError(
                401,
                "invalid_credential",
                "Invalid ALEX Brain API key.",
            )

    @brain_app.exception_handler(BrainHttpError)
    def handle_brain_http_error(
        _: Request,
        error: BrainHttpError,
    ) -> JSONResponse:
        return _error_response(error)

    @brain_app.exception_handler(RequestValidationError)
    def handle_validation_error(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        request_id = None
        return _error_response(
            BrainHttpError(
                422,
                "invalid_request",
                "Request body does not match BrainChatRequest.",
                request_id,
            )
        )

    @brain_app.get("/health", response_model=BrainHealthResponse)
    def health() -> BrainHealthResponse:
        response = service.health()
        _log_outcome("/health", "ok", provider=service.provider_name)
        return response

    @brain_app.get("/ready", response_model=BrainReadinessResponse)
    def ready() -> BrainReadinessResponse:
        response = service.readiness()
        _log_outcome(
            "/ready",
            response.status,
            provider=service.provider_name,
        )
        return response

    @brain_app.get(
        "/v1/health",
        response_model=BrainHealthResponse,
        responses={503: {"model": BrainErrorResponse}},
    )
    def v1_health() -> BrainHealthResponse:
        response = service.health()
        _log_outcome("/v1/health", "ok", provider=service.provider_name)
        return response

    @brain_app.get(
        "/v1/readiness",
        response_model=BrainReadinessResponse,
        responses={503: {"model": BrainErrorResponse}},
    )
    def v1_readiness() -> BrainReadinessResponse:
        response = service.readiness()
        if response.status != "ready":
            _log_outcome("/v1/readiness", "not_ready", provider=service.provider_name)
            raise BrainHttpError(
                503,
                "not_ready",
                "ALEX Brain service is not ready.",
            )
        _log_outcome("/v1/readiness", "ok", provider=service.provider_name)
        return response

    @brain_app.post(
        "/v1/chat",
        response_model=BrainChatResponse,
        responses={
            401: {"model": BrainErrorResponse},
            422: {"model": BrainErrorResponse},
            502: {"model": BrainErrorResponse},
            503: {"model": BrainErrorResponse},
            504: {"model": BrainErrorResponse},
        },
    )
    def chat(
        payload: BrainChatRequest,
        _: None = Depends(require_brain_api_key),
    ) -> BrainChatResponse:
        started = time.monotonic()
        try:
            response = service.chat(payload)
        except ProviderNotConfiguredError as error:
            _log_outcome(
                "/v1/chat",
                "provider_not_configured",
                payload.request_id,
                provider=service.provider_name,
            )
            raise BrainHttpError(
                503,
                "provider_not_configured",
                "No Brain inference provider is configured.",
                payload.request_id,
            ) from error
        except ProviderTimeoutError as error:
            _log_outcome(
                "/v1/chat",
                "provider_timeout",
                payload.request_id,
                provider=service.provider_name,
            )
            raise BrainHttpError(
                504,
                "provider_timeout",
                "The Brain inference provider timed out.",
                payload.request_id,
            ) from error
        except ProviderUnavailableError as error:
            _log_outcome(
                "/v1/chat",
                "provider_unavailable",
                payload.request_id,
                provider=service.provider_name,
            )
            raise BrainHttpError(
                503,
                "provider_unavailable",
                "The Brain inference provider is unavailable.",
                payload.request_id,
            ) from error
        except InvalidProviderResponseError as error:
            _log_outcome(
                "/v1/chat",
                "invalid_provider_response",
                payload.request_id,
                provider=service.provider_name,
            )
            raise BrainHttpError(
                502,
                "invalid_provider_response",
                "The inference provider returned an invalid response.",
                payload.request_id,
            ) from error
        latency_ms = round((time.monotonic() - started) * 1000)
        _log_outcome(
            "/v1/chat",
            "ok",
            payload.request_id,
            provider=service.provider_name,
            tool_count=len(response.tool_calls),
            latency_ms=latency_ms,
        )
        return response

    @brain_app.post(
        "/v1/stt",
        response_model=BrainSTTResponse,
        responses={
            401: {"model": BrainErrorResponse},
            422: {"model": BrainErrorResponse},
            503: {"model": BrainErrorResponse},
        },
    )
    async def stt(
        payload: BrainSTTRequest,
        _: None = Depends(require_brain_api_key),
    ) -> BrainSTTResponse:
        import base64
        try:
            audio_bytes = base64.b64decode(payload.audio_base64)
            stt_provider = get_stt_provider()
            result = await stt_provider.transcribe(payload.session_id, payload.request_id, audio_bytes)
            _log_outcome("/v1/stt", "ok", payload.request_id, provider="faster_whisper")
            return BrainSTTResponse(
                session_id=payload.session_id,
                request_id=payload.request_id,
                transcript=result.transcript,
                is_final=True,
                provider="brain_stt",
            )
        except Exception as error:
            error_cls = error.__class__.__name__
            safe_detail = str(error)
            LOGGER.error(
                "stt_failed request_id=%s session_id=%s provider=faster_whisper error_cls=%s error=%s",
                payload.request_id,
                payload.session_id,
                error_cls,
                safe_detail,
            )
            _log_outcome("/v1/stt", "stt_unavailable", payload.request_id, provider="faster_whisper")
            raise BrainHttpError(
                503,
                "stt_unavailable",
                f"STT transcription unavailable: {safe_detail[:120]}",
                payload.request_id,
            ) from error

    @brain_app.post(
        "/v1/tts",
        response_model=BrainTTSResponse,
        responses={
            401: {"model": BrainErrorResponse},
            422: {"model": BrainErrorResponse},
            503: {"model": BrainErrorResponse},
        },
    )
    async def tts(
        payload: BrainTTSRequest,
        _: None = Depends(require_brain_api_key),
    ) -> BrainTTSResponse:
        import base64
        try:
            tts_provider = get_tts_provider()
            result = await tts_provider.synthesize(payload.session_id, payload.request_id, payload.text)
            audio_b64 = base64.b64encode(result.audio_data).decode("utf-8")
            _log_outcome("/v1/tts", "ok", payload.request_id, provider="local_tts")
            return BrainTTSResponse(
                session_id=payload.session_id,
                request_id=payload.request_id,
                audio_base64=audio_b64,
                provider="brain_tts",
            )
        except Exception as error:
            error_cls = error.__class__.__name__
            safe_detail = str(error)
            LOGGER.error(
                "tts_failed request_id=%s session_id=%s provider=local_tts error_cls=%s error=%s",
                payload.request_id,
                payload.session_id,
                error_cls,
                safe_detail,
            )
            _log_outcome("/v1/tts", "tts_unavailable", payload.request_id, provider="local_tts")
            raise BrainHttpError(
                503,
                "tts_unavailable",
                f"TTS synthesis unavailable: {safe_detail[:120]}",
                payload.request_id,
            ) from error

    return brain_app


app = create_app()
