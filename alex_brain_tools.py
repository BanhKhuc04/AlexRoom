from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, Mapping, Protocol, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    JsonScalar,
    KnowledgeSource,
    KnowledgeValue,
)
from alex_relevant_context import (
    RELEVANT_CONTEXT_SCHEMA_VERSION,
    RelevantContextReason,
    RelevantContextScope,
    RelevantContextSectionKind,
)


MAX_TOOL_CALLS: Final = 4
MAX_REQUEST_ID_LENGTH: Final = 64
MAX_TEXT_LENGTH: Final = 4096
MAX_RECORD_ID_LENGTH: Final = 80
MAX_BRAIN_CONTEXT_BYTES: Final = 64 * 1024
MAX_BRAIN_CONTEXT_SECTIONS: Final = 128
MAX_BRAIN_CONTEXT_FACTS: Final = 16
MAX_BRAIN_CONTEXT_SUBJECT_LENGTH: Final = 80
MAX_BRAIN_CONTEXT_VALUE_LENGTH: Final = 256
BOUNDED_ID_PATTERN: Final = (
    r"^[^\x00-\x20\x7F](?:[^\x00-\x1F\x7F]*[^\x00-\x20\x7F])?$"
)

ToolName = Literal[
    "system_status",
    "list_devices",
    "set_test_led",
    "set_room_mode",
    "run_safe_mission",
    "run_safe_automation",
]
ToolAccess = Literal["read_only", "mutation"]
ToolRisk = Literal[
    "safe_read",
    "safe_low_voltage_mutation",
    "safe_logical_mutation",
    "stored_workflow_gated",
]

TOOL_NAMES: Final[tuple[ToolName, ...]] = (
    "system_status",
    "list_devices",
    "set_test_led",
    "set_room_mode",
    "run_safe_mission",
    "run_safe_automation",
)


class StrictContractModel(BaseModel):
    """Shared fail-closed configuration for Brain/Core wire contracts."""

    model_config = ConfigDict(extra="forbid", strict=True)


class NoArguments(StrictContractModel):
    pass


class SetTestLedArguments(StrictContractModel):
    value: bool


class SetRoomModeArguments(StrictContractModel):
    mode: Literal["home", "away", "sleep", "study"]


class RunSafeMissionArguments(StrictContractModel):
    mission_id: str = Field(
        min_length=1,
        max_length=MAX_RECORD_ID_LENGTH,
        pattern=BOUNDED_ID_PATTERN,
    )


class RunSafeAutomationArguments(StrictContractModel):
    automation_id: str = Field(
        min_length=1,
        max_length=MAX_RECORD_ID_LENGTH,
        pattern=BOUNDED_ID_PATTERN,
    )


@dataclass(frozen=True)
class BrainToolDefinition:
    argument_model: type[StrictContractModel]
    access: ToolAccess
    description: str
    risk: ToolRisk
    core_mapping: Mapping[str, str]


def _immutable_mapping(**values: str) -> Mapping[str, str]:
    return MappingProxyType(values)


# This registry is owned by ALEX Core. A Brain response may select only a key and
# provide arguments; it cannot replace schemas, risk metadata, or Core routing.
BRAIN_TOOL_REGISTRY: Final[Mapping[ToolName, BrainToolDefinition]] = MappingProxyType(
    {
        "system_status": BrainToolDefinition(
            argument_model=NoArguments,
            access="read_only",
            description="Read the current ALEX Core system status.",
            risk="safe_read",
            core_mapping=_immutable_mapping(operation="read_system_status"),
        ),
        "list_devices": BrainToolDefinition(
            argument_model=NoArguments,
            access="read_only",
            description="List devices from the Core-authoritative registry.",
            risk="safe_read",
            core_mapping=_immutable_mapping(operation="list_devices"),
        ),
        "set_test_led": BrainToolDefinition(
            argument_model=SetTestLedArguments,
            access="mutation",
            description="Propose setting the verified low-voltage ESP01 test LED.",
            risk="safe_low_voltage_mutation",
            core_mapping=_immutable_mapping(
                node_id="esp01",
                capability="test_led",
                action="set",
            ),
        ),
        "set_room_mode": BrainToolDefinition(
            argument_model=SetRoomModeArguments,
            access="mutation",
            description="Propose a logical room-mode update without relay actions.",
            risk="safe_logical_mutation",
            core_mapping=_immutable_mapping(operation="set_room_mode"),
        ),
        "run_safe_mission": BrainToolDefinition(
            argument_model=RunSafeMissionArguments,
            access="mutation",
            description="Propose a stored mission explicitly allowed for Brain use.",
            risk="stored_workflow_gated",
            core_mapping=_immutable_mapping(
                operation="run_stored_mission",
                domain="missions",
                requires="brain_allowed",
            ),
        ),
        "run_safe_automation": BrainToolDefinition(
            argument_model=RunSafeAutomationArguments,
            access="mutation",
            description="Propose a stored automation explicitly allowed for Brain use.",
            risk="stored_workflow_gated",
            core_mapping=_immutable_mapping(
                operation="run_stored_automation",
                domain="automations",
                requires="brain_allowed",
            ),
        ),
    }
)

