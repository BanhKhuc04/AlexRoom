# ALEX Brain PC — Piper TTS Voice Provisioning Guide

This document defines the production provisioning process for Piper TTS on the ALEX Brain PC (`192.168.0.216`).

---

## 1. Directory & File Structure

The Piper TTS voice model files must reside in:

```text
/var/lib/alex-brain/models/piper/
```

Target voice model: `vi_VN-vais1000-medium`

Required files:
1. `vi_VN-vais1000-medium.onnx` (ONNX model weights binary)
2. `vi_VN-vais1000-medium.onnx.json` (Voice synthesis configuration metadata)

> [!IMPORTANT]
> Both `.onnx` and `.onnx.json` files are strictly required by Piper. Do not commit model binary files to Git repository.

---

## 2. Model Download & Installation Commands

Execute as operator or with `sudo` on the Brain PC:

```bash
# 1. Ensure target directory exists with correct alex-brain ownership
sudo mkdir -p /var/lib/alex-brain/models/piper
sudo chown -R alex-brain:alex-brain /var/lib/alex-brain/models/piper
sudo chmod 755 /var/lib/alex-brain/models/piper

# 2. Download Vietnamese voice model and configuration
cd /var/lib/alex-brain/models/piper/

sudo -u alex-brain wget -O vi_VN-vais1000-medium.onnx \
  "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx"

sudo -u alex-brain wget -O vi_VN-vais1000-medium.onnx.json \
  "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx.json"

# 3. Verify permissions
sudo chown alex-brain:alex-brain /var/lib/alex-brain/models/piper/vi_VN-vais1000-medium.onnx*
sudo chmod 644 /var/lib/alex-brain/models/piper/vi_VN-vais1000-medium.onnx*
```

---

## 3. Environment Configuration

In `/etc/alex/alex-brain.env` (loaded by `alex-brain.service`):

```ini
# Real Piper TTS Production Configuration
ALEX_TTS_PROVIDER=piper
ALEX_PIPER_BACKEND=python
ALEX_PIPER_VOICE=vi_VN-vais1000-medium
ALEX_PIPER_MODEL_DIR=/var/lib/alex-brain/models/piper
ALEX_TTS_NAME_PRONUNCIATION=A-lếch
```

---

## 4. Manual Verification & Real Synthesis Test

Test synthesis directly under `alex-brain` service user context:

```bash
sudo -u alex-brain /opt/alex/brain/.venv/bin/python -c "
import asyncio
from alex_local_tts import LocalTTSProvider

async def test():
    provider = LocalTTSProvider()
    res = await provider.synthesize('test-s1', 'test-r1', 'Xin chào ALEX, hệ thống đã sẵn sàng.')
    print(f'Synthesized {len(res.audio_data)} bytes WAV metadata={res.metadata}')
    with open('/tmp/alex-tts-test.wav', 'wb') as f:
        f.write(res.audio_data)

asyncio.run(test())
"
```

Verify output audio formatting:

```bash
file /tmp/alex-tts-test.wav
# Expected: RIFF (little-endian) data, WAVE audio, Microsoft PCM, 16 bit, mono 22050 Hz
```
