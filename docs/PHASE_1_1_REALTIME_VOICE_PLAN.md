# ALEX NEXUS OS — PHASE 1.1 REALTIME VOICE PLAN

This document outlines the architectural plan for Phase 1.1, transitioning ALEX NEXUS OS from the current request/response voice architecture (Phase 1.0) to a fully streaming, realtime conversational AI system.

## 1. Target Architecture Flow

The Phase 1.1 real-time voice interaction will follow this pipeline:

1. **Browser Audio Stream**: Continuous WebSocket transmission of raw audio chunks from the frontend.
2. **Silero VAD**: Edge or server-side Voice Activity Detection filtering non-speech frames.
3. **Smart Turn**: Semantic end-of-speech detection to determine when the user has finished speaking, rather than relying solely on silence gaps.
4. **Streaming/Partial STT**: Generating interim transcription hypotheses (partial results) for instant UI feedback and early LLM routing.
5. **ConversationSession / Context**: Maintaining multi-turn conversation memory, speaker context, and multimodal awareness across interactions.
6. **Streaming LLM**: Receiving inference tokens word-by-word.
7. **Sentence Chunker**: Buffering LLM tokens into complete semantic units (sentences/clauses) suitable for prosodic TTS.
8. **Streaming TTS**: Generating audio for each chunk immediately as it completes, reducing time-to-first-byte (TTFB).
9. **Browser Audio Queue**: Frontend playback queue managing continuous, gapless playback of incoming audio chunks.
10. **Barge-in**: Immediate interruption of the audio queue and backend processes when new user speech is detected.

## 2. Technical Evaluation Candidates

The following technologies and frameworks will be evaluated for implementing the streaming pipeline:

- **Silero VAD**: For robust, low-latency voice activity detection.
- **Pipecat**: To orchestrate the complex multimodal streaming pipeline and handle WebRTC negotiations.
- **Pipecat Smart Turn**: To handle conversational turn-taking intelligently.
- **LiveKit Agents Architecture**: Alternative WebRTC transport and agent framework.
- **whisper.cpp**: High-performance, low-latency local STT on constrained hardware.
- **llama.cpp**: Fast, quantized local LLM execution.
- **Piper Streaming API**: For continuous TTS audio generation.

## 3. Core Constraints

- **Core Final Authority**: The Orange Pi Core must remain the final authority for all hardware control, MQTT publishing, and SafetyPolicy enforcement.
- **Bypass Prevention**: The Brain PC must never directly control GPIO or bypass the Core's security gateway.
- **Privacy First**: All processing (STT, LLM, TTS) must remain local or strictly opt-in for hybrid cloud capabilities.

This plan serves as a blueprint. Implementation is strictly deferred until Phase 1.1 development begins.
