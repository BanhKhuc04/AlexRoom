import os
os.environ.setdefault("MQTT_PASSWORD", "test")
os.environ.setdefault("ALEX_API_KEY", "test")

import asyncio
import threading
from unittest.mock import patch

from tests._brain_service_test_client import AsgiTestClient
from alex_brain_client import BrainClientError
from alex_brain_integration import CoreBrainChatResponse
import app as alex_app
from app import ALEX_API_KEY

def test_fastapi_concurrency_heavy_vs_cheap():
    async def run_test():
        client = AsgiTestClient(alex_app.app)

        active_lock = threading.Lock()
        heavy_entry_event = threading.Event()
        heavy_release_event = threading.Event()

        def mock_chat(req, *args, **kwargs):
            if not active_lock.acquire(blocking=False):
                raise BrainClientError("brain_busy")
            try:
                heavy_entry_event.set()
                heavy_release_event.wait()
                return CoreBrainChatResponse(
                    request_id=req.request_id,
                    route="mock",
                    assistant_text="done",
                    tool_results=[]
                )
            finally:
                active_lock.release()

        with patch.object(alex_app.core_brain_integration, "chat", side_effect=mock_chat), \
             patch.object(alex_app.store, "health", return_value={"status": "ok", "latency_ms": 1, "wal_size_mb": 0}):
            # 1. Fire off Request A (heavy)
            async def request_a():
                return await asyncio.to_thread(
                    client.post,
                    "/api/v1/brain/chat",
                    headers={"X-Alex-Key": ALEX_API_KEY},
                    json_body={"request_id": "req-a", "user_text": "heavy"}
                )

            task_a = asyncio.create_task(request_a())

            try:
                # Wait for Request A to enter the locked state
                entered = await asyncio.to_thread(heavy_entry_event.wait, 5.0)
                assert entered, "Request A did not enter heavy dispatch"

                # 2. Fire off Request B (cheap health endpoint)
                async def request_b():
                    return await asyncio.to_thread(
                        client.get,
                        "/api/v1/status"
                    )

                task_b = asyncio.create_task(request_b())
                
                # Request B should complete immediately
                resp_b = await asyncio.wait_for(task_b, timeout=2.0)
                assert resp_b.status_code == 200, f"Status failed: {resp_b.text}"
                
                # 3. Fire off Request C (heavy, should be rejected)
                async def request_c():
                    return await asyncio.to_thread(
                        client.post,
                        "/api/v1/brain/chat",
                        headers={"X-Alex-Key": ALEX_API_KEY},
                        json_body={"request_id": "req-c", "user_text": "heavy 2"}
                    )
                    
                task_c = asyncio.create_task(request_c())
                resp_c = await asyncio.wait_for(task_c, timeout=2.0)
                
                # Assert Request C was rejected with 503 brain_busy
                assert resp_c.status_code == 503
                data_c = resp_c.json()
                assert data_c["detail"]["code"] == "brain_busy"

            finally:
                # 4. Release Request A
                heavy_release_event.set()
            
            # Request A should now finish successfully
            resp_a = await asyncio.wait_for(task_a, timeout=2.0)
            assert resp_a.status_code == 200
            data_a = resp_a.json()
            assert data_a["assistant_text"] == "done"

    asyncio.run(run_test())
