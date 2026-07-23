from __future__ import annotations

import re

from alex_brain_tools import BrainChatRequest, BrainChatResponse


# This semantic classifier is defense in depth only. Provider output must pass
# the exact C1 structural validator before this policy can shape user-facing text.
FORBIDDEN_END_ACTION = re.compile(
    r"(?:"
    r"\brelay[_\s-]?[1-4]\b|"
    r"(?:publish|send|use|call|access|direct(?:ly)?|trực\s+tiếp)"
    r".{0,48}\bmqtt\b|"
    r"\bmqtt\b.{0,48}"
    r"(?:publish|direct|trực\s+tiếp|relay|command|bật|tắt)|"
    r"\bgpio\b|"
    r"\bshell\b|"
    r"\braw[\s-]+hardware\b|"
    r"\bbypass(?:ing)?\s+(?:alex\s+)?core\b|"
    r"\bbỏ\s+qua\s+(?:alex\s+)?core\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

FORBIDDEN_ACTION_REFUSAL = (
    "Hành động trực tiếp với relay_1–relay_4, MQTT, GPIO, shell hoặc "
    "bypass ALEX Core không khả dụng. ALEX Brain không thể đề xuất công cụ, "
    "mission, automation hay đường vòng để thực hiện yêu cầu đó."
)


def requires_forbidden_action_refusal(user_text: str) -> bool:
    return FORBIDDEN_END_ACTION.search(user_text) is not None


def apply_forbidden_action_refusal(
    request: BrainChatRequest,
    response: BrainChatResponse,
) -> BrainChatResponse:
    if not requires_forbidden_action_refusal(request.user_text):
        return response
    return BrainChatResponse(
        request_id=request.request_id,
        assistant_text=FORBIDDEN_ACTION_REFUSAL,
        tool_calls=[],
    )
