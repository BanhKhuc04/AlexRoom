from typing import Protocol, Mapping, Any
from dataclasses import dataclass, field
from enum import Enum

class TTSErrorCode(str, Enum):
    TTS_UNAVAILABLE = "tts_unavailable"
    SYNTHESIS_TIMEOUT = "synthesis_timeout"
    INTERNAL_FAILURE = "internal_failure"

class TTSError(Exception):
    def __init__(self, code: TTSErrorCode, message: str):
        super().__init__(message)
        self.code = code

@dataclass(frozen=True)
class TTSResult:
    session_id: str
    request_id: str
    audio_data: bytes
    provider: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

class TTSProvider(Protocol):
    async def synthesize(self, session_id: str, request_id: str, text: str, **kwargs: Any) -> TTSResult:
        """
        Synthesize text to audio.
        Returns a TTSResult containing audio bytes.
        Raises TTSError on failure.
        """
        ...

class DeterministicTTSProvider:
    """A deterministic provider for testing and simulating responses."""
    def __init__(self) -> None:
        self.next_result: TTSResult | TTSError | None = None
        
    async def synthesize(self, session_id: str, request_id: str, text: str, **kwargs: Any) -> TTSResult:
        if isinstance(self.next_result, TTSError):
            raise self.next_result
        if isinstance(self.next_result, TTSResult):
            # Enforce correlation
            if self.next_result.session_id != session_id or self.next_result.request_id != request_id:
                return TTSResult(
                    session_id=session_id,
                    request_id=request_id,
                    audio_data=self.next_result.audio_data,
                    provider="deterministic",
                    metadata=self.next_result.metadata
                )
            return self.next_result
            
        if not text:
            raise TTSError(TTSErrorCode.INTERNAL_FAILURE, "Empty text")
            
        raise TTSError(TTSErrorCode.INTERNAL_FAILURE, "DeterministicTTSProvider not configured for result")
