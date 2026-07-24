from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Callable, Final, Literal, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from pydantic import ValidationError

from alex_brain_tools import BrainChatRequest, BrainChatResponse


BRAIN_AUTH_HEADER: Final = "X-ALEX-Brain-Key"
DEFAULT_BRAIN_TIMEOUT_SECONDS: Final = 5.0
MIN_BRAIN_TIMEOUT_SECONDS: Final = 0.1
MAX_BRAIN_TIMEOUT_SECONDS: Final = 30.0
MAX_BRAIN_RESPONSE_BYTES: Final = 256 * 1024

BrainClientErrorCode = Literal[
    "brain_disabled",
    "brain_not_configured",
    "brain_unavailable",
    "brain_timeout",
    "invalid_brain_response",
]


class BrainClientError(RuntimeError):
    """Bounded Core-side failure; upstream response bodies are never exposed."""

    def __init__(
        self,
        code: BrainClientErrorCode,
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class CoreBrainConfig:
    """Core-to-Brain HTTP configuration, separate from Brain PC Wake-on-LAN."""

    enabled: bool = False
    url: str = ""
    client_key: str = ""
    timeout_seconds: float = DEFAULT_BRAIN_TIMEOUT_SECONDS

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
    ) -> "CoreBrainConfig":
        enabled = environ.get("ALEX_BRAIN_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        timeout = _bounded_timeout(
            environ.get("ALEX_BRAIN_TIMEOUT_SECONDS", "")
        )
        return cls(
            enabled=enabled,
            url=environ.get("ALEX_BRAIN_URL", "").strip(),
            client_key=environ.get("ALEX_BRAIN_CLIENT_KEY", "").strip(),
            timeout_seconds=timeout,
        )

    @property
    def configured(self) -> bool:
        return bool(self.url and self.client_key)


class BrainHttpResponse(Protocol):
    def read(self, amount: int = -1) -> bytes: ...

    def __enter__(self) -> "BrainHttpResponse": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


BrainHttpOpen = Callable[..., BrainHttpResponse]


def _bounded_timeout(raw_value: str) -> float:
    try:
        value = float(raw_value) if raw_value else DEFAULT_BRAIN_TIMEOUT_SECONDS
    except ValueError:
        return DEFAULT_BRAIN_TIMEOUT_SECONDS
    return min(MAX_BRAIN_TIMEOUT_SECONDS, max(MIN_BRAIN_TIMEOUT_SECONDS, value))


def build_brain_chat_url(base_url: str) -> str:
    """Build a fixed /v1/chat target without inheriting query, fragment or userinfo."""

    parsed = urlsplit(base_url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise BrainClientError("brain_not_configured")
    path = f"{parsed.path.rstrip('/')}/v1/chat"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class CoreBrainClient:
    """Small authenticated HTTP client. It has no Core execution capability."""

    def __init__(
        self,
        config: CoreBrainConfig,
        opener: BrainHttpOpen = urlopen,
    ) -> None:
        self.config = config
        self._opener = opener

    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        if not self.config.enabled:
            raise BrainClientError("brain_disabled")
        if not self.config.configured:
            raise BrainClientError("brain_not_configured")

        url = build_brain_chat_url(self.config.url)
        outbound = Request(
            url,
            data=request.model_dump_json().encode("utf-8"),
            headers={
                BRAIN_AUTH_HEADER: self.config.client_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with self._opener(
                outbound,
                timeout=self.config.timeout_seconds,
            ) as upstream:
                body = upstream.read(MAX_BRAIN_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code in {408, 504}:
                raise BrainClientError(
                    "brain_timeout",
                    http_status=error.code,
                ) from None
            raise BrainClientError(
                "brain_unavailable",
                http_status=error.code,
            ) from None
        except (socket.timeout, TimeoutError):
            raise BrainClientError("brain_timeout") from None
        except URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise BrainClientError("brain_timeout") from None
            raise BrainClientError("brain_unavailable") from None
        except OSError:
            raise BrainClientError("brain_unavailable") from None

        if len(body) > MAX_BRAIN_RESPONSE_BYTES:
            raise BrainClientError("invalid_brain_response")

        try:
            document = json.loads(body.decode("utf-8"))
            response = BrainChatResponse.model_validate(document)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
            raise BrainClientError("invalid_brain_response") from None

        if response.request_id != request.request_id:
            raise BrainClientError("invalid_brain_response")
        return response
