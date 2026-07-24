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


import base64
import asyncio
from alex_brain_client import CoreBrainClient, BrainClientError

class BrainSTTProvider:
    """Remote STT provider delegating speech recognition to ALEX Brain PC."""

    def __init__(self, client: CoreBrainClient) -> None:
        self.client = client

    async def transcribe(self, session_id: str, request_id: str, audio_data: bytes, **kwargs: Any) -> STTResult:
        if not audio_data:
            raise STTError(STTErrorCode.INTERNAL_FAILURE, "Empty audio data provided")

        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        try:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                None,
                self.client.transcribe,
                session_id,
                request_id,
                audio_b64
            )
            transcript = resp.get("transcript", "")
            return STTResult(
                session_id=session_id,
                request_id=request_id,
                transcript=transcript,
                is_final=resp.get("is_final", True),
                provider=resp.get("provider", "brain_stt"),
                metadata=resp.get("metadata", {})
            )
        except BrainClientError as e:
            code = STTErrorCode.TRANSCRIPTION_TIMEOUT if e.code == "brain_timeout" else STTErrorCode.STT_UNAVAILABLE
            raise STTError(code, f"Brain STT error: {e.code}") from e
        except Exception as e:
            raise STTError(STTErrorCode.INTERNAL_FAILURE, str(e)) from e

