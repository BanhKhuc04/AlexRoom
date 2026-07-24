import asyncio
from typing import Protocol, Callable
from enum import Enum

class WakeWordState(Enum):
    IDLE = "idle"
    DETECTED = "detected"
    ERROR = "error"

class WakeWordProvider(Protocol):
    async def listen(self) -> WakeWordState:
        """
        Listen for the wake word. Returns DETECTED when the wake word is detected.
        Should not block the main event loop.
        """
        ...
        
    def stop(self) -> None:
        """Stop listening."""
        ...

    def set_mute(self, mute: bool) -> None:
        """Enable or disable mute mode (deaf mode)."""
        ...


class DeterministicWakeWordProvider:
    """Mock wake word provider for testing."""
    
    def __init__(self) -> None:
        self.muted = False
        self.stopped = False
        self.trigger_event = asyncio.Event()

    async def listen(self) -> WakeWordState:
        if self.stopped:
            return WakeWordState.ERROR
            
        while not self.stopped:
            await self.trigger_event.wait()
            if self.stopped:
                return WakeWordState.ERROR
                
            self.trigger_event.clear()
            if not self.muted:
                return WakeWordState.DETECTED
                
        return WakeWordState.ERROR

    def stop(self) -> None:
        self.stopped = True
        self.trigger_event.set()

    def set_mute(self, mute: bool) -> None:
        self.muted = mute

    def simulate_wake_word(self) -> None:
        """Helper to simulate detection from a test."""
        self.trigger_event.set()
