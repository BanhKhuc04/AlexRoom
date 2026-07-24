import asyncio
import logging
from typing import Any, Callable

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
MAX_CHUNK_SIZE_BYTES = 1024 * 1024 * 2  # 2MB max per chunk

class BoundedAudioTransport:
    """Bounded WebSocket transport for receiving audio chunks and managing voice sessions."""

    def __init__(self, stt_provider: STTProvider, router_dispatch: Callable[[Any], Any]) -> None:
        self.stt_provider = stt_provider
        self.router_dispatch = router_dispatch

    async def handle_websocket(self, websocket: WebSocket, session_id: str, request_id: str) -> None:
        await websocket.accept()
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
            return
            
        # Process the accumulated audio
        try:
            session.transition_to(VoiceSessionState.TRANSCRIBING)
            
            stt_result = await self.stt_provider.transcribe(session_id, request_id, bytes(audio_buffer))
            
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
            
            if not websocket.client_state.name == "DISCONNECTED":
                await websocket.send_json({
                    "state": response.state.value,
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
