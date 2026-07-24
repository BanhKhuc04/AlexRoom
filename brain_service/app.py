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

from alex_brain_tools import BrainChatRequest, BrainChatResponse
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
    service: BrainInferenceService | None = None,
) -> FastAPI:
    resolved_config = config or BrainServiceConfig.from_environment()
    inference_service = service or BrainInferenceService(build_provider(resolved_config))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        readiness = inference_service.warmup(
            timeout_seconds=resolved_config.warmup_timeout_seconds
        )
        _log_outcome(
            "/startup",
            readiness.warmup,
            provider=inference_service.provider_name,
        )
        yield

    brain_app = FastAPI(
        title="ALEX Brain",
        version="v1",
        lifespan=lifespan,
    )

    @brain_app.exception_handler(BrainHttpError)
    async def handle_brain_http_error(_: Request, error: BrainHttpError) -> JSONResponse:
        return _error_response(error)

    @brain_app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        _log_outcome(request.url.path, "invalid_request")
        return _error_response(
            BrainHttpError(
                422,
                "invalid_request",
                "Request body does not match BrainChatRequest.",
            )
        )

    @brain_app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _: Exception) -> JSONResponse:
        _log_outcome(request.url.path, "internal_error")
        return _error_response(
            BrainHttpError(
                500,
                "internal_error",
                "The Brain service could not process the request.",
            )
        )

    def require_brain_api_key(
        credential: Annotated[str | None, Header(alias=AUTH_HEADER)] = None,
    ) -> None:
        if credential is None:
            _log_outcome("/v1/chat", "authentication_required")
            raise BrainHttpError(
                401,
                "authentication_required",
                f"Provide the {AUTH_HEADER} header.",
            )
        if not resolved_config.api_key:
            _log_outcome("/v1/chat", "authentication_not_configured")
            raise BrainHttpError(
                503,
                "authentication_not_configured",
                "Brain service authentication is not configured.",
            )
        if not secure_credentials_match(credential, resolved_config.api_key):
            _log_outcome("/v1/chat", "invalid_credential")
            raise BrainHttpError(
                401,
                "invalid_credential",
                "Brain service credential was rejected.",
            )

    @brain_app.get("/health", response_model=BrainHealthResponse)
    def health() -> BrainHealthResponse:
        response = inference_service.health()
        _log_outcome("/health", "ok", provider=inference_service.provider_name)
        return response

    @brain_app.get("/ready", response_model=BrainReadinessResponse)
    def ready() -> BrainReadinessResponse:
        response = inference_service.readiness()
        _log_outcome(
            "/ready",
            response.status,
            provider=inference_service.provider_name,
        )
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
            response = inference_service.chat(payload)
        except ProviderNotConfiguredError as error:
            _log_outcome(
                "/v1/chat",
                "provider_not_configured",
                payload.request_id,
                provider=inference_service.provider_name,
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
                provider=inference_service.provider_name,
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
                provider=inference_service.provider_name,
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
                provider=inference_service.provider_name,
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
            provider=inference_service.provider_name,
            tool_count=len(response.tool_calls),
            latency_ms=latency_ms,
        )
        return response

    return brain_app


app = create_app()