if tuple(BRAIN_TOOL_REGISTRY) != TOOL_NAMES:
    raise RuntimeError("Brain tool registry must contain the exact ordered allowlist")


def brain_tool_schemas_for_provider(
    allowed_names: Sequence[ToolName] | None = None,
) -> tuple[dict[str, object], ...]:
    """Build fresh schemas for the exact Core-selected canonical subset."""

    schemas: list[dict[str, object]] = []
    if allowed_names is None:
        selected_names = TOOL_NAMES
    else:
        requested = frozenset(allowed_names)
        if (
            len(requested) != len(allowed_names)
            or not requested.issubset(BRAIN_TOOL_REGISTRY)
        ):
            raise ValueError("invalid_allowed_tool_subset")
        selected_names = tuple(
            name
            for name in TOOL_NAMES
            if name in requested
        )
    for name in selected_names:
        definition = BRAIN_TOOL_REGISTRY[name]
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": definition.description,
                    "parameters": deepcopy(
                        definition.argument_model.model_json_schema()
                    ),
                },
            }
        )
    return tuple(schemas)


class BrainContextFreshness(StrictContractModel):
    stale: bool | str
    observed_at: str | None = Field(
        default=None,
        max_length=MAX_BRAIN_CONTEXT_VALUE_LENGTH,
        exclude_if=lambda value: value is None,
    )

    @field_validator("stale")
    @classmethod
    def validate_stale(cls, value: bool | str) -> bool | str:
        if isinstance(value, str) and value not in {
            item.value for item in KnowledgeValue
        }:
            raise ValueError("invalid_context_knowledge_value")
        return value


class BrainContextSection(StrictContractModel):
    kind: str = Field(min_length=1, max_length=32)
    subject: str = Field(
        min_length=1,
        max_length=MAX_BRAIN_CONTEXT_SUBJECT_LENGTH,
        pattern=BOUNDED_ID_PATTERN,
    )
    facts: dict[str, JsonScalar] = Field(
        default_factory=dict,
        max_length=MAX_BRAIN_CONTEXT_FACTS,
    )
    freshness: BrainContextFreshness
    sources: list[str] = Field(
        default_factory=list,
        max_length=len(KnowledgeSource),
    )

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in {
            item.value for item in RelevantContextSectionKind
        }:
            raise ValueError("invalid_context_section_kind")
        return value

    @field_validator("facts")
    @classmethod
    def validate_facts(
        cls,
        value: dict[str, JsonScalar],
    ) -> dict[str, JsonScalar]:
        for name, fact in value.items():
            if (
                not isinstance(name, str)
                or not name
                or len(name) > 64
                or any(ord(character) < 32 for character in name)
            ):
                raise ValueError("invalid_context_fact_name")
            if (
                isinstance(fact, str)
                and len(fact) > MAX_BRAIN_CONTEXT_VALUE_LENGTH
            ):
                raise ValueError("context_fact_value_too_long")
        return value

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        canonical = {item.value for item in KnowledgeSource}
        if len(value) != len(set(value)) or any(
            item not in canonical for item in value
        ):
            raise ValueError("invalid_context_sources")
        return sorted(value)


class BrainRelevantContext(StrictContractModel):
    context_schema_version: int
    knowledge_schema_version: int
    snapshot_captured_at: str = Field(
        min_length=1,
        max_length=MAX_BRAIN_CONTEXT_VALUE_LENGTH,
    )
    scope: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=64)
    incomplete: bool
    sources: list[str] = Field(
        default_factory=list,
        max_length=len(KnowledgeSource),
    )
    sections: list[BrainContextSection] = Field(
        default_factory=list,
        max_length=MAX_BRAIN_CONTEXT_SECTIONS,
    )

    @model_validator(mode="after")
    def validate_canonical_context(self) -> "BrainRelevantContext":
        if self.context_schema_version != RELEVANT_CONTEXT_SCHEMA_VERSION:
            raise ValueError("unsupported_context_schema")
        if self.knowledge_schema_version != KNOWLEDGE_SCHEMA_VERSION:
            raise ValueError("unsupported_knowledge_schema")
        if self.scope not in {
            item.value for item in RelevantContextScope
        }:
            raise ValueError("invalid_context_scope")
        if self.reason not in {
            item.value for item in RelevantContextReason
        }:
            raise ValueError("invalid_context_reason")
        canonical_sources = {item.value for item in KnowledgeSource}
        if len(self.sources) != len(set(self.sources)) or any(
            item not in canonical_sources for item in self.sources
        ):
            raise ValueError("invalid_context_sources")
        self.sources = sorted(self.sources)
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > MAX_BRAIN_CONTEXT_BYTES:
            raise ValueError("brain_context_too_large")
        return self


