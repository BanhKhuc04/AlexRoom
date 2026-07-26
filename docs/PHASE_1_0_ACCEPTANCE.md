# Phase 1.0 Acceptance Document

## Architecture & Trust Boundaries
ALEX Voice architecture (Phase 1.0) is implemented as a bounded software transport layer. It operates entirely outside the trusted Core logic. The Voice layer receives audio, translates it via isolated STT boundaries, passes the resulting text verbatim to `IntelligenceRouter`, and plays back the router's assistant response via TTS boundaries.

- **Audio Transport**: Uses FastAPI WebSockets.
- **Origin Validation**: Explicit strict validation ensures connection originates only from trusted configured hosts (via `websocket.headers.get("origin")` exact match).
- **Authentication**: Long-lived API keys are NOT exposed in the URL. A short-timeout first-message protocol requires `{"type": "auth", "api_key": ...}`.
- **Resource Limits**: 
  - `MAX_CHUNK_SIZE_BYTES` = 512KB
  - `MAX_SESSION_BYTES` = 5MB (enforced strictly via rolling byte accumulator)
  - `MAX_SESSION_DURATION_SECONDS` = 30s
- **Safety Boundary**: Voice bypasses ZERO security policies. It does NOT publish MQTT directly. All commands route through `IntelligenceRouter` and the canonical `SafetyPolicy`.
- **WSS Requirement**: Unencrypted local deployments are acceptable only on trusted Tailscale networks. Otherwise, TLS/WSS is strictly required for untrusted networks.

## Speech-to-Text (STT)
- **Adapter**: `STTProvider` Protocol implemented.
- **Local Implementation**: `FasterWhisperSTTProvider` executes in an `asyncio.run_in_executor` thread pool to prevent blocking the event loop.
- **Privacy**: No persistent raw audio logs. Graceful degradation via `_HAS_WHISPER` constant.

## Text-to-Speech (TTS) & Playback
- **Adapter**: `TTSProvider` and `PlaybackSink` interfaces defined.
- **Local Implementation**: `LocalTTSProvider` interfaces with standard TTS engines (e.g., Piper).
- **Privacy**: TTS only parses authoritative `assistant_text` from the router. No command execution or payload extraction occurs here.

## Barge-in & Wake Word
- **Barge-in**: Implemented via `VoiceSessionLifecycle`. Cancellation immediately drops the session and stops downstream STT/TTS calls. Any commands already dispatched by Core remain unmodified (true hardware state).
- **Wake Word**: Boundary established via `WakeWordProvider`. Deaf mode implemented. No execution triggers, only session state transitions from `IDLE` to `LISTENING`.

## Optional Dependencies
The system continues to boot and operate fully without Voice dependencies. `faster-whisper` and TTS binaries are imported lazily/conditionally.

## Validation Results
- Python backend: `1402 passed`
- JS frontend: `110 passed`
- E2E Tests: Fully mocked pipeline completed (STT -> Router -> TTS -> Playback).
- WebSocket Security: Validated 1008 disconnections on missing/invalid keys.

## Real Hardware Status
- Real Microphone: BLOCKED (No physical integration yet)
- STT/TTS Models: BLOCKED (No physical multi-GB local models downloaded in CI/Test environment)
- Speaker: BLOCKED
- Wake Model: BLOCKED

## Limitations
Hardware constraints mean this is a software architectural acceptance. Physical deployment to the target host requires model provisioning.
