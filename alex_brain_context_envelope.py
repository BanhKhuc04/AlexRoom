from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from alex_brain_tools import BrainChatRequest, BrainRelevantContext
from alex_intent_planner import IntelligencePlan
from alex_knowledge_contracts import SystemKnowledgeSnapshot
from alex_relevant_context import build_relevant_context
from alex_tool_narrowing import narrow_brain_tools


BRAIN_RELEVANT_CONTEXT_ENV_NAME: Final = (
    "ALEX_BRAIN_RELEVANT_CONTEXT_ENABLED"
)
BRAIN_RELEVANT_CONTEXT_TRUE_VALUES: Final = frozenset(
    {"1", "true", "yes", "on"}
)


def brain_relevant_context_enabled(
    environ: Mapping[str, str],
) -> bool:
    """Parse the independent opt-in flag; unknown values stay disabled."""

    value = environ.get(BRAIN_RELEVANT_CONTEXT_ENV_NAME, "")
    return (
        isinstance(value, str)
        and value.strip().lower()
        in BRAIN_RELEVANT_CONTEXT_TRUE_VALUES
    )


def build_guarded_brain_request(
    *,
    request: BrainChatRequest,
    plan: IntelligencePlan,
    snapshot: SystemKnowledgeSnapshot,
) -> BrainChatRequest:
    """Build one bounded request; this grants no execution authority."""

    context = build_relevant_context(plan, snapshot)
    narrowing = narrow_brain_tools(plan, context)
    wire_context = BrainRelevantContext.model_validate(
        context.to_compact_dict()
    )
    return BrainChatRequest(
        request_id=request.request_id,
        user_text=request.user_text,
        context=wire_context,
        allowed_tools=list(narrowing.selected_tool_names),
    )


def build_fail_closed_brain_request(
    request: BrainChatRequest,
) -> BrainChatRequest:
    """Preserve text reasoning while exposing no tools after local failure."""

    return BrainChatRequest(
        request_id=request.request_id,
        user_text=request.user_text,
        allowed_tools=[],
    )


def build_legacy_brain_request(
    request: BrainChatRequest,
) -> BrainChatRequest:
    """Strip any user-supplied enhanced fields at the Core boundary."""

    return BrainChatRequest(
        request_id=request.request_id,
        user_text=request.user_text,
    )