class BrainChatRequest(StrictContractModel):
    request_id: str = Field(
        min_length=1,
        max_length=MAX_REQUEST_ID_LENGTH,
        pattern=BOUNDED_ID_PATTERN,
    )
    user_text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    context: BrainRelevantContext | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    allowed_tools: list[ToolName] | None = Field(
        default=None,
        max_length=len(TOOL_NAMES),
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_enhanced_fields(self) -> "BrainChatRequest":
        if self.context is not None and self.allowed_tools is None:
            raise ValueError("context_requires_allowed_tools")
        if self.allowed_tools is not None:
            if len(self.allowed_tools) != len(set(self.allowed_tools)):
                raise ValueError("duplicate_allowed_tools")
            requested = frozenset(self.allowed_tools)
            self.allowed_tools = [
                name
                for name in TOOL_NAMES
                if name in requested
            ]
        return self


class BrainToolCall(StrictContractModel):
    name: ToolName
    arguments: dict[str, object]

    @model_validator(mode="after")
    def validate_registered_arguments(self) -> "BrainToolCall":
        definition = BRAIN_TOOL_REGISTRY[self.name]
        validated = definition.argument_model.model_validate(self.arguments)
        self.arguments = validated.model_dump(mode="python")
        return self


class BrainChatResponse(StrictContractModel):
    request_id: str = Field(
        min_length=1,
        max_length=MAX_REQUEST_ID_LENGTH,
        pattern=BOUNDED_ID_PATTERN,
    )
    assistant_text: str = Field(default="", max_length=MAX_TEXT_LENGTH)
    tool_calls: list[BrainToolCall] = Field(default_factory=list, max_length=MAX_TOOL_CALLS)

    @model_validator(mode="after")
    def reject_exact_duplicate_calls(self) -> "BrainChatResponse":
        signatures = [call.model_dump_json() for call in self.tool_calls]
        if len(signatures) != len(set(signatures)):
            raise ValueError("exact duplicate tool calls are not allowed")
        return self


class BrainRecordStore(Protocol):
    def get_record(self, domain: str, record_id: str) -> dict[str, object] | None: ...


class BrainToolBoundaryError(ValueError):
    """A Core-side proposal rejection with a stable machine-readable reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ValidatedBrainToolProposal:
    """Validated proposal metadata only; this object has no execution method."""

    name: ToolName
    arguments: Mapping[str, object]
    access: ToolAccess
    risk: ToolRisk
    core_mapping: Mapping[str, str]


class BrainToolBoundary:
    """Core-owned validation boundary. It validates proposals but never executes them."""

    def __init__(self, store: BrainRecordStore) -> None:
        self.store = store

    def validate_proposal(self, call: BrainToolCall) -> ValidatedBrainToolProposal:
        definition = BRAIN_TOOL_REGISTRY[call.name]
        arguments = definition.argument_model.model_validate(call.arguments).model_dump(mode="python")

        if call.name == "run_safe_mission":
            self._require_brain_allowed("missions", str(arguments["mission_id"]))
        elif call.name == "run_safe_automation":
            self._require_brain_allowed("automations", str(arguments["automation_id"]))

        return ValidatedBrainToolProposal(
            name=call.name,
            arguments=MappingProxyType(arguments),
            access=definition.access,
            risk=definition.risk,
            core_mapping=definition.core_mapping,
        )

    def validate_response(
        self,
        response: BrainChatResponse,
    ) -> tuple[ValidatedBrainToolProposal, ...]:
        return tuple(self.validate_proposal(call) for call in response.tool_calls)

    def _require_brain_allowed(self, domain: str, record_id: str) -> None:
        record = self.store.get_record(domain, record_id)
        if record is None:
            raise BrainToolBoundaryError(f"{domain[:-1]}_not_found")
        if record.get("brain_allowed") is not True:
            raise BrainToolBoundaryError(f"{domain[:-1]}_not_brain_allowed")
