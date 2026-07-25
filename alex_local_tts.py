import asyncio
import io
import os
import re
import tempfile
import wave
from typing import Any

from alex_audio import AudioValidationError, validate_wav_pcm
from alex_tts import TTSError, TTSErrorCode, TTSProvider, TTSResult

MAX_TEXT_LENGTH = 4096
MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 5MB strict limit

_ALEX_NAME_REGEX = re.compile(r"\b[Aa][Ll][Ee][Xx]\b")


def normalize_tts_pronunciation(text: str, name_alias: str = "A-lếch") -> str:
    """
    Normalizes text for TTS speech synthesis ONLY.
    Replaces standalone occurrences of system name 'ALEX' (case-insensitive) with name_alias,
    without altering surrounding words (e.g. 'alexander' remains unchanged).
    Does NOT mutate the original displayed assistant_text.
    """
    if not text or not name_alias:
        return text
    return _ALEX_NAME_REGEX.sub(name_alias, text)


class LocalTTSProvider:
    """
    Local Piper TTS provider running on ALEX Brain PC.
    
    Supports canonical Python API ('python') with cached model runtime,
    and explicit subprocess execution ('subprocess') when configured.
    Strictly refrains from silent implicit fallback between backends.
    """

    def __init__(
        self,
        executable_path: str | None = None,
        model_path: str | None = None,
        config_path: str | None = None,
        backend: str | None = None,
        name_alias: str | None = None,
    ) -> None:
        self.provider_name = os.environ.get("ALEX_TTS_PROVIDER", "piper")
        self.backend = (backend or os.environ.get("ALEX_PIPER_BACKEND", "python")).lower()
        self.executable_path = executable_path or os.environ.get("ALEX_PIPER_EXECUTABLE", "piper")
        
        voice = os.environ.get("ALEX_PIPER_VOICE", "vi_VN-vais1000-medium")
        model_dir = os.environ.get("ALEX_PIPER_MODEL_DIR", "/var/lib/alex-brain/models/piper")
        
        if model_path:
            self.model_path = model_path
        else:
            self.model_path = os.path.join(model_dir, f"{voice}.onnx")

        if config_path:
            self.config_path = config_path
        else:
            self.config_path = f"{self.model_path}.json"

        self.name_alias = name_alias or os.environ.get("ALEX_TTS_NAME_PRONUNCIATION", "A-lếch")
        self._piper_voice: Any = None
        self._voice_loaded: bool = False

    def _verify_model_files(self) -> None:
        """Verify that both .onnx model and .onnx.json metadata files exist."""
        if not os.path.exists(self.model_path):
            raise TTSError(
                TTSErrorCode.TTS_UNAVAILABLE,
                f"Piper voice model file not found: {self.model_path}",
            )
        if not os.path.exists(self.config_path):
            raise TTSError(
                TTSErrorCode.TTS_UNAVAILABLE,
                f"Piper voice config file not found: {self.config_path}",
            )

    def load_voice(self) -> None:
        """Load cached Piper voice runtime instance for single-worker Brain process."""
        if self._voice_loaded:
            return

        if self.backend == "python":
            self._verify_model_files()
            try:
                try:
                    from piper.voice import PiperVoice
                except ImportError:
                    from piper import PiperVoice

                self._piper_voice = PiperVoice.load(
                    self.model_path,
                    config_path=self.config_path,
                )
                self._voice_loaded = True
            except ImportError as err:
                raise TTSError(
                    TTSErrorCode.TTS_UNAVAILABLE,
                    f"Piper Python library is not installed or available: {err}",
                ) from err
            except Exception as err:
                raise TTSError(
                    TTSErrorCode.TTS_UNAVAILABLE,
                    f"Failed to load Piper voice model: {err}",
                ) from err
        elif self.backend == "subprocess":
            self._verify_model_files()
            self._voice_loaded = True
        else:
            raise TTSError(
                TTSErrorCode.TTS_UNAVAILABLE,
                f"Unsupported Piper backend configured: '{self.backend}'",
            )

    async def synthesize(
        self, session_id: str, request_id: str, text: str, **kwargs: Any
    ) -> TTSResult:
        if not text or not text.strip():
            raise TTSError(TTSErrorCode.INTERNAL_FAILURE, "Empty text provided")

        if len(text) > MAX_TEXT_LENGTH:
            raise TTSError(
                TTSErrorCode.INTERNAL_FAILURE,
                f"Text length ({len(text)}) exceeds maximum limit of {MAX_TEXT_LENGTH} characters",
            )

        spoken_text = normalize_tts_pronunciation(text, self.name_alias)

        try:
            self.load_voice()
        except TTSError:
            raise
        except Exception as err:
            raise TTSError(
                TTSErrorCode.TTS_UNAVAILABLE,
                f"Piper voice initialization failed: {err}",
            ) from err

        try:
            loop = asyncio.get_running_loop()
            if self.backend == "python":
                audio_bytes = await loop.run_in_executor(
                    None, self._synthesize_python_sync, spoken_text
                )
            elif self.backend == "subprocess":
                audio_bytes = await self._synthesize_subprocess(spoken_text)
            else:
                raise TTSError(
                    TTSErrorCode.TTS_UNAVAILABLE,
                    f"Unsupported Piper backend: '{self.backend}'",
                )

            metadata = validate_wav_pcm(
                audio_bytes,
                min_sample_rate=8000,
                max_sample_rate=48000,
                max_bytes=MAX_AUDIO_BYTES,
            )

            return TTSResult(
                session_id=session_id,
                request_id=request_id,
                audio_data=audio_bytes,
                provider="local_tts",
                metadata={
                    "model": self.model_path,
                    "backend": self.backend,
                    "sample_rate": metadata["sample_rate"],
                    "channels": metadata["channels"],
                    "sample_width": metadata["sample_width"],
                    "duration_seconds": metadata["duration_seconds"],
                },
            )
        except AudioValidationError as err:
            raise TTSError(
                TTSErrorCode.INTERNAL_FAILURE,
                f"Synthesized audio validation failed: {err}",
            ) from err
        except asyncio.TimeoutError:
            raise TTSError(
                TTSErrorCode.SYNTHESIS_TIMEOUT, "TTS synthesis timed out"
            )
        except TTSError:
            raise
        except Exception as err:
            raise TTSError(
                TTSErrorCode.INTERNAL_FAILURE, f"Synthesis error: {err}"
            ) from err

    def _synthesize_python_sync(self, text: str) -> bytes:
        """Synthesizes audio using in-memory Python PiperVoice runtime."""
        if not self._piper_voice:
            raise TTSError(
                TTSErrorCode.TTS_UNAVAILABLE, "PiperVoice runtime not loaded"
            )

        if not hasattr(self._piper_voice, "synthesize_wav"):
            raise TTSError(
                TTSErrorCode.TTS_UNAVAILABLE,
                "PiperVoice runtime missing required synthesize_wav method",
            )

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_out:
            self._piper_voice.synthesize_wav(text, wav_out)

        return buf.getvalue()



    async def _synthesize_subprocess(self, text: str) -> bytes:
        """Synthesizes audio via explicit Piper CLI binary execution."""
        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_wav_path = tmp_wav.name
        tmp_wav.close()

        try:
            cmd = [
                self.executable_path,
                "--model",
                self.model_path,
                "--config",
                self.config_path,
                "--output_file",
                tmp_wav_path,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=text.encode("utf-8")),
                    timeout=15.0,
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except OSError:
                    pass
                raise TTSError(
                    TTSErrorCode.SYNTHESIS_TIMEOUT,
                    "Piper subprocess timed out after 15s",
                )

            if process.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                raise TTSError(
                    TTSErrorCode.INTERNAL_FAILURE,
                    f"Piper subprocess failed with exit code {process.returncode}: {err_msg[:160]}",
                )

            if not os.path.exists(tmp_wav_path):
                raise TTSError(
                    TTSErrorCode.INTERNAL_FAILURE,
                    "Piper subprocess did not produce output WAV file",
                )

            with open(tmp_wav_path, "rb") as f:
                data = f.read()

            return data
        finally:
            if os.path.exists(tmp_wav_path):
                try:
                    os.remove(tmp_wav_path)
                except OSError:
                    pass


class PlaybackSink:
    """Boundary for playing audio bytes."""

    async def play(self, audio_data: bytes) -> None:
        raise NotImplementedError()


class NullPlaybackSink(PlaybackSink):
    """Deterministic null playback sink for testing."""

    def __init__(self) -> None:
        self.played_audio = bytearray()
        self.cancelled = False

    async def play(self, audio_data: bytes) -> None:
        if self.cancelled:
            return
        await asyncio.sleep(0.01)
        if not self.cancelled:
            self.played_audio.extend(audio_data)

    def cancel(self) -> None:
        self.cancelled = True

