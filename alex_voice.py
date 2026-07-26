from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from alex_brain_client import BrainClientError
from alex_brain_integration import CoreBrainChatResponse
from alex_brain_tools import BrainChatRequest, MAX_REQUEST_ID_LENGTH, BOUNDED_ID_PATTERN, BRAIN_TOOL_REGISTRY
from pydantic import BaseModel, Field, ConfigDict

# Reuse existing telemetry logger
_TELEMETRY_LOGGER = logging.getLogger("alex.intelligence.telemetry")


class VoiceSessionState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    ACTING = "acting"
    SPEAKING = "speaking"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class VoiceErrorCode(str, Enum):
    VOICE_UNAVAILABLE = "voice_unavailable"
    STT_UNAVAILABLE = "stt_unavailable"
    TRANSCRIPTION_TIMEOUT = "transcription_timeout"
    BRAIN_UNAVAILABLE = "brain_unavailable"
    BRAIN_TIMEOUT = "brain_timeout"
    BRAIN_BUSY = "brain_busy"
    PROVIDER_ERROR = "provider_error"
    INVALID_GENERATION = "invalid_generation"
    EMPTY_GENERATION = "empty_generation"
    CANCELLED = "cancelled"
    INVALID_TRANSITION = "invalid_transition"
    INTERNAL_ERROR = "internal_error"
    EMPTY_RESPONSE = "empty_response"


class VoiceSessionError(Exception):
    def __init__(self, code: VoiceErrorCode, message: str):
        super().__init__(message)
        self.code = code


