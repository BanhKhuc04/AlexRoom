# ALEX NEXUS OS — Architecture Correction Register

This register documents architectural debt and corrections identified during Phase 1.0 forensic audits. It serves as the authoritative guide for runtime alignment and future phases.

---

## 1. Classifications

### FIX_NOW_PHASE_1_0 (Resolved in Phase 1.0 Master Correction)
- **Browser Voice WebSocket Missing**: Frontend lacked WebSocket transport client for `/api/v1/voice/stream`.
- **Browser Audio Transport Missing**: Frontend microphone button only rendered Canvas visual waveforms without capturing or streaming PCM audio chunks to Core.
- **Text Input Bypassing Intelligence Router**: Free-text entered into `#commandInput` evaluated hardcoded client-side regex instead of delegating natural language intent to `IntelligenceRouter`.
- **Frontend / Backend State Divergence**: Frontend Orb visual states operated on client-side JS `setTimeout` timers instead of syncing with backend `VoiceSessionLifecycle`.
- **Assistant Response Not Wired**: Natural language assistant responses (`assistant_text`) were not rendered on Presence or Command Center UI surfaces.
- **TTS Browser Playback Missing**: Frontend possessed no Web Audio PCM/audio decode playback path for synthesized assistant speech.
- **STT/TTS Workload Placement**: Orange Pi Core was incorrectly instantiating heavy ML models (`faster-whisper`, `piper`) locally instead of delegating compute to ALEX Brain PC.
- **Stale Service Worker / Cache Version**: Cache version `safety-v4` was obsolete and prevented updated JS modules from activating without manual browser cache purges.
- **Local TTS Engine Integration**: Placeholder synthesis replaced with real Piper TTS production runtime (`piper-tts==1.5.0` with `vi_VN-vais1000-medium`) on ALEX Brain PC, featuring WAV 22050 Hz container validation and speech pronunciation normalization.


---

## 2. DEFER_NEXT_PHASE (Scheduled for Phase 1.1 / Phase 2)
- **ScriptProcessorNode Deprecation**: `AudioRecorder` currently uses `ScriptProcessorNode` for 16kHz PCM downsampling. Scheduled for `AudioWorklet` migration in Phase 1.1.
- **`aria-hidden` Retained Focus Warning**: Browser console accessibility warning when modal dialogs set `aria-hidden` while an inner element retains focus.
- **Repeated OTA 401 Noise**: Background OTA status polling generating 401 console logs when `X-Alex-Key` is unverified.
- **Full Deletion of Legacy UI Helper Methods**: Non-reachable legacy intent methods retained safely for backward workspace compatibility until UI rewrite.
- **Global Event Bus Redesign**: EventSource SSE retained alongside WebSocket for telemetry streaming until a unified multi-channel socket is introduced.
- **Multi-Turn Conversation Persistence**: Long-term conversational context history storage across browser reloads.
- **Hardware Wake-Word Model**: Physical wake-word DSP chip integration on ESP32/Orange Pi hardware.
- **Multi-Client Voice Arbitration**: Concurrently arbitrating multiple active microphone sessions across separate browser clients.

---

## 3. LONG_TERM_REFACTOR & KEEP

### KEEP (Canonical Foundations)
- `core-renderer.js` & `core-visuals.js`: High-performance 2D/WebGL Canvas particle & orbit rendering.
- `audio-waveform.js`: Visual Web Audio AnalyserNode FFT graph for reactive UI visualizer.
- `sound-engine.js`: Centralized Web Audio oscillator sound effect (SFX) cues.
- **Command Lifecycle & Evidence Panel**: Authoritative Reported State tracking (`V1Command` lifecycle & `DeviceCommand` phases).
- **Orange Pi Core Authority Boundary**: Orange Pi Core remains the sole hardware authority, MQTT broker, and SafetyPolicy enforcer. Brain PC is purely compute.
