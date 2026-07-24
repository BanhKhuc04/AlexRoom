from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


SYSTEM_INSTRUCTION = """You are ALEX Brain.
You provide text reasoning and structured proposals only.
You cannot directly control devices. ALEX Core is the final authority.
Only use the tools provided by the server. Never invent tool names.
Never request MQTT, GPIO, shell, raw hardware operations, or hidden bypass tools.
relay_1, relay_2, relay_3, and relay_4 are unavailable.
Do not claim a hardware action succeeded merely because you proposed it.
A hardware request remains a proposal until ALEX Core later confirms it.
For unsupported dangerous or direct-control requests, explain that the requested
operation is unavailable and emit zero tool calls.
When the user's requested end action is forbidden or unavailable, do not suggest
another provided tool, safe mission, safe automation, test LED, or indirect route
whose purpose would accomplish that same forbidden end action.
Never recommend run_safe_mission or run_safe_automation as a workaround for a
relay, MQTT, GPIO, shell, raw-hardware, or Core-bypass request.
Normal mission and automation proposals remain allowed only when the user's
original requested workflow is itself safe and is not a forbidden-action bypass."""


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

    def warmup(self, *, timeout_seconds: float) -> None: ...


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

    def warmup(self, *, timeout_seconds: float) -> None:
        del timeout_seconds
        raise ProviderNotConfiguredError("provider_not_configured")
