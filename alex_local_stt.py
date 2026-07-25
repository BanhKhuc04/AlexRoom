import os
import io
import asyncio
from typing import Any
import tempfile
import wave

from alex_audio import AudioValidationError, raw_pcm16le_to_wav
from alex_stt import STTError, STTErrorCode, STTProvider, STTResult

# Attempt to import faster_whisper, but gracefully fail for environments without it
try:
    from faster_whisper import WhisperModel
    _HAS_WHISPER = True
except ImportError:
    _HAS_WHISPER = False


class FasterWhisperSTTProvider:
    """Local STT provider using faster-whisper on ALEX Brain PC."""

    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        language: str | None = None,
    ) -> None:
        self.model_size = model_size or os.environ.get("ALEX_STT_MODEL", "small")
        self.device = device or os.environ.get("ALEX_STT_DEVICE", "cpu")
        self.compute_type = compute_type or os.environ.get("ALEX_STT_COMPUTE_TYPE", "int8")
        self.language = language or os.environ.get("ALEX_STT_LANGUAGE", "vi")
        self.model = None

        if _HAS_WHISPER:
            try:
                self.model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
            except Exception:
                # Strictly do not fall back to tiny or another model if loading fails
                self.model = None

    async def transcribe(self, session_id: str, request_id: str, audio_data: bytes, **kwargs: Any) -> STTResult:
        """
        Transcribes audio data (raw PCM16LE or WAV container).
        """
        if not _HAS_WHISPER or self.model is None:
            raise STTError(
                STTErrorCode.STT_UNAVAILABLE,
                f"FasterWhisper model '{self.model_size}' is not available or failed to load",
            )

        if not audio_data:
            raise STTError(STTErrorCode.INTERNAL_FAILURE, "Empty audio payload provided")

        try:
            wav_bytes = raw_pcm16le_to_wav(audio_data, sample_rate=16000, channels=1)
        except AudioValidationError as err:
            raise STTError(STTErrorCode.INTERNAL_FAILURE, f"Invalid audio input: {err}") from err

        try:
            loop = asyncio.get_running_loop()
            transcript = await loop.run_in_executor(None, self._transcribe_sync, wav_bytes)

            return STTResult(
                session_id=session_id,
                request_id=request_id,
                transcript=transcript,
                is_final=True,
                provider="faster_whisper",
                metadata={
                    "model": self.model_size,
                    "language": self.language,
                    "device": self.device,
                    "compute_type": self.compute_type,
                },
            )
        except Exception as e:
            if isinstance(e, STTError):
                raise
            raise STTError(STTErrorCode.INTERNAL_FAILURE, str(e)) from e

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes)
            tmp_path = tmp.name

        try:
            segments, info = self.model.transcribe(
                tmp_path,
                beam_size=5,
                language=self.language,
                condition_on_previous_text=False,
            )
            text = "".join([segment.text for segment in segments])
            return text.strip()
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

