import pytest
import asyncio

from alex_wake_word import DeterministicWakeWordProvider, WakeWordState

def test_deterministic_wake_word_detection():
    async def run():
        provider = DeterministicWakeWordProvider()
        
        # Start listening in a background task
        listen_task = asyncio.create_task(provider.listen())
        
        # Simulate wake word
        provider.simulate_wake_word()
        
        result = await listen_task
        assert result == WakeWordState.DETECTED
        
    asyncio.run(run())

def test_deterministic_wake_word_mute():
    async def run():
        provider = DeterministicWakeWordProvider()
        provider.set_mute(True)
        
        listen_task = asyncio.create_task(provider.listen())
        
        # Simulate wake word while muted
        provider.simulate_wake_word()
        
        # We need to add a timeout because if muted, it will just wait for the next event.
        # But wait, our DeterministicWakeWordProvider loop goes back to wait. Let's cancel it instead of waiting forever.
        # If it returns DETECTED, that's a failure.
        
        # Instead, let's stop it after a small delay.
        await asyncio.sleep(0.01)
        provider.stop()
        
        result = await listen_task
        assert result == WakeWordState.ERROR
        
    asyncio.run(run())

def test_deterministic_wake_word_stop():
    async def run():
        provider = DeterministicWakeWordProvider()
        listen_task = asyncio.create_task(provider.listen())
        
        provider.stop()
        
        result = await listen_task
        assert result == WakeWordState.ERROR
        
    asyncio.run(run())
