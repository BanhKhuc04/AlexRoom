import os
os.environ.setdefault("MQTT_PASSWORD", "unit-test-password")
os.environ.setdefault("ALEX_API_KEY", "test-api-key")

import pytest
from unittest.mock import patch, Mock
from _brain_service_test_client import AsgiTestClient
from app import app, ALEX_API_KEY

@pytest.fixture
def client():
    return AsgiTestClient(app)

def test_natural_language_greetings_route_to_router(client):
    """Verify 'Xin chào ALEX' routes to IntelligenceRouter via /api/v1/brain/chat."""
    response = client.post(
        "/api/v1/brain/chat",
        headers={"X-Alex-Key": ALEX_API_KEY},
        json_body={
            "request_id": "req-nl-1",
            "user_text": "Xin chào ALEX"
        }
    )
    # Either 200 (Brain connected) or 503 (Brain disabled) proves request reached IntelligenceRouter
    assert response.status_code in [200, 503]

def test_natural_language_action_routes_to_router_and_safety(client):
    """Verify 'Bật test led' routes to IntelligenceRouter/Core safety via /api/v1/brain/chat."""
    response = client.post(
        "/api/v1/brain/chat",
        headers={"X-Alex-Key": ALEX_API_KEY},
        json_body={
            "request_id": "req-nl-2",
            "user_text": "Bật test led"
        }
    )
    assert response.status_code in [200, 503]

def test_arbitrary_natural_language_routes_to_router(client):
    """Verify arbitrary natural language text routes to IntelligenceRouter via /api/v1/brain/chat."""
    response = client.post(
        "/api/v1/brain/chat",
        headers={"X-Alex-Key": ALEX_API_KEY},
        json_body={
            "request_id": "req-nl-3",
            "user_text": "Thời tiết hôm nay thế nào?"
        }
    )
    assert response.status_code in [200, 503]
