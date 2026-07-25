from __future__ import annotations

import io
import struct
import wave

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 5MB max per session


class AudioValidationError(ValueError):
    """Raised when audio payload is empty, corrupted, or incompatible."""
    pass


def raw_pcm16le_to_wav(
    audio_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    """
    Normalizes input audio data to a canonical RIFF/WAVE container with PCM16 LE encoding.
    
    If input already contains a valid RIFF/WAVE header matching the required audio contract
    (16kHz mono 16-bit PCM), it is validated and returned.
    If input is raw PCM16 LE bytes, a valid 44-byte RIFF/WAVE header is generated.
    
    Raises:
        AudioValidationError: If input is empty, oversized, malformed, or has an invalid header.
    """
    if not audio_data:
        raise AudioValidationError("Empty audio payload provided")

    if len(audio_data) > MAX_AUDIO_BYTES:
        raise AudioValidationError(f"Audio payload exceeds maximum limit of {MAX_AUDIO_BYTES} bytes")

    # Check if starts with a RIFF container header
    if audio_data[:4] == b"RIFF":
        if audio_data[8:12] != b"WAVE":
            raise AudioValidationError("Corrupted WAV header: missing WAVE identifier")
        try:
            with wave.open(io.BytesIO(audio_data), "rb") as wav:
                w_channels = wav.getnchannels()
                w_sampwidth = wav.getsampwidth()
                w_rate = wav.getframerate()
                
                if w_channels != channels:
                    raise AudioValidationError(f"Invalid WAV channels: expected {channels}, got {w_channels}")
                if w_sampwidth != (bits_per_sample // 8):
                    raise AudioValidationError(
                        f"Invalid WAV sample width: expected {bits_per_sample // 8} bytes, got {w_sampwidth}"
                    )
                if w_rate != sample_rate:
                    raise AudioValidationError(f"Invalid WAV sample rate: expected {sample_rate} Hz, got {w_rate} Hz")
                    
            return audio_data
        except (wave.Error, EOFError, struct.error, ValueError) as err:
            raise AudioValidationError(f"Corrupted WAV header: {err}") from err

    # If raw PCM16 LE
    bytes_per_sample = bits_per_sample // 8
    if len(audio_data) % bytes_per_sample != 0:
        raise AudioValidationError(
            f"Raw PCM byte length ({len(audio_data)}) is not aligned to {bytes_per_sample}-byte sample boundary"
        )

    # Wrap raw PCM16 LE bytes in a standard RIFF/WAVE header
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(bytes_per_sample)
        wav.setframerate(sample_rate)
        wav.writeframes(audio_data)

    return buffer.getvalue()
