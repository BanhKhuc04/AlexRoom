from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


SYSTEM_INSTRUCTION = """You are ALEX Brain.
Provide text reasoning and structured proposals only.
You cannot directly control devices. ALEX Core is the final authority.
Only use the tools provided. Never invent tool names or request MQTT, GPIO, shell, raw hardware, or bypass tools.
relay_1..relay_4 are restricted.
Do not claim physical success; actions remain proposals until Core confirms.
For unsupported/dangerous requests, explain unavailability and emit zero tool calls.
If a request is forbidden, do not suggest a workaround (like run_safe_mission or run_safe_automation).
Missions/automations remain allowed only if the original requested workflow is safe."""


class ProviderNotConfiguredError(RuntimeError):
    pass


class ProviderUnavailableError(RuntimeError):
    pass


class ProviderTimeoutError(RuntimeError):
    pass


class InvalidProviderResponseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderToolProposal:
    name: object
    arguments: object


@dataclass(frozen=True, slots=True)
class ProviderReply:
    assistant_text: object
    tool_calls: object


class BrainTextProvider(Protocol):
    name: str
    configured: bool
    supports_warmup: bool

    def infer(
        self,
        *,
        system_instruction: str,
        user_text: str,
        tools: Sequence[Mapping[str, object]],
    ) -> ProviderReply: ...

    def warmup(
        self,
        *,
        timeout_seconds: float,
        system_instruction: str,
        tools: Sequence[Mapping[str, object]],
    ) -> None: ...


class DisabledProvider:
    name = "disabled"
    configured = False
    supports_warmup = False

    def infer(
        self,
        *,
        system_instruction: str,
        user_text: str,
        tools: Sequence[Mapping[str, object]],
    ) -> ProviderReply:
        del system_instruction, user_text, tools
        raise ProviderNotConfiguredError("provider_not_configured")

    def warmup(
        self,
        *,
        timeout_seconds: float,
        system_instruction: str,
        tools: Sequence[Mapping[str, object]],
    ) -> None:
        del timeout_seconds, system_instruction, tools
        raise ProviderNotConfiguredError("provider_not_configured")
