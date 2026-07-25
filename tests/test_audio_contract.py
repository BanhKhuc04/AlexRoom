import io
import math
import struct
import wave
import pytest

def create_pcm16_le_wav_fixture(sample_rate: int = 16000, duration_sec: float = 0.5) -> bytes:
    """Generate exact 16kHz mono signed PCM16 LE WAV binary fixture using Python stdlib."""
    num_samples = int(sample_rate * duration_sec)
    frames = bytearray()
    for i in range(num_samples):
        sample = int(math.sin(2 * math.pi * 440 * (i / sample_rate)) * 32767)
        frames.extend(struct.pack("<h", sample)) # 16-bit signed little endian

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)           # mono
        wav.setsampwidth(2)           # 16-bit = 2 bytes
        wav.setframerate(sample_rate) # 16000 Hz
        wav.writeframes(frames)
    
    return buffer.getvalue()

def test_pcm16_le_wav_contract_verification():
    """Verify that WAV fixture strictly adheres to 16kHz mono 16-bit PCM LE contract."""
    wav_bytes = create_pcm16_le_wav_fixture()
    
    # Header verification
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"

    # Parse wave properties
    buffer = io.BytesIO(wav_bytes)
    with wave.open(buffer, "rb") as wav:
        assert wav.getnchannels() == 1, "Must be mono channel"
        assert wav.getsampwidth() == 2, "Must be 16-bit (2 bytes) sample width"
        assert wav.getframerate() == 16000, "Must be 16000 Hz sample rate"
        
        frames = wav.readframes(wav.getnframes())
        assert len(frames) > 0
        # Ensure sample count matches 16-bit width
        assert len(frames) % 2 == 0
