import os
import io
import asyncio
from typing import Any
import tempfile
import wave

from alex_stt import STTProvider, STTResult, STTError, STTErrorCode

# Attempt to import faster_whisper, but gracefully fail for environments without it
try:
    from faster_whisper import WhisperModel
    _HAS_WHISPER = True
except ImportError:
    _HAS_WHISPER = False


class FasterWhisperSTTProvider:
    """Local STT provider using faster-whisper."""
    
    def __init__(self, model_size: str = "tiny", device: str = "cpu", compute_type: str = "int8") -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        
        if _HAS_WHISPER:
            try:
                # Load model lazily or in init. We do it carefully to not crash immediately if path doesn't exist
                self.model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
            except Exception:
                self.model = None

    async def transcribe(self, session_id: str, request_id: str, audio_data: bytes, **kwargs: Any) -> STTResult:
        """
        Transcribes PCM WAV audio data.
        """
        if not _HAS_WHISPER or self.model is None:
            raise STTError(STTErrorCode.STT_UNAVAILABLE, "FasterWhisper model is not available or not installed")
            
        if not audio_data:
            raise STTError(STTErrorCode.INTERNAL_FAILURE, "Empty audio data provided")

        try:
            # We must run this synchronous ML model in a thread pool so we don't block the async event loop
            loop = asyncio.get_running_loop()
            transcript = await loop.run_in_executor(None, self._transcribe_sync, audio_data)
            
            return STTResult(
                session_id=session_id,
                request_id=request_id,
                transcript=transcript,
                is_final=True,
                provider="faster_whisper",
                metadata={"model": self.model_size}
            )
        except Exception as e:
            # We map transcription failure to INTERNAL_FAILURE or TIMEOUT based on need
            raise STTError(STTErrorCode.INTERNAL_FAILURE, str(e))
            
    def _transcribe_sync(self, audio_data: bytes) -> str:
        # Write to a temporary file because WhisperModel expects a file path or a file-like object with wav headers
        # Assuming audio_data is a valid WAV bytes for now.
        # In a real pipeline, audio normalization would happen before here.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name
            
        try:
            segments, info = self.model.transcribe(tmp_path, beam_size=5, language="vi")
            text = "".join([segment.text for segment in segments])
            return text.strip()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
