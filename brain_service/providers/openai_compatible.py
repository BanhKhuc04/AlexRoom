from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Mapping, Protocol, Sequence

from brain_service.provider import (
    InvalidProviderResponseError,
    ProviderNotConfiguredError,
    ProviderReply,
    ProviderTimeoutError,
    ProviderToolProposal,
    ProviderUnavailableError,
)


MAX_UPSTREAM_RESPONSE_BYTES = 1_000_000


class JsonHttpTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]: ...


class UrllibJsonTransport:
    """Small standard-library JSON transport isolated to the Brain PC."""

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw_body = response.read(MAX_UPSTREAM_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            error.close()
            raise ProviderUnavailableError("provider_unavailable") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError("provider_timeout") from None
            raise ProviderUnavailableError("provider_unavailable") from None
        except (TimeoutError, socket.timeout):
            raise ProviderTimeoutError("provider_timeout") from None
        except OSError:
            raise ProviderUnavailableError("provider_unavailable") from None

        if len(raw_body) > MAX_UPSTREAM_RESPONSE_BYTES:
            raise InvalidProviderResponseError("invalid_provider_response")
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InvalidProviderResponseError("invalid_provider_response") from None
        if not isinstance(decoded, dict):
            raise InvalidProviderResponseError("invalid_provider_response")
        return decoded


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        url: str | None,
        model: str | None,
        api_key: str | None,
        timeout_seconds: float,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        self.url = (url or "").strip()
        self.model = (model or "").strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport or UrllibJsonTransport()
        self.configured = bool(self.url and self.model)

    def infer(
        self,
        *,
        system_instruction: str,
        user_text: str,
        tools: Sequence[Mapping[str, object]],
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
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        upstream = self.transport.post_json(
            url=self.url,
            headers=headers,
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        return self._parse_response(upstream)

    @staticmethod
    def _parse_response(upstream: dict[str, object]) -> ProviderReply:
        choices = upstream.get("choices")
        if not isinstance(choices, list) or not choices:
            raise InvalidProviderResponseError("invalid_provider_response")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise InvalidProviderResponseError("invalid_provider_response")
        message = first_choice.get("message")
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
            if raw_call.get("type", "function") != "function":
                raise InvalidProviderResponseError("invalid_provider_response")
            function = raw_call.get("function")
            if not isinstance(function, dict):
                raise InvalidProviderResponseError("invalid_provider_response")
            proposals.append(
                ProviderToolProposal(
                    name=function.get("name"),
                    arguments=function.get("arguments"),
                )
            )
        return ProviderReply(
            assistant_text=content,
            tool_calls=tuple(proposals),
        )
