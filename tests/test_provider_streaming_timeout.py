import json
import time
import urllib.error
import urllib.request
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from brain_service.provider import ProviderReply, ProviderStreamEvent
from brain_service.providers.ollama_native import OllamaNativeProvider

@pytest.fixture
def provider():
    return OllamaNativeProvider(
        base_url="http://fake",
        model="test",
        api_key="fake",
        timeout_seconds=5.0,
        stream_first_token_timeout_seconds=0.1,
        stream_idle_timeout_seconds=0.1,
        stream_hard_deadline_seconds=0.3
    )

class FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, t):
        self.timeouts.append(t)

class FakeBufferedReader:
    def __init__(self, raw=None):
        self.raw = raw

class FakeHTTPResponse:
    def __init__(self, sock=None):
        if sock:
            self.fp = FakeBufferedReader(MagicMock(_sock=sock))
        else:
            self.fp = None
        self.read_count = 0
        self.lines = []

    def readline(self, size=-1):
        if self.read_count < len(self.lines):
            val = self.lines[self.read_count]
            self.read_count += 1
            if isinstance(val, Exception):
                raise val
            return val
        return b""

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass

def test_streaming_response_object_layout_does_not_crash(provider):
    sock = FakeSocket()
    resp = FakeHTTPResponse(sock)
    
    resp.lines = [
        b'{"message": {"content": "Hello"}}\n',
        b'{"message": {"content": " World"}}\n',
        b'{"done": true}\n'
    ]

    with patch("urllib.request.urlopen", return_value=resp):
        stream = provider.infer_stream(
            request_id="req1",
            system_instruction="sys",
            user_text="hi",
        )
        events = list(stream)

    assert len(events) == 4
    assert events[0].type == "start"
    assert events[1].type == "text_delta"
    assert events[1].delta == "Hello"
    assert events[2].type == "text_delta"
    assert events[2].delta == " World"
    assert events[3].type == "final"
    assert events[3].assistant_text == "Hello World"

    assert len(sock.timeouts) == 3
    assert sock.timeouts[0] == provider.stream_first_token_timeout_seconds
    assert sock.timeouts[1] == provider.stream_idle_timeout_seconds
    assert sock.timeouts[2] == provider.stream_idle_timeout_seconds

def test_private_socket_layout_mismatch_produces_safe_canonical_failure(provider):
    resp = FakeHTTPResponse(sock=None)
    
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(Exception) as excinfo:
            stream = provider.infer_stream(
                request_id="req1",
                system_instruction="sys",
                user_text="hi",
            )
            events = list(stream)
            
        assert "provider_unavailable" in str(excinfo.value)

def test_hard_deadline_is_enforced(provider):
    sock = FakeSocket()
    resp = FakeHTTPResponse(sock)
    
    def delayed_readline(*args):
        time.sleep(0.4) 
        return b'{"message": {"content": "Hello"}}\n'
        
    resp.readline = delayed_readline
    
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(Exception) as excinfo:
            stream = provider.infer_stream(
                request_id="req1",
                system_instruction="sys",
                user_text="hi",
            )
            events = list(stream)

        assert "provider_timeout" in str(excinfo.value)
