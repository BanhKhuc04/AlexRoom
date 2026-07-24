from typing import Protocol, Mapping, Any
from dataclasses import dataclass, field
from enum import Enum

class STTErrorCode(str, Enum):
    STT_UNAVAILABLE = "stt_unavailable"
    TRANSCRIPTION_TIMEOUT = "transcription_timeout"
    INTERNAL_FAILURE = "internal_failure"

class STTError(Exception):
    def __init__(self, code: STTErrorCode, message: str):
        super().__init__(message)
        self.code = code

@dataclass(frozen=True)
class STTResult:
    session_id: str
    request_id: str
    transcript: str
    is_final: bool
    provider: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

class STTProvider(Protocol):
    async def transcribe(self, session_id: str, request_id: str, audio_data: bytes, **kwargs: Any) -> STTResult:
        """
        Transcribe audio data. 
        Returns an STTResult.
        Raises STTError on failure.
        """
        ...

class DeterministicSTTProvider:
    """A deterministic provider for testing and simulating responses."""
    def __init__(self) -> None:
        self.next_result: STTResult | STTError | None = None
        
    async def transcribe(self, session_id: str, request_id: str, audio_data: bytes, **kwargs: Any) -> STTResult:
        if isinstance(self.next_result, STTError):
            raise self.next_result
        if isinstance(self.next_result, STTResult):
            # Enforce correlation
            if self.next_result.session_id != session_id or self.next_result.request_id != request_id:
                return STTResult(
                    session_id=session_id,
                    request_id=request_id,
                    transcript=self.next_result.transcript,
                    is_final=self.next_result.is_final,
                    provider="deterministic",
                    metadata=self.next_result.metadata
                )
            return self.next_result
            
        raise STTError(STTErrorCode.INTERNAL_FAILURE, "DeterministicSTTProvider not configured for result")
