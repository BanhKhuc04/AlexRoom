import asyncio
from alex_voice import VoiceSessionLifecycle, VoiceSessionState, process_voice_transcript, VoiceInput
from alex_brain_integration import CoreBrainChatResponse

def debug():
    session = VoiceSessionLifecycle("sess1")
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    
    voice_input = VoiceInput(
        session_id="sess1",
        request_id="req1",
        transcript="xin chào",
        is_final=True,
        source="local_stt",
        created_at="now"
    )
    
    class DummyRouter:
        def dispatch(self, req):
            return CoreBrainChatResponse(
                assistant_text="",
                tool_results=[],
                route="chat"
            )
            
    try:
        response = process_voice_transcript(session, voice_input, DummyRouter())
        print("Response:", response)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("Exception!", e)

if __name__ == "__main__":
    debug()
