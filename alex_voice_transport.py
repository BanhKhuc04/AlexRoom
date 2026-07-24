import asyncio
import logging
import json
from typing import Any, Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect

from alex_stt import STTProvider
from alex_voice import (
    VoiceInput,
    VoiceSessionLifecycle,
    VoiceSessionState,
    process_voice_transcript,
)

logger = logging.getLogger("alex.voice.transport")

MAX_SESSION_DURATION_SECONDS = 30
MAX_CHUNK_SIZE_BYTES = 1024 * 512  # 512KB max per chunk
MAX_SESSION_BYTES = 1024 * 1024 * 5 # 5MB max total per session
AUTH_TIMEOUT_SECONDS = 5.0

def is_valid_websocket_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    host = websocket.headers.get("host")
    if not host:
        return False
    # Exact match on scheme + host ensures no cross-origin manipulation
    return origin in (f"http://{host}", f"https://{host}")


class BoundedAudioTransport:
    """Bounded WebSocket transport for receiving audio chunks and managing voice sessions."""

    def __init__(
        self,
        stt_provider: STTProvider,
        router_dispatch: Callable[[Any], Any],
        tts_provider: Any = None,
        playback_sink: Any = None,
        auth_validator: Optional[Callable[[str], bool]] = None
    ) -> None:
        self.stt_provider = stt_provider
        self.router_dispatch = router_dispatch
        self.tts_provider = tts_provider
        self.playback_sink = playback_sink
        self.auth_validator = auth_validator

    async def handle_websocket(self, websocket: WebSocket, session_id: str, request_id: str) -> None:
        if not is_valid_websocket_origin(websocket):
            await websocket.close(code=1008)
            return

        await websocket.accept()

        # Phase 1: Authentication State
        if self.auth_validator:
            try:
                async with asyncio.timeout(AUTH_TIMEOUT_SECONDS):
                    auth_msg = await websocket.receive_json()
                    if auth_msg.get("type") != "auth" or not auth_msg.get("api_key"):
                        await websocket.close(code=1008)
                        return
                    if not self.auth_validator(auth_msg["api_key"]):
                        await websocket.close(code=1008)
                        return
            except (asyncio.TimeoutError, json.JSONDecodeError, KeyError, ValueError, WebSocketDisconnect):
                await websocket.close(code=1008)
                return
            except Exception:
                await websocket.close(code=1008)
                return

        session = VoiceSessionLifecycle(session_id)
        
        try:
            session.transition_to(VoiceSessionState.LISTENING)
        except Exception:
            await websocket.close(code=1003)
            return

        audio_buffer = bytearray()
        
        try:
            # We enforce a maximum session duration to prevent infinite unauthenticated streaming
            async with asyncio.timeout(MAX_SESSION_DURATION_SECONDS):
                while True:
                    # Receive data
                    message = await websocket.receive()
                    
                    if "bytes" in message:
                        chunk = message["bytes"]
                        if len(chunk) > MAX_CHUNK_SIZE_BYTES:
                            logger.warning(f"Session {session_id} exceeded max chunk size")
                            session.cancel()
                            break
                        
                        if len(audio_buffer) + len(chunk) > MAX_SESSION_BYTES:
                            logger.warning(f"Session {session_id} exceeded max session size")
                            session.cancel()
                            break
                            
                        audio_buffer.extend(chunk)
                        
                    elif "text" in message:
                        text = message["text"]
                        if text == "CANCEL":
                            session.cancel()
                            break
                        if text == "DONE":
                            break
                            
        except asyncio.TimeoutError:
            logger.warning(f"Session {session_id} exceeded max duration")
            session.cancel()
        except WebSocketDisconnect:
            logger.info(f"Session {session_id} disconnected unexpectedly")
            session.cancel()
        except Exception as e:
            logger.error(f"Transport error for {session_id}: {e}")
            session.cancel()
            
        # If user cancelled, don't execute
        if session.state == VoiceSessionState.CANCELLED:
            if not websocket.client_state.name == "DISCONNECTED":
                try:
                    await websocket.send_json({"state": "CANCELLED"})
                    await websocket.close()
                except Exception:
                    pass
            # Release memory explicitly
            audio_buffer.clear()
            return
            
        # Process the accumulated audio
        try:
            session.transition_to(VoiceSessionState.TRANSCRIBING)
            
            stt_result = await self.stt_provider.transcribe(session_id, request_id, bytes(audio_buffer))
            
            # Explicitly clear audio memory once passed to STT
            audio_buffer.clear()
            
            voice_input = VoiceInput(
                session_id=session_id,
                request_id=request_id,
                transcript=stt_result.transcript,
                is_final=stt_result.is_final,
                source=stt_result.provider,
                created_at="now"
            )
            
            # Use IntelligenceRouter integration from C1
            # Mocking router_dispatch interface (obj with dispatch method)
            class RouterAdapter:
                def dispatch(self, req):
                    return self._dispatch(req)
            router = RouterAdapter()
            router._dispatch = self.router_dispatch
            
            response = process_voice_transcript(session, voice_input, router)
            
            # Phase 1.0 C7: Bare-In Orchestration Pipeline Integration
            # If the response contains text to speak, synthesize and play
            audio_response = None
            if response.assistant_text and self.tts_provider and self.playback_sink:
                try:
                    # process_voice_transcript already transitions to SPEAKING if needed
                    tts_result = await self.tts_provider.synthesize(session_id, request_id, response.assistant_text)
                    audio_response = tts_result.audio_data
                    
                    # Play the audio
                    await self.playback_sink.play(audio_response)
                except Exception as e:
                    logger.error(f"TTS/Playback error for {session_id}: {e}")
                    # Failure to speak does not fail the whole session's core intent
            
            if response.state == VoiceSessionState.SPEAKING:
                session.transition_to(VoiceSessionState.COMPLETED)
            
            if not websocket.client_state.name == "DISCONNECTED":
                # For transport we may want to send the audio back if it's a remote client,
                # but local playback sink handles it if it's local. We'll send the state anyway.
                await websocket.send_json({
                    "state": session.state.value,
                    "transcript": stt_result.transcript,
                    "assistant_text": response.assistant_text,
                    "error_code": response.error_code
                })
                
        except Exception as e:
            logger.error(f"Processing error for {session_id}: {e}")
            session.cancel()
            
        # Cleanup
        if not websocket.client_state.name == "DISCONNECTED":
            try:
                await websocket.close()
            except Exception:
                pass
