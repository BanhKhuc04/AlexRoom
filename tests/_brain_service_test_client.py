from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from fastapi import FastAPI


@dataclass(frozen=True)
class AsgiResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    def json(self) -> dict[str, object]:
        return json.loads(self.body)


class AsgiTestClient:
    """Minimal dependency-free HTTP harness for the Brain ASGI boundary."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def get(self, path: str) -> AsgiResponse:
        return self.request("GET", path)

    def post(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> AsgiResponse:
        return self.request("POST", path, headers=headers, json_body=json_body)

    def post_raw(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes,
    ) -> AsgiResponse:
        return asyncio.run(
            self._request("POST", path, headers=headers, raw_body=body)
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> AsgiResponse:
        return asyncio.run(
            self._request(method, path, headers=headers, json_body=json_body)
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None,
        json_body: dict[str, object] | None = None,
        raw_body: bytes | None = None,
    ) -> AsgiResponse:
        body = raw_body if raw_body is not None else (
            b"" if json_body is None else json.dumps(json_body).encode("utf-8")
        )
        encoded_headers = [
            (name.lower().encode("ascii"), value.encode("utf-8"))
            for name, value in (headers or {}).items()
        ]
        if json_body is not None or raw_body is not None:
            encoded_headers.append((b"content-type", b"application/json"))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": encoded_headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        request_sent = False
        messages: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            messages.append(message)

        await self.app(scope, receive, send)
        start = next(
            message
            for message in messages
            if message["type"] == "http.response.start"
        )
        response_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        response_headers = {
            bytes(name).decode("latin-1"): bytes(value).decode("latin-1")
            for name, value in start.get("headers", [])
        }
        return AsgiResponse(
            status_code=int(start["status"]),
            body=response_body,
            headers=response_headers,
        )
