from __future__ import annotations

import json
import socket
from typing import Iterator
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
MAX_BRAIN_TTS_RESPONSE_BYTES: Final = 8 * 1024 * 1024
DEFAULT_STREAM_FIRST_TOKEN_TIMEOUT_SEC: Final = 25.0
DEFAULT_STREAM_IDLE_TIMEOUT_SEC: Final = 15.0
DEFAULT_STREAM_HARD_DEADLINE_SEC: Final = 120.0

BrainClientErrorCode = Literal[
    "brain_disabled",
    "brain_not_configured",
    "brain_unavailable",
    "brain_timeout",
    "invalid_brain_response",
    "brain_busy",
    "invalid_generation",
    "empty_generation",
    "provider_error",
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
    stream_first_token_timeout_seconds: float = DEFAULT_STREAM_FIRST_TOKEN_TIMEOUT_SEC
    stream_idle_timeout_seconds: float = DEFAULT_STREAM_IDLE_TIMEOUT_SEC
    stream_hard_deadline_seconds: float = DEFAULT_STREAM_HARD_DEADLINE_SEC

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
        stream_first = _bounded_timeout(
            environ.get("ALEX_BRAIN_STREAM_FIRST_TOKEN_TIMEOUT_SECONDS", ""),
            default=DEFAULT_STREAM_FIRST_TOKEN_TIMEOUT_SEC,
            maximum=60.0,
        )
        stream_idle = _bounded_timeout(
            environ.get("ALEX_BRAIN_STREAM_IDLE_TIMEOUT_SECONDS", ""),
            default=DEFAULT_STREAM_IDLE_TIMEOUT_SEC,
            maximum=30.0,
        )
        stream_hard = _bounded_timeout(
            environ.get("ALEX_BRAIN_STREAM_HARD_DEADLINE_SECONDS", ""),
            default=DEFAULT_STREAM_HARD_DEADLINE_SEC,
            maximum=600.0,
        )
        return cls(
            enabled=enabled,
            url=environ.get("ALEX_BRAIN_URL", "").strip(),
            client_key=environ.get("ALEX_BRAIN_CLIENT_KEY", "").strip(),
            timeout_seconds=timeout,
            stream_first_token_timeout_seconds=stream_first,
            stream_idle_timeout_seconds=stream_idle,
            stream_hard_deadline_seconds=stream_hard,
        )

    @property
    def configured(self) -> bool:
        return bool(self.url and self.client_key)


class BrainHttpResponse(Protocol):
    def read(self, amount: int = -1) -> bytes: ...

    def __enter__(self) -> "BrainHttpResponse": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


BrainHttpOpen = Callable[..., BrainHttpResponse]


def _bounded_timeout(raw_value: str, default: float = DEFAULT_BRAIN_TIMEOUT_SECONDS, maximum: float = MAX_BRAIN_TIMEOUT_SECONDS) -> float:
    if not raw_value.strip():
        return default
    try:
        parsed = float(raw_value)
    except ValueError:
        return default
    if parsed < MIN_BRAIN_TIMEOUT_SECONDS:
        return MIN_BRAIN_TIMEOUT_SECONDS
    if parsed > maximum:
        return maximum
    return parsed


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


def build_brain_stt_url(base_url: str) -> str:
    """Build a fixed /v1/stt target."""
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
    path = f"{parsed.path.rstrip('/')}/v1/stt"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def build_brain_tts_url(base_url: str) -> str:
    """Build a fixed /v1/tts target."""
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
    path = f"{parsed.path.rstrip('/')}/v1/tts"
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
            code = "brain_unavailable"
            if error.code in {408, 504}:
                code = "brain_timeout"
            else:
                try:
                    error_body = error.read(MAX_BRAIN_RESPONSE_BYTES + 1)
                    if len(error_body) <= MAX_BRAIN_RESPONSE_BYTES:
                        parsed = json.loads(error_body.decode("utf-8"))
                        err_detail = parsed.get("error", {})
                        returned_code = err_detail.get("code")
                        if returned_code in {
                            "brain_busy",
                            "provider_error",
                            "invalid_generation",
                            "empty_generation",
                        }:
                            code = returned_code
                except Exception:
                    pass
            raise BrainClientError(code, http_status=error.code) from None
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

    def chat_stream(self, request: BrainChatRequest) -> Iterator[dict]:
        if not self.config.enabled:
            raise BrainClientError("brain_disabled")
        if not self.config.configured:
            raise BrainClientError("brain_not_configured")

        url = build_brain_chat_url(self.config.url) + "/stream"
        outbound = Request(
            url,
            data=request.model_dump_json().encode("utf-8"),
            headers={
                BRAIN_AUTH_HEADER: self.config.client_key,
                "Content-Type": "application/json",
                "Accept": "application/x-ndjson",
            },
            method="POST",
        )

        try:
            import time
            started = time.monotonic()
            
            with self._opener(
                outbound,
                timeout=self.config.stream_first_token_timeout_seconds,
            ) as upstream:
                try:
                    if hasattr(upstream, "fp") and hasattr(upstream.fp, "raw") and hasattr(upstream.fp.raw, "_sock"):
                        upstream.fp.raw._sock.settimeout(self.config.stream_idle_timeout_seconds)
                except Exception:
                    pass
                    
                total_read = 0
                while True:
                    if time.monotonic() - started > self.config.stream_hard_deadline_seconds:
                        raise BrainClientError("brain_timeout")
                        
                    line = upstream.readline(65536)
                    if not line:
                        break
                    total_read += len(line)
                    if total_read > MAX_BRAIN_RESPONSE_BYTES * 2:  # allow more for stream
                        raise BrainClientError("invalid_brain_response")
                        
                    decoded = line.decode("utf-8").strip()
                    if decoded:
                        try:
                            event = json.loads(decoded)
                        except json.JSONDecodeError:
                            raise BrainClientError("invalid_brain_response") from None
                            
                        if event.get("type") == "error":
                            code = event.get("code", "brain_unavailable")
                            raise BrainClientError(code, http_status=500)
                            
                        yield event
        except HTTPError as error:
            code = "brain_unavailable"
            if error.code in {408, 504}:
                code = "brain_timeout"
            else:
                try:
                    error_body = error.read(MAX_BRAIN_RESPONSE_BYTES + 1)
                    if len(error_body) <= MAX_BRAIN_RESPONSE_BYTES:
                        parsed = json.loads(error_body.decode("utf-8"))
                        err_detail = parsed.get("error", {})
                        returned_code = err_detail.get("code")
                        if returned_code in {
                            "brain_busy",
                            "provider_error",
                            "invalid_generation",
                            "empty_generation",
                        }:
                            code = returned_code
                except Exception:
                    pass
            raise BrainClientError(code, http_status=error.code) from None
        except (socket.timeout, TimeoutError):
            raise BrainClientError("brain_timeout") from None
        except URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise BrainClientError("brain_timeout") from None
            raise BrainClientError("brain_unavailable") from None
        except OSError:
            raise BrainClientError("brain_unavailable") from None

    def transcribe(self, session_id: str, request_id: str, audio_base64: str, language: str = "vi") -> dict:
        if not self.config.enabled:
            raise BrainClientError("brain_disabled")
        if not self.config.configured:
            raise BrainClientError("brain_not_configured")

        url = build_brain_stt_url(self.config.url)
        payload = json.dumps({
            "session_id": session_id,
            "request_id": request_id,
            "audio_base64": audio_base64,
            "audio_format": "wav_pcm16",
            "sample_rate": 16000,
            "channels": 1,
            "language": language,
        }).encode("utf-8")

        outbound = Request(
            url,
            data=payload,
            headers={
                BRAIN_AUTH_HEADER: self.config.client_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with self._opener(outbound, timeout=self.config.timeout_seconds) as upstream:
                body = upstream.read(MAX_BRAIN_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code in {408, 504}:
                raise BrainClientError("brain_timeout", http_status=error.code) from None
            raise BrainClientError("brain_unavailable", http_status=error.code) from None
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
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BrainClientError("invalid_brain_response") from None

    def synthesize(self, session_id: str, request_id: str, text: str) -> dict:
        if not self.config.enabled:
            raise BrainClientError("brain_disabled")
        if not self.config.configured:
            raise BrainClientError("brain_not_configured")

        url = build_brain_tts_url(self.config.url)
        payload = json.dumps({
            "session_id": session_id,
            "request_id": request_id,
            "text": text
        }).encode("utf-8")

        outbound = Request(
            url,
            data=payload,
            headers={
                BRAIN_AUTH_HEADER: self.config.client_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with self._opener(outbound, timeout=self.config.timeout_seconds) as upstream:
                body = upstream.read(MAX_BRAIN_TTS_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code in {408, 504}:
                raise BrainClientError("brain_timeout", http_status=error.code) from None
            raise BrainClientError("brain_unavailable", http_status=error.code) from None
        except (socket.timeout, TimeoutError):
            raise BrainClientError("brain_timeout") from None
        except URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise BrainClientError("brain_timeout") from None
            raise BrainClientError("brain_unavailable") from None
        except OSError:
            raise BrainClientError("brain_unavailable") from None

        if len(body) > MAX_BRAIN_TTS_RESPONSE_BYTES:
            raise BrainClientError("invalid_brain_response")

        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BrainClientError("invalid_brain_response") from None
