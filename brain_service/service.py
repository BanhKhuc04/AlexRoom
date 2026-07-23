from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import Field, ValidationError

from alex_brain_tools import (
    BRAIN_TOOL_REGISTRY,
    MAX_TOOL_CALLS,
    BrainChatRequest,
    BrainChatResponse,
    BrainToolCall,
    StrictContractModel,
    brain_tool_schemas_for_provider,
)
from brain_service.provider import (
    SYSTEM_INSTRUCTION,
    BrainTextProvider,
    DisabledProvider,
    InvalidProviderResponseError,
    ProviderReply,
    ProviderToolProposal,
)
from brain_service.refusal_policy import apply_forbidden_action_refusal


UNCONFIRMED_SUCCESS_CLAIM = re.compile(
    r"(?:"
    r"\bturned\s+(?:on|off)\s+successfully\b|"
    r"\bsuccessfully\s+(?:turned|executed|completed)\b|"
    r"\baction\s+(?:succeeded|completed|confirmed)\b|"
    r"\bhas\s+been\s+(?:executed|completed|confirmed)\b|"
    r"đã\s+(?:bật|tắt|chuyển|chạy|thực hiện|hoàn thành)\b|"
    r"\bthành\s+công\b"
    r")",
    re.IGNORECASE,
)


class BrainHealthResponse(StrictContractModel):
    status: Literal["ok"] = "ok"
    service: Literal["alex-brain"] = "alex-brain"
    api_version: Literal["v1"] = "v1"
    provider: Literal["not_configured", "configured"] = "not_configured"


class BrainErrorDetail(StrictContractModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=160)
    request_id: str | None = Field(default=None, max_length=64)


class BrainErrorResponse(StrictContractModel):
    error: BrainErrorDetail


class BrainInferenceService:
    """C3 text-inference boundary that validates proposals and never executes them."""

    def __init__(self, provider: BrainTextProvider | None = None) -> None:
        self.provider = provider or DisabledProvider()

    def health(self) -> BrainHealthResponse:
        return BrainHealthResponse(
            provider="configured" if self.provider.configured else "not_configured"
        )

    def chat(self, request: BrainChatRequest) -> BrainChatResponse:
        reply = self.provider.infer(
            system_instruction=SYSTEM_INSTRUCTION,
            user_text=request.user_text,
            tools=brain_tool_schemas_for_provider(),
        )
        response = self._validated_response(request.request_id, reply)
        return apply_forbidden_action_refusal(request, response)

    @property
    def provider_name(self) -> str:
        return self.provider.name

    @staticmethod
    def _validated_response(
        request_id: str,
        reply: ProviderReply,
    ) -> BrainChatResponse:
        if not isinstance(reply.assistant_text, str):
            raise InvalidProviderResponseError("invalid_provider_response")
        if not isinstance(reply.tool_calls, (list, tuple)):
            raise InvalidProviderResponseError("invalid_provider_response")
        if len(reply.tool_calls) > MAX_TOOL_CALLS:
            raise InvalidProviderResponseError("invalid_provider_response")

        validated_calls: list[BrainToolCall] = []
        try:
            for proposal in reply.tool_calls:
                if not isinstance(proposal, ProviderToolProposal):
                    raise InvalidProviderResponseError("invalid_provider_response")
                if not isinstance(proposal.name, str):
                    raise InvalidProviderResponseError("invalid_provider_response")
                if not isinstance(proposal.arguments, str):
                    raise InvalidProviderResponseError("invalid_provider_response")
                arguments = json.loads(proposal.arguments)
                if not isinstance(arguments, dict):
                    raise InvalidProviderResponseError("invalid_provider_response")
                validated_calls.append(
                    BrainToolCall.model_validate(
                        {
                            "name": proposal.name,
                            "arguments": arguments,
                        }
                    )
                )
            response = BrainChatResponse.model_validate(
                {
                    "request_id": request_id,
                    "assistant_text": reply.assistant_text,
                    "tool_calls": validated_calls,
                }
            )
            has_mutation = any(
                BRAIN_TOOL_REGISTRY[call.name].access == "mutation"
                for call in response.tool_calls
            )
            if (
                has_mutation
                and UNCONFIRMED_SUCCESS_CLAIM.search(response.assistant_text)
            ):
                raise InvalidProviderResponseError("invalid_provider_response")
            return response
        except (
            json.JSONDecodeError,
            TypeError,
            ValidationError,
        ):
            raise InvalidProviderResponseError("invalid_provider_response") from None
