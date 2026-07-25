import io
import math
import struct
import wave
import pytest

from alex_audio import AudioValidationError, raw_pcm16le_to_wav, MAX_AUDIO_BYTES
from alex_local_stt import FasterWhisperSTTProvider, _HAS_WHISPER


def create_pcm16_le_raw_fixture(sample_rate: int = 16000, duration_sec: float = 0.5) -> bytes:
    """Generate raw 16kHz mono signed PCM16 LE byte stream without container header."""
    num_samples = int(sample_rate * duration_sec)
    frames = bytearray()
    for i in range(num_samples):
        sample = int(math.sin(2 * math.pi * 440 * (i / sample_rate)) * 32767)
        frames.extend(struct.pack("<h", sample))  # 16-bit signed little endian
    return bytes(frames)


def create_pcm16_le_wav_fixture(sample_rate: int = 16000, duration_sec: float = 0.5) -> bytes:
    """Generate exact 16kHz mono signed PCM16 LE WAV binary fixture using Python stdlib."""
    frames = create_pcm16_le_raw_fixture(sample_rate, duration_sec)
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
    
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"

    buffer = io.BytesIO(wav_bytes)
    with wave.open(buffer, "rb") as wav:
        assert wav.getnchannels() == 1, "Must be mono channel"
        assert wav.getsampwidth() == 2, "Must be 16-bit (2 bytes) sample width"
        assert wav.getframerate() == 16000, "Must be 16000 Hz sample rate"
        frames = wav.readframes(wav.getnframes())
        assert len(frames) > 0
        assert len(frames) % 2 == 0


def test_audio_matrix_a_raw_pcm_normalization():
    """A. Valid PCM16LE raw fixture -> WAV normalization -> valid RIFF 16kHz mono 16-bit."""
    raw_pcm = create_pcm16_le_raw_fixture()
    wav_bytes = raw_pcm16le_to_wav(raw_pcm, sample_rate=16000, channels=1)

    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000
        frames = wav.readframes(wav.getnframes())
        assert frames == raw_pcm


def test_audio_matrix_b_valid_wav_fixture_pass_through():
    """B. Valid generated WAV fixture -> raw_pcm16le_to_wav accepts container boundary."""
    valid_wav = create_pcm16_le_wav_fixture()
    res_bytes = raw_pcm16le_to_wav(valid_wav, sample_rate=16000, channels=1)
    assert res_bytes == valid_wav


def test_audio_matrix_c_mislabeled_raw_pcm_rejection():
    """C. Corrupted RIFF header -> rejected by audio validation."""
    fake_wav_header = b"RIFF\x00\x00\x00\x00WAVEcorrupted_junk_header_bytes_here_12345"
    with pytest.raises(AudioValidationError, match="Corrupted WAV header"):
        raw_pcm16le_to_wav(fake_wav_header)


def test_audio_matrix_d_empty_audio_rejection():
    """D. Empty audio -> structured failure."""
    with pytest.raises(AudioValidationError, match="Empty audio payload"):
        raw_pcm16le_to_wav(b"")


def test_audio_matrix_e_malformed_wav_rejection():
    """E. Malformed WAV -> structured failure."""
    malformed_wav = b"RIFF1234WAVEfmt \x10\x00\x00\x00\x01\x00\x02\x00"  # truncated fmt chunk
    with pytest.raises(AudioValidationError, match="Corrupted WAV header"):
        raw_pcm16le_to_wav(malformed_wav)


def test_audio_matrix_f_oversized_audio_rejection():
    """F. Oversized audio -> existing bounds preserved."""
    oversized_pcm = b"\x00" * (MAX_AUDIO_BYTES + 2)
    with pytest.raises(AudioValidationError, match="exceeds maximum limit"):
        raw_pcm16le_to_wav(oversized_pcm)


import asyncio


def test_real_provider_smoke_test():
    """
    8. Real Provider Smoke Test:
    Executes only when faster-whisper is installed in current environment.
    Proves model container/decode pipeline executes without crash.
    """
    if not _HAS_WHISPER:
        pytest.skip("faster-whisper is not installed in current test environment")

    provider = FasterWhisperSTTProvider(model_size="tiny", device="cpu", compute_type="int8")
    if provider.model is None:
        pytest.skip("faster-whisper model weights unavailable in local environment")

    valid_wav = create_pcm16_le_wav_fixture(duration_sec=0.5)
    result = asyncio.run(provider.transcribe("sess-smoke-1", "req-smoke-1", valid_wav))
    assert result.session_id == "sess-smoke-1"
    assert result.request_id == "req-smoke-1"
    assert isinstance(result.transcript, str)


from alex_audio import validate_wav_pcm


def test_validate_wav_pcm_22050_hz_piper():
    """Verify validate_wav_pcm accepts valid 22050 Hz WAV from Piper TTS."""
    piper_wav = create_pcm16_le_wav_fixture(sample_rate=22050, duration_sec=0.5)
    meta = validate_wav_pcm(piper_wav)
    assert meta["sample_rate"] == 22050
    assert meta["channels"] == 1
    assert meta["sample_width"] == 2
    assert meta["duration_seconds"] == pytest.approx(0.5, abs=0.05)


def test_validate_wav_pcm_empty_and_oversized():
    """Verify validate_wav_pcm rejects empty data and audio exceeding 5MB max bytes."""
    with pytest.raises(AudioValidationError, match="Empty audio payload"):
        validate_wav_pcm(b"")

    oversized_header = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * (MAX_AUDIO_BYTES + 10)
    with pytest.raises(AudioValidationError, match="exceeds limit"):
        validate_wav_pcm(oversized_header, max_bytes=MAX_AUDIO_BYTES)


def test_validate_wav_pcm_non_wav_rejection():
    """Verify validate_wav_pcm rejects non-RIFF/WAVE containers."""
    with pytest.raises(AudioValidationError, match="expected valid RIFF/WAVE"):
        validate_wav_pcm(b"NOT_A_WAVE_CONTAINER_DATA_HERE")


def test_validate_wav_pcm_zero_frames_44byte_empty_wav_rejection():
    """Verify 44-byte empty RIFF/WAVE header with zero frames is strictly rejected."""
    empty_wav = create_pcm16_le_wav_fixture(sample_rate=22050, duration_sec=0.0)
    assert len(empty_wav) == 44
    with pytest.raises(AudioValidationError, match="zero audio frames"):
        validate_wav_pcm(empty_wav)


