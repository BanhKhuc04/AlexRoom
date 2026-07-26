from __future__ import annotations

import json
from typing import Mapping, Sequence

from brain_service.provider import (
    InvalidProviderResponseError,
    ProviderNotConfiguredError,
    ProviderReply,
    ProviderToolProposal,
    ProviderStreamEvent,
)
from typing import Iterator
from brain_service.providers.openai_compatible import (
    JsonHttpTransport,
    UrllibJsonTransport,
)


OLLAMA_CHAT_PATH = "/api/chat"
OLLAMA_NUM_PREDICT = 512
OLLAMA_KEEP_ALIVE = -1
OLLAMA_WARMUP_NUM_PREDICT = 1


class OllamaNativeProvider:
    name = "ollama_native"
    supports_warmup = True

    def __init__(
        self,
        *,
        base_url: str | None,
        model: str | None,
        api_key: str | None,
        timeout_seconds: float,
        stream_first_token_timeout_seconds: float = 15.0,
        stream_idle_timeout_seconds: float = 10.0,
        stream_hard_deadline_seconds: float = 120.0,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        self.url = self._chat_url(base_url)
        self.model = (model or "").strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.stream_first_token_timeout_seconds = stream_first_token_timeout_seconds
        self.stream_idle_timeout_seconds = stream_idle_timeout_seconds
        self.stream_hard_deadline_seconds = stream_hard_deadline_seconds
        self.transport = transport or UrllibJsonTransport()
        self.configured = bool(self.url and self.model)

    @staticmethod
    def _chat_url(base_url: str | None) -> str:
        normalized = (base_url or "").strip().rstrip("/")
        if not normalized:
            return ""
        if normalized.endswith(OLLAMA_CHAT_PATH):
            return normalized
        return f"{normalized}{OLLAMA_CHAT_PATH}"

    def infer(
        self,
        *,
        system_instruction: str,
        user_text: str,
        tools: Sequence[Mapping[str, object]],
        generation_budget: int | None = None,
    ) -> ProviderReply:
        if not self.configured:
            raise ProviderNotConfiguredError("provider_not_configured")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_text},
            ],
            "think": False,
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": 0,
                "num_predict": generation_budget if generation_budget is not None else OLLAMA_NUM_PREDICT,
            },
        }
        if tools:
            payload["tools"] = list(tools)
        upstream = self.transport.post_json(
            url=self.url,
            headers=headers,
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        return self._parse_response(upstream)

    def infer_stream(
        self,
        *,
        request_id: str,
        system_instruction: str,
        user_text: str,
    ) -> Iterator[ProviderStreamEvent]:
        if not self.configured:
            raise ProviderNotConfiguredError("provider_not_configured")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_text},
            ],
            "think": False,
            "stream": True,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": 0,
                "num_predict": OLLAMA_NUM_PREDICT,
            },
        }

        yield ProviderStreamEvent(type="start", request_id=request_id)
        
        full_text = ""
        stream = self.transport.post_json_stream(
            url=self.url,
            headers=headers,
            payload=payload,
            first_token_timeout_seconds=self.stream_first_token_timeout_seconds,
            idle_timeout_seconds=self.stream_idle_timeout_seconds,
            hard_deadline_seconds=self.stream_hard_deadline_seconds,
        )
        for line in stream:
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                raise InvalidProviderResponseError("invalid_provider_response") from None
                
            msg = chunk.get("message", {})
            content = msg.get("content", "")
            if content:
                full_text += content
                yield ProviderStreamEvent(type="text_delta", delta=content, request_id=request_id)
                
            if chunk.get("done") is True:
                yield ProviderStreamEvent(type="final", assistant_text=full_text, request_id=request_id)
                return

    def warmup(
        self,
        *,
        timeout_seconds: float,
        system_instruction: str,
        tools: Sequence[Mapping[str, object]],
    ) -> None:
        """Prime the canonical prefix without creating a Brain response."""

        if not self.configured:
            raise ProviderNotConfiguredError("provider_not_configured")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        upstream = self.transport.post_json(
            url=self.url,
            headers=headers,
            payload={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_instruction,
                    },
                    {"role": "user", "content": ""},
                ],
                "tools": list(tools),
                "think": False,
                "stream": False,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {
                    "temperature": 0,
                    "num_predict": OLLAMA_WARMUP_NUM_PREDICT,
                },
            },
            timeout_seconds=timeout_seconds,
        )
        if upstream.get("done") is not True:
            raise InvalidProviderResponseError("invalid_provider_response")

    @staticmethod
    def _parse_response(upstream: dict[str, object]) -> ProviderReply:
        message = upstream.get("message")
        if not isinstance(message, dict):
            raise InvalidProviderResponseError("invalid_provider_response")

        content = message.get("content", "")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise InvalidProviderResponseError("invalid_provider_response")

        raw_tool_calls = message.get("tool_calls", [])
        if not isinstance(raw_tool_calls, list):
            raise InvalidProviderResponseError("invalid_provider_response")
        proposals: list[ProviderToolProposal] = []
        for raw_call in raw_tool_calls:
            if not isinstance(raw_call, dict):
                raise InvalidProviderResponseError("invalid_provider_response")
            function = raw_call.get("function")
            if not isinstance(function, dict):
                raise InvalidProviderResponseError("invalid_provider_response")
            arguments = function.get("arguments")
            if not isinstance(arguments, dict):
                raise InvalidProviderResponseError("invalid_provider_response")
            try:
                encoded_arguments = json.dumps(
                    arguments,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError, RecursionError):
                raise InvalidProviderResponseError(
                    "invalid_provider_response"
                ) from None
            proposals.append(
                ProviderToolProposal(
                    name=function.get("name"),
                    arguments=encoded_arguments,
                )
            )
        return ProviderReply(
            assistant_text=content,
            tool_calls=tuple(proposals),
        )
