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


import base64
import asyncio
from alex_brain_client import CoreBrainClient, BrainClientError
from alex_audio import validate_wav_pcm, AudioValidationError

class BrainTTSProvider:
    """Remote TTS provider delegating speech synthesis to ALEX Brain PC."""

    def __init__(self, client: CoreBrainClient) -> None:
        self.client = client

    async def synthesize(self, session_id: str, request_id: str, text: str, **kwargs: Any) -> TTSResult:
        if not text:
            raise TTSError(TTSErrorCode.INTERNAL_FAILURE, "Empty text provided")

        try:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                None,
                self.client.synthesize,
                session_id,
                request_id,
                text
            )
            audio_b64 = resp.get("audio_base64", "")
            audio_bytes = base64.b64decode(audio_b64) if audio_b64 else b""

            if not audio_bytes:
                raise TTSError(TTSErrorCode.INTERNAL_FAILURE, "Empty audio returned from Brain TTS")

            wav_meta = validate_wav_pcm(audio_bytes)
            metadata = dict(resp.get("metadata", {}))
            metadata.update(wav_meta)
            metadata.setdefault("audio_format", resp.get("audio_format", "wav"))

            return TTSResult(
                session_id=session_id,
                request_id=request_id,
                audio_data=audio_bytes,
                provider=resp.get("provider", "brain_tts"),
                metadata=metadata
            )
        except AudioValidationError as e:
            raise TTSError(TTSErrorCode.INTERNAL_FAILURE, f"Invalid Brain TTS audio container: {e}") from e
        except TTSError:
            raise
        except BrainClientError as e:
            code = TTSErrorCode.SYNTHESIS_TIMEOUT if e.code == "brain_timeout" else TTSErrorCode.TTS_UNAVAILABLE
            raise TTSError(code, f"Brain TTS error: {e.code}") from e
        except Exception as e:
            raise TTSError(TTSErrorCode.INTERNAL_FAILURE, str(e)) from e


