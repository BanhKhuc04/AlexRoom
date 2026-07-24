from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from alex_brain_tools import (
    BRAIN_TOOL_REGISTRY,
    TOOL_NAMES,
    ToolAccess,
    ToolName,
    ToolRisk,
)
from alex_intelligence import IntelligenceRoute
from alex_intent_planner import IntelligencePlan, IntentStep
from alex_knowledge_contracts import KNOWLEDGE_SCHEMA_VERSION
from alex_relevant_context import (
    RELEVANT_CONTEXT_SCHEMA_VERSION,
    RelevantContext,
    RelevantContextReason,
    RelevantContextScope,
    RelevantContextSection,
    RelevantContextSectionKind,
)


TOOL_NARROWING_SCHEMA_VERSION: Final = 1
_TOOL_ORDER: Final = {
    name: index
    for index, name in enumerate(TOOL_NAMES)
}
_RELAY_CAPABILITIES: Final = frozenset(
    f"relay_{index}"
    for index in range(1, 5)
)


class ToolNarrowingReason(str, Enum):
    SELECTED_SYSTEM_STATUS = "selected_system_status"
    SELECTED_DEVICE_LIST = "selected_device_list"
    SELECTED_DEVICE_DETAIL = "selected_device_detail"
    SELECTED_EXACT_SAFE_ACTION = "selected_exact_safe_action"
    GENERAL_NO_TOOLS = "general_no_tools"
    RESTRICTED_CAPABILITY = "restricted_capability"
    DEVICE_NOT_FOUND = "device_not_found"
    AMBIGUOUS_PLAN = "ambiguous_plan"
    MULTI_INTENT_UNSUPPORTED = "multi_intent_unsupported"
    NO_CANONICAL_TOOL = "no_canonical_tool"
    MALFORMED_INPUT = "malformed_input"
    UNSUPPORTED_CONTEXT_SCHEMA = "unsupported_context_schema"
    UNSUPPORTED_KNOWLEDGE_SCHEMA = "unsupported_knowledge_schema"


@dataclass(frozen=True, slots=True)
class ToolSelection:
    name: ToolName
    access: ToolAccess
    risk: ToolRisk
    relevant_subjects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        definition = BRAIN_TOOL_REGISTRY.get(self.name)
        if definition is None:
            raise ValueError("tool_selection_must_use_canonical_tool")
        if (
            self.access != definition.access
            or self.risk != definition.risk
        ):
            raise ValueError("tool_selection_metadata_must_match_catalog")
        object.__setattr__(
            self,
            "relevant_subjects",
            tuple(self.relevant_subjects),
        )

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "access": self.access,
            "risk": self.risk,
            "relevant_subjects": list(self.relevant_subjects),
        }


@dataclass(frozen=True, slots=True)
class ToolNarrowingResult:
    narrowing_schema_version: int = field(
        init=False,
        default=TOOL_NARROWING_SCHEMA_VERSION,
    )
    context_schema_version: int
    knowledge_schema_version: int
    selected_tools: tuple[ToolSelection, ...]
    reason: ToolNarrowingReason
    incomplete: bool
    authorizes_execution: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        selected = tuple(self.selected_tools)
        names = tuple(item.name for item in selected)
        if len(names) != len(set(names)):
            raise ValueError("tool_narrowing_duplicate_selection")
        ordered = tuple(
            sorted(
                selected,
                key=lambda item: _TOOL_ORDER[item.name],
            )
        )
        object.__setattr__(self, "selected_tools", ordered)

    @property
    def selected_tool_names(self) -> tuple[ToolName, ...]:
        return tuple(item.name for item in self.selected_tools)

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "narrowing_schema_version": self.narrowing_schema_version,
            "context_schema_version": self.context_schema_version,
            "knowledge_schema_version": self.knowledge_schema_version,
            "canonical_tool_count": len(BRAIN_TOOL_REGISTRY),
            "selected_tool_names": list(self.selected_tool_names),
            "selected_tools": [
                item.to_compact_dict()
                for item in self.selected_tools
            ],
            "reason": self.reason.value,
            "incomplete": self.incomplete,
            "authorizes_execution": self.authorizes_execution,
        }


