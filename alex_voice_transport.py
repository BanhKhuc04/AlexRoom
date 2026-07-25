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
            if not websocket.client_state.name == "DISCONNECTED":
                await websocket.send_json({
                    "type": "auth_ok",
                    "state": "listening",
                    "session_id": session_id,
                    "request_id": request_id
                })
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
                        try:
                            parsed_msg = json.loads(text)
                            msg_type = parsed_msg.get("type")
                            if msg_type in ["cancel", "CANCEL"]:
                                session.cancel()
                                break
                            if msg_type in ["end_audio", "done", "DONE"]:
                                break
                        except Exception:
                            if text in ["CANCEL", "cancel"]:
                                session.cancel()
                                break
                            if text in ["DONE", "done", "end_audio"]:
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
                    await websocket.send_json({
                        "type": "completed",
                        "state": "CANCELLED",
                        "session_id": session_id,
                        "request_id": request_id,
                        "reason": "cancelled"
                    })
                    await websocket.close()
                except Exception:
                    pass
            # Release memory explicitly
            audio_buffer.clear()
            return
            
        # Process the accumulated audio
        try:
            session.transition_to(VoiceSessionState.TRANSCRIBING)
            if not websocket.client_state.name == "DISCONNECTED":
                await websocket.send_json({
                    "type": "transcribing",
                    "session_id": session_id,
                    "request_id": request_id
                })
            
            try:
                stt_result = await self.stt_provider.transcribe(session_id, request_id, bytes(audio_buffer))
            except Exception as stt_err:
                logger.error(f"STT failed for {session_id}: {stt_err}")
                if not websocket.client_state.name == "DISCONNECTED":
                    raw_code = getattr(stt_err, "code", "stt_unavailable")
                    error_code = getattr(raw_code, "value", str(raw_code))
                    await websocket.send_json({
                        "type": "error",
                        "session_id": session_id,
                        "request_id": request_id,
                        "error_code": str(error_code),
                        "detail": str(stt_err)
                    })
                    await websocket.close()
                audio_buffer.clear()
                return

            # Explicitly clear audio memory once passed to STT
            audio_buffer.clear()
            
            if not stt_result.transcript.strip():
                if not websocket.client_state.name == "DISCONNECTED":
                    await websocket.send_json({
                        "type": "no_speech",
                        "session_id": session_id,
                        "request_id": request_id
                    })
                session.transition_to(VoiceSessionState.COMPLETED)
                return

            if not websocket.client_state.name == "DISCONNECTED":
                await websocket.send_json({
                    "type": "transcript_final",
                    "session_id": session_id,
                    "request_id": request_id,
                    "transcript": stt_result.transcript
                })
            
            voice_input = VoiceInput(
                session_id=session_id,
                request_id=request_id,
                transcript=stt_result.transcript,
                is_final=stt_result.is_final,
                source=stt_result.provider,
                created_at="now"
            )
            
            if not websocket.client_state.name == "DISCONNECTED":
                await websocket.send_json({
                    "type": "thinking",
                    "session_id": session_id,
                    "request_id": request_id
                })

            # Use IntelligenceRouter integration
            class RouterAdapter:
                def dispatch(self, req):
                    return self._dispatch(req)
            router = RouterAdapter()
            router._dispatch = self.router_dispatch
            
            response = process_voice_transcript(session, voice_input, router)
            
            if response.state == VoiceSessionState.FAILED:
                if not websocket.client_state.name == "DISCONNECTED":
                    await websocket.send_json({
                        "type": "error",
                        "session_id": session_id,
                        "request_id": request_id,
                        "error_code": response.error_code or "internal_error",
                        "detail": "Không có phản hồi từ hệ thống."
                    })
                    await websocket.close()
                return
            
            if response.assistant_text and not websocket.client_state.name == "DISCONNECTED":
                await websocket.send_json({
                    "type": "assistant_text",
                    "session_id": session_id,
                    "request_id": request_id,
                    "text": response.assistant_text
                })

            # TTS Audio Return Path
            import base64
            if response.assistant_text and self.tts_provider:
                try:
                    tts_result = await self.tts_provider.synthesize(session_id, request_id, response.assistant_text)
                    if tts_result and tts_result.audio_data and len(tts_result.audio_data) > 44:
                        session.transition_to(VoiceSessionState.SPEAKING)
                        audio_b64 = base64.b64encode(tts_result.audio_data).decode("utf-8")
                        if not websocket.client_state.name == "DISCONNECTED":
                            await websocket.send_json({
                                "type": "speaking",
                                "session_id": session_id,
                                "request_id": request_id,
                                "audio_base64": audio_b64,
                                "audio_format": tts_result.metadata.get("audio_format", "wav"),
                                "sample_rate": tts_result.metadata.get("sample_rate", 22050),
                                "channels": tts_result.metadata.get("channels", 1),
                                "sample_width": tts_result.metadata.get("sample_width", 2)
                            })

                        if self.playback_sink and hasattr(self.playback_sink, "play"):
                            try:
                                await self.playback_sink.play(tts_result.audio_data)
                            except Exception:
                                pass
                except Exception as tts_err:
                    logger.warning(f"TTS synthesis failed for {session_id}: {tts_err}")
                    if not websocket.client_state.name == "DISCONNECTED":
                        await websocket.send_json({
                            "type": "error",
                            "session_id": session_id,
                            "request_id": request_id,
                            "error_code": "tts_unavailable",
                            "detail": str(tts_err)
                        })
            
            if session.state in (VoiceSessionState.THINKING, VoiceSessionState.ACTING, VoiceSessionState.SPEAKING):
                session.transition_to(VoiceSessionState.COMPLETED)
            
            if not websocket.client_state.name == "DISCONNECTED":
                await websocket.send_json({
                    "type": "completed",
                    "state": session.state.value,
                    "session_id": session_id,
                    "request_id": request_id,
                    "transcript": stt_result.transcript,
                    "assistant_text": response.assistant_text,
                    "error_code": response.error_code
                })
                
        except Exception as e:
            logger.error(f"Processing error for {session_id}: {e}")
            session.cancel()
            if not websocket.client_state.name == "DISCONNECTED":
                try:
                    await websocket.send_json({
                        "type": "error",
                        "session_id": session_id,
                        "request_id": request_id,
                        "error_code": "internal_failure",
                        "detail": str(e)
                    })
                except Exception:
                    pass
            
        # Cleanup
        if not websocket.client_state.name == "DISCONNECTED":
            try:
                await websocket.close()
            except Exception:
                pass