class VoiceInput(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    session_id: str = Field(min_length=1, max_length=MAX_REQUEST_ID_LENGTH, pattern=BOUNDED_ID_PATTERN)
    request_id: str = Field(min_length=1, max_length=MAX_REQUEST_ID_LENGTH, pattern=BOUNDED_ID_PATTERN)
    transcript: str
    is_final: bool
    source: str
    created_at: str


class VoiceResponse(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    session_id: str
    request_id: str
    assistant_text: str | None
    state: VoiceSessionState
    error_code: str | None
    metadata: Mapping[str, Any] = Field(default_factory=dict)


class VoiceSessionLifecycle:
    """Thread-safe deterministic state machine for a voice session."""

    _VALID_PATHS = {
        VoiceSessionState.IDLE: {
            VoiceSessionState.LISTENING,
            VoiceSessionState.UNAVAILABLE
        },
        VoiceSessionState.LISTENING: {
            VoiceSessionState.TRANSCRIBING,
            VoiceSessionState.CANCELLED,
            VoiceSessionState.FAILED
        },
        VoiceSessionState.TRANSCRIBING: {
            VoiceSessionState.THINKING,
            VoiceSessionState.CANCELLED,
            VoiceSessionState.FAILED
        },
        VoiceSessionState.THINKING: {
            VoiceSessionState.ACTING,
            VoiceSessionState.SPEAKING,
            VoiceSessionState.COMPLETED,
            VoiceSessionState.CANCELLED,
            VoiceSessionState.FAILED
        },
        VoiceSessionState.ACTING: {
            VoiceSessionState.SPEAKING,
            VoiceSessionState.COMPLETED,
            VoiceSessionState.CANCELLED,
            VoiceSessionState.FAILED
        },
        VoiceSessionState.SPEAKING: {
            VoiceSessionState.COMPLETED,
            VoiceSessionState.CANCELLED,
            VoiceSessionState.FAILED
        },
        VoiceSessionState.COMPLETED: {
            VoiceSessionState.IDLE
        },
        VoiceSessionState.CANCELLED: set(),
        VoiceSessionState.FAILED: set(),
        VoiceSessionState.UNAVAILABLE: {
            VoiceSessionState.IDLE
        },
    }

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._state = VoiceSessionState.IDLE
        self._lock = threading.Lock()

    def transition_to(self, new_state: VoiceSessionState) -> None:
        with self._lock:
            if new_state not in self._VALID_PATHS.get(self._state, set()):
                raise VoiceSessionError(
                    VoiceErrorCode.INVALID_TRANSITION,
                    f"Cannot transition from {self._state.value} to {new_state.value}"
                )

            self._state = new_state

            try:
                # Best-effort structured observation without leaking PII/secrets
                _TELEMETRY_LOGGER.info(
                    '{"event": "voice_state_changed", "session_id": "%s", "state": "%s", "timestamp": "%s"}',
                    self.session_id,
                    self._state.value,
                    datetime.now(timezone.utc).isoformat()
                )
            except (Exception, ValueError):
                pass

    @property
    def state(self) -> VoiceSessionState:
        with self._lock:
            return self._state

    def cancel(self) -> None:
        """Bounded no-op cancellation logic."""
        with self._lock:
            if self._state in {
                VoiceSessionState.COMPLETED,
                VoiceSessionState.CANCELLED,
                VoiceSessionState.FAILED,
                VoiceSessionState.UNAVAILABLE,
                VoiceSessionState.IDLE
            }:
                return  # No-op

            self._state = VoiceSessionState.CANCELLED
            try:
                _TELEMETRY_LOGGER.info(
                    '{"event": "voice_cancelled", "session_id": "%s", "timestamp": "%s"}',
                    self.session_id,
                    datetime.now(timezone.utc).isoformat()
                )
            except (Exception, ValueError):
                pass


def process_voice_transcript(
    session: VoiceSessionLifecycle,
    voice_input: VoiceInput,
    router: Any  # IntelligenceRouter
) -> VoiceResponse:
    """
    Integrates Voice Domain with Phase 0.9 IntelligenceRouter.
    Voice simply maps its transcript to a BrainChatRequest and waits for authoritative execution.
    """
    if not voice_input.is_final:
        # Partial transcripts don't trigger the brain yet
        return VoiceResponse(
            session_id=voice_input.session_id,
            request_id=voice_input.request_id,
            assistant_text=None,
            state=session.state,
            error_code=None
        )

    start_time = time.monotonic()
    try:
        session.transition_to(VoiceSessionState.THINKING)

        request = BrainChatRequest(
            request_id=voice_input.request_id,
            user_text=voice_input.transcript,
            allowed_tools=None,
            context=None,
            mode=None
        )

        # IntelligenceRouter remains the authoritative boundary
        response: CoreBrainChatResponse = router.dispatch(request)

        # Flow differentiation: Action vs Chat-only
        has_mutations = len(response.tool_results) > 0 and any(
            getattr(BRAIN_TOOL_REGISTRY.get(t.name), "access", None) == "mutation"
            for t in response.tool_results
        )

        is_action = response.route in ("deterministic_safe_action", "execute_action") or has_mutations

        if is_action:
            session.transition_to(VoiceSessionState.ACTING)

        if not response.assistant_text and len(response.tool_results) == 0:
            session.transition_to(VoiceSessionState.FAILED)
            duration_ms = round((time.monotonic() - start_time) * 1000)
            _TELEMETRY_LOGGER.error(
                '{"event": "voice_process_error", "session_id": "%s", "request_id": "%s", "stage": "process_voice_transcript", "error_code": "empty_response", "duration_ms": %d}',
                voice_input.session_id, voice_input.request_id, duration_ms
            )
            return VoiceResponse(
                session_id=voice_input.session_id,
                request_id=voice_input.request_id,
                assistant_text=None,
                state=session.state,
                error_code="empty_response",
                metadata={"route": response.route or "unknown"}
            )

        if session.state == VoiceSessionState.CANCELLED:
            duration_ms = round((time.monotonic() - start_time) * 1000)
            _TELEMETRY_LOGGER.info(
                '{"event": "voice_process_cancelled", "session_id": "%s", "request_id": "%s", "stage": "process_voice_transcript", "duration_ms": %d}',
                voice_input.session_id, voice_input.request_id, duration_ms
            )
            return VoiceResponse(
                session_id=voice_input.session_id,
                request_id=voice_input.request_id,
                assistant_text=None,
                state=VoiceSessionState.CANCELLED,
                error_code=VoiceErrorCode.CANCELLED.value,
                metadata={"route": response.route or "unknown"}
            )

        duration_ms = round((time.monotonic() - start_time) * 1000)
        _TELEMETRY_LOGGER.info(
            '{"event": "voice_process_success", "session_id": "%s", "request_id": "%s", "stage": "process_voice_transcript", "duration_ms": %d, "route": "%s", "is_action": %s}',
            voice_input.session_id, voice_input.request_id, duration_ms, response.route or "unknown", "true" if is_action else "false"
        )
        return VoiceResponse(
            session_id=voice_input.session_id,
            request_id=voice_input.request_id,
            assistant_text=response.assistant_text,
            state=session.state,
            error_code=None,
            metadata={"route": response.route or "unknown"}
        )

    except BrainClientError as e:
        session.transition_to(VoiceSessionState.FAILED)
        duration_ms = round((time.monotonic() - start_time) * 1000)
        error_code = e.code if e.code in [
            "brain_timeout", "brain_busy", "provider_error", "provider_unavailable",
            "invalid_generation", "empty_generation"
        ] else "brain_unavailable"
        _TELEMETRY_LOGGER.error(
            '{"event": "voice_process_error", "session_id": "%s", "request_id": "%s", "stage": "brain_client", "error_code": "%s", "duration_ms": %d}',
            voice_input.session_id, voice_input.request_id, error_code, duration_ms
        )
        return VoiceResponse(
            session_id=voice_input.session_id,
            request_id=voice_input.request_id,
            assistant_text=None,
            state=session.state,
            error_code=error_code
        )
    except VoiceSessionError as e:
        duration_ms = round((time.monotonic() - start_time) * 1000)
        _TELEMETRY_LOGGER.error(
            '{"event": "voice_process_error", "session_id": "%s", "request_id": "%s", "stage": "voice_session", "error_code": "%s", "duration_ms": %d}',
            voice_input.session_id, voice_input.request_id, e.code.value, duration_ms
        )
        # If it was cancelled while router was working, the state would be CANCELLED and we would get INVALID_TRANSITION
        if session.state == VoiceSessionState.CANCELLED:
            return VoiceResponse(
                session_id=voice_input.session_id,
                request_id=voice_input.request_id,
                assistant_text=None,
                state=VoiceSessionState.CANCELLED,
                error_code=VoiceErrorCode.CANCELLED.value
            )
        session._state = VoiceSessionState.FAILED  # Force failed on invalid transitions internally
        return VoiceResponse(
            session_id=voice_input.session_id,
            request_id=voice_input.request_id,
            assistant_text=None,
            state=VoiceSessionState.FAILED,
            error_code=VoiceErrorCode.INVALID_TRANSITION.value
        )
    except Exception as e:
        duration_ms = round((time.monotonic() - start_time) * 1000)
        _TELEMETRY_LOGGER.error(
            '{"event": "voice_process_error", "session_id": "%s", "request_id": "%s", "stage": "process_voice_transcript", "error_code": "%s", "duration_ms": %d}',
            voice_input.session_id, voice_input.request_id, VoiceErrorCode.INTERNAL_ERROR.value, duration_ms
        )
        session._state = VoiceSessionState.FAILED  # bypass transition checking for internal err
        return VoiceResponse(
            session_id=voice_input.session_id,
            request_id=voice_input.request_id,
            assistant_text=None,
            state=VoiceSessionState.FAILED,
            error_code=VoiceErrorCode.INTERNAL_ERROR.value
        )