def narrow_brain_tools(
    plan: IntelligencePlan,
    context: RelevantContext,
) -> ToolNarrowingResult:
    """Select minimum canonical candidates without authorizing execution."""

    if not isinstance(plan, IntelligencePlan) or not isinstance(
        context,
        RelevantContext,
    ):
        return _empty(
            context,
            ToolNarrowingReason.MALFORMED_INPUT,
            incomplete=True,
        )
    if (
        context.context_schema_version
        != RELEVANT_CONTEXT_SCHEMA_VERSION
    ):
        return _empty(
            context,
            ToolNarrowingReason.UNSUPPORTED_CONTEXT_SCHEMA,
            incomplete=True,
        )
    if context.knowledge_schema_version != KNOWLEDGE_SCHEMA_VERSION:
        return _empty(
            context,
            ToolNarrowingReason.UNSUPPORTED_KNOWLEDGE_SCHEMA,
            incomplete=True,
        )
    if plan.multi_intent:
        return _empty(
            context,
            ToolNarrowingReason.MULTI_INTENT_UNSUPPORTED,
            incomplete=True,
        )
    if (
        plan.requires_clarification
        or len(plan.steps) != 1
        or not isinstance(plan.steps[0], IntentStep)
    ):
        return _empty(
            context,
            ToolNarrowingReason.AMBIGUOUS_PLAN,
            incomplete=True,
        )

    step = plan.steps[0]
    if context.scope is RelevantContextScope.SYSTEM_STATUS:
        return _select_read_tool(
            context,
            step,
            expected_tool="system_status",
            reason=ToolNarrowingReason.SELECTED_SYSTEM_STATUS,
            subjects=("alex",),
        )
    if context.scope is RelevantContextScope.DEVICE_LIST:
        return _select_read_tool(
            context,
            step,
            expected_tool="list_devices",
            reason=ToolNarrowingReason.SELECTED_DEVICE_LIST,
            subjects=(),
        )
    if context.scope is RelevantContextScope.DEVICE_DETAIL:
        if context.reason is RelevantContextReason.DEVICE_NOT_FOUND:
            return _empty(
                context,
                ToolNarrowingReason.DEVICE_NOT_FOUND,
                incomplete=True,
            )
        if step.decision.route is IntelligenceRoute.SYSTEM:
            subjects = tuple(
                section.subject
                for section in context.sections
                if section.kind is RelevantContextSectionKind.DEVICE
            )
            return _select_read_tool(
                context,
                step,
                expected_tool="list_devices",
                reason=ToolNarrowingReason.SELECTED_DEVICE_DETAIL,
                subjects=subjects,
            )
        return _select_exact_capability_action(context)
    if context.scope is RelevantContextScope.GENERAL:
        return _empty(
            context,
            ToolNarrowingReason.GENERAL_NO_TOOLS,
            incomplete=False,
        )
    return _empty(
        context,
        (
            ToolNarrowingReason.AMBIGUOUS_PLAN
            if context.reason is RelevantContextReason.AMBIGUOUS_PLAN
            else ToolNarrowingReason.NO_CANONICAL_TOOL
        ),
        incomplete=True,
    )


def compact_tool_narrowing(
    result: ToolNarrowingResult,
) -> dict[str, Any]:
    return result.to_compact_dict()


def _select_read_tool(
    context: RelevantContext,
    step: IntentStep,
    *,
    expected_tool: ToolName,
    reason: ToolNarrowingReason,
    subjects: tuple[str, ...],
) -> ToolNarrowingResult:
    definition = BRAIN_TOOL_REGISTRY.get(expected_tool)
    if (
        step.decision.route is not IntelligenceRoute.SYSTEM
        or step.decision.allowed_tool_names != (expected_tool,)
        or definition is None
        or definition.access != "read_only"
    ):
        return _empty(
            context,
            ToolNarrowingReason.NO_CANONICAL_TOOL,
            incomplete=True,
        )
    return _selected(
        context,
        (
            _selection(expected_tool, subjects),
        ),
        reason,
    )


def _select_exact_capability_action(
    context: RelevantContext,
) -> ToolNarrowingResult:
    capability_sections = tuple(
        section
        for section in context.sections
        if section.kind is RelevantContextSectionKind.CAPABILITY
    )
    if len(capability_sections) != 1:
        return _empty(
            context,
            ToolNarrowingReason.NO_CANONICAL_TOOL,
            incomplete=True,
        )
    capability = capability_sections[0]
    capability_id = capability.subject.rpartition(".")[2]
    capability_facts = _facts(capability)
    if (
        capability_id in _RELAY_CAPABILITIES
        or capability_facts.get("availability") == "restricted"
        or capability_facts.get("command_allowed") is not True
    ):
        return _empty(
            context,
            ToolNarrowingReason.RESTRICTED_CAPABILITY,
            incomplete=True,
        )
    if not _is_canonical_test_led_context(capability):
        return _empty(
            context,
            ToolNarrowingReason.NO_CANONICAL_TOOL,
            incomplete=True,
        )
    return _selected(
        context,
        (
            _selection(
                "set_test_led",
                (capability.subject,),
            ),
        ),
        ToolNarrowingReason.SELECTED_EXACT_SAFE_ACTION,
    )


def _is_canonical_test_led_context(
    capability: RelevantContextSection,
) -> bool:
    definition = BRAIN_TOOL_REGISTRY.get("set_test_led")
    return bool(
        definition is not None
        and definition.access == "mutation"
        and capability.subject == "esp01.test_led"
        and dict(definition.core_mapping)
        == {
            "node_id": "esp01",
            "capability": "test_led",
            "action": "set",
        }
    )


def _facts(
    section: RelevantContextSection,
) -> dict[str, object]:
    return {
        fact.name: fact.value
        for fact in section.facts
    }


def _selection(
    name: ToolName,
    subjects: tuple[str, ...],
) -> ToolSelection:
    definition = BRAIN_TOOL_REGISTRY[name]
    return ToolSelection(
        name=name,
        access=definition.access,
        risk=definition.risk,
        relevant_subjects=subjects,
    )


def _selected(
    context: RelevantContext,
    selected_tools: tuple[ToolSelection, ...],
    reason: ToolNarrowingReason,
) -> ToolNarrowingResult:
    return ToolNarrowingResult(
        context_schema_version=context.context_schema_version,
        knowledge_schema_version=context.knowledge_schema_version,
        selected_tools=selected_tools,
        reason=reason,
        incomplete=context.incomplete,
    )


def _empty(
    context: object,
    reason: ToolNarrowingReason,
    *,
    incomplete: bool,
) -> ToolNarrowingResult:
    return ToolNarrowingResult(
        context_schema_version=(
            context.context_schema_version
            if isinstance(context, RelevantContext)
            else 0
        ),
        knowledge_schema_version=(
            context.knowledge_schema_version
            if isinstance(context, RelevantContext)
            else 0
        ),
        selected_tools=(),
        reason=reason,
        incomplete=incomplete,
    )
