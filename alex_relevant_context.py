from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from alex_intelligence import IntelligenceDecision, IntelligenceRoute
from alex_intent_planner import IntelligencePlan, IntentStep
from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    CapabilityKnowledge,
    DeviceKnowledge,
    JsonScalar,
    KnowledgeSource,
    KnowledgeStatus,
    KnowledgeValue,
    SystemKnowledgeSnapshot,
)
from alex_knowledge_normalization import is_json_scalar, safe_text
from alex_knowledge_query import (
    DeviceDetailQueryData,
    DeviceListQueryData,
    KnowledgeQueryResult,
    KnowledgeQueryScope,
    MaintenanceQueryData,
    ServiceQueryData,
    SystemStatusQueryData,
    query_knowledge,
)


RELEVANT_CONTEXT_SCHEMA_VERSION: Final = 1
_DEVICE_REFERENCE_DECISION: Final = IntelligenceDecision(
    route=IntelligenceRoute.SYSTEM,
    matched=True,
    reason="relevant_context_exact_device_reference",
    allowed_tool_names=("list_devices",),
)


class RelevantContextScope(str, Enum):
    SYSTEM_STATUS = "system_status"
    DEVICE_LIST = "device_list"
    DEVICE_DETAIL = "device_detail"
    GENERAL = "general"
    UNSUPPORTED = "unsupported"


class RelevantContextReason(str, Enum):
    SELECTED_SYSTEM_STATUS = "selected_system_status"
    SELECTED_DEVICE_LIST = "selected_device_list"
    SELECTED_DEVICE_DETAIL = "selected_device_detail"
    SELECTED_EXPLICIT_ENTITY = "selected_explicit_entity"
    DEVICE_NOT_FOUND = "device_not_found"
    NO_RELEVANT_KNOWLEDGE = "no_relevant_knowledge"
    AMBIGUOUS_PLAN = "ambiguous_plan"
    UNSUPPORTED_PLAN = "unsupported_plan"
    UNSUPPORTED_KNOWLEDGE_SCHEMA = "unsupported_knowledge_schema"


class RelevantContextSectionKind(str, Enum):
    SYSTEM = "system"
    SERVICE = "service"
    MAINTENANCE = "maintenance"
    DEVICE = "device"
    CAPABILITY = "capability"


@dataclass(frozen=True, slots=True)
class RelevantFact:
    name: str
    value: JsonScalar

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("relevant_context_fact_name_required")
        if not is_json_scalar(self.value):
            raise TypeError("relevant_context_fact_value_must_be_json_scalar")


@dataclass(frozen=True, slots=True)
class RelevantContextSection:
    kind: RelevantContextSectionKind
    subject: str
    facts: tuple[RelevantFact, ...]
    observed_at: str | None
    stale: KnowledgeValue
    sources: tuple[KnowledgeSource, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", tuple(self.facts))
        object.__setattr__(self, "sources", tuple(self.sources))
        names = tuple(fact.name for fact in self.facts)
        if len(names) != len(set(names)):
            raise ValueError("relevant_context_fact_names_must_be_unique")

    def to_compact_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind.value,
            "subject": self.subject,
            "facts": {
                fact.name: fact.value
                for fact in self.facts
            },
            "freshness": {
                "stale": _compact_value(self.stale),
            },
            "sources": _compact_sources(self.sources),
        }
        if self.observed_at is not None:
            result["freshness"]["observed_at"] = self.observed_at
        return result


@dataclass(frozen=True, slots=True)
class RelevantContext:
    context_schema_version: int = field(
        init=False,
        default=RELEVANT_CONTEXT_SCHEMA_VERSION,
    )
    knowledge_schema_version: int
    snapshot_captured_at: str
    scope: RelevantContextScope
    reason: RelevantContextReason
    incomplete: bool
    sources: tuple[KnowledgeSource, ...]
    sections: tuple[RelevantContextSection, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "sections", tuple(self.sections))

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "context_schema_version": self.context_schema_version,
            "knowledge_schema_version": self.knowledge_schema_version,
            "snapshot_captured_at": self.snapshot_captured_at,
            "scope": self.scope.value,
            "reason": self.reason.value,
            "incomplete": self.incomplete,
            "sources": _compact_sources(self.sources),
            "sections": [
                section.to_compact_dict()
                for section in self.sections
            ],
        }


def build_relevant_context(
    plan: IntelligencePlan,
    snapshot: SystemKnowledgeSnapshot,
) -> RelevantContext:
    """Select bounded factual context without I/O, authorization, or execution."""

    if not isinstance(snapshot, SystemKnowledgeSnapshot):
        return _empty_context(
            knowledge_schema_version=0,
            snapshot_captured_at="",
            scope=RelevantContextScope.UNSUPPORTED,
            reason=RelevantContextReason.UNSUPPORTED_PLAN,
            incomplete=True,
        )
    if snapshot.schema_version != KNOWLEDGE_SCHEMA_VERSION:
        return _empty_context(
            knowledge_schema_version=snapshot.schema_version,
            snapshot_captured_at=snapshot.captured_at,
            scope=RelevantContextScope.UNSUPPORTED,
            reason=(
                RelevantContextReason.UNSUPPORTED_KNOWLEDGE_SCHEMA
            ),
            incomplete=True,
        )
    if not isinstance(plan, IntelligencePlan):
        return _unsupported_plan(snapshot)
    if (
        plan.multi_intent
        or plan.requires_clarification
        or len(plan.steps) != 1
        or not isinstance(plan.steps[0], IntentStep)
    ):
        return _empty_context(
            knowledge_schema_version=snapshot.schema_version,
            snapshot_captured_at=snapshot.captured_at,
            scope=RelevantContextScope.UNSUPPORTED,
            reason=(
                RelevantContextReason.AMBIGUOUS_PLAN
                if plan.requires_clarification or plan.multi_intent
                else RelevantContextReason.UNSUPPORTED_PLAN
            ),
            incomplete=True,
        )

    step = plan.steps[0]
    if step.decision.route is IntelligenceRoute.SYSTEM:
        selected = query_knowledge(
            snapshot,
            step.decision,
            step.original_text,
        )
        return _context_from_system_query(selected, snapshot)
    return _context_for_non_system_step(step, snapshot)


def compact_relevant_context(
    context: RelevantContext,
) -> dict[str, Any]:
    return context.to_compact_dict()


def _context_from_system_query(
    selected: KnowledgeQueryResult,
    snapshot: SystemKnowledgeSnapshot,
) -> RelevantContext:
    if (
        selected.scope is KnowledgeQueryScope.SYSTEM_STATUS
        and isinstance(selected.data, SystemStatusQueryData)
    ):
        sections = (
            _system_section(selected.data),
            *(
                _service_section(service)
                for service in selected.data.services
            ),
            *(
                _maintenance_section(entry)
                for entry in selected.data.maintenance
            ),
        )
        return _selected_context(
            selected,
            RelevantContextScope.SYSTEM_STATUS,
            RelevantContextReason.SELECTED_SYSTEM_STATUS,
            sections,
        )
    if (
        selected.scope is KnowledgeQueryScope.DEVICE_LIST
        and isinstance(selected.data, DeviceListQueryData)
    ):
        devices = {
            device.device_id: device
            for device in snapshot.devices
        }
        sections = tuple(
            _device_section(devices[item.device_id])
            for item in selected.data.devices
            if item.device_id in devices
        )
        return _selected_context(
            selected,
            RelevantContextScope.DEVICE_LIST,
            RelevantContextReason.SELECTED_DEVICE_LIST,
            sections,
        )
    if (
        selected.scope is KnowledgeQueryScope.DEVICE_DETAIL
        and isinstance(selected.data, DeviceDetailQueryData)
    ):
        return _device_detail_context(
            selected,
            snapshot,
            capability_ids=(),
            reason=RelevantContextReason.SELECTED_DEVICE_DETAIL,
        )
    return _unsupported_plan(snapshot)


def _context_for_non_system_step(
    step: IntentStep,
    snapshot: SystemKnowledgeSnapshot,
) -> RelevantContext:
    selected = query_knowledge(
        snapshot,
        _DEVICE_REFERENCE_DECISION,
        step.original_text,
    )
    if selected.scope is KnowledgeQueryScope.UNSUPPORTED:
        return _empty_context(
            knowledge_schema_version=snapshot.schema_version,
            snapshot_captured_at=snapshot.captured_at,
            scope=RelevantContextScope.UNSUPPORTED,
            reason=RelevantContextReason.AMBIGUOUS_PLAN,
            incomplete=True,
        )
    if (
        selected.scope is not KnowledgeQueryScope.DEVICE_DETAIL
        or not isinstance(selected.data, DeviceDetailQueryData)
    ):
        return _empty_context(
            knowledge_schema_version=snapshot.schema_version,
            snapshot_captured_at=snapshot.captured_at,
            scope=RelevantContextScope.GENERAL,
            reason=RelevantContextReason.NO_RELEVANT_KNOWLEDGE,
            incomplete=False,
        )
    capability_ids = _referenced_capability_ids(
        step.normalized_text,
        selected.data,
        snapshot,
    )
    return _device_detail_context(
        selected,
        snapshot,
        capability_ids=capability_ids,
        reason=RelevantContextReason.SELECTED_EXPLICIT_ENTITY,
    )


def _device_detail_context(
    selected: KnowledgeQueryResult,
    snapshot: SystemKnowledgeSnapshot,
    *,
    capability_ids: tuple[str, ...],
    reason: RelevantContextReason,
) -> RelevantContext:
    assert isinstance(selected.data, DeviceDetailQueryData)
    data = selected.data
    device = next(
        (
            item
            for item in snapshot.devices
            if item.device_id == data.requested_device_id
        ),
        None,
    )
    if not data.found or device is None:
        section = RelevantContextSection(
            kind=RelevantContextSectionKind.DEVICE,
            subject=data.requested_device_id,
            facts=(
                RelevantFact("found", False),
                RelevantFact("known", KnowledgeValue.UNKNOWN.value),
            ),
            observed_at=None,
            stale=KnowledgeValue.UNKNOWN,
            sources=(KnowledgeSource.UNKNOWN,),
        )
        return RelevantContext(
            knowledge_schema_version=selected.knowledge_schema_version,
            snapshot_captured_at=selected.snapshot_captured_at,
            scope=RelevantContextScope.DEVICE_DETAIL,
            reason=RelevantContextReason.DEVICE_NOT_FOUND,
            incomplete=True,
            sources=(KnowledgeSource.UNKNOWN,),
            sections=(section,),
        )

    capabilities = {
        capability.capability_id: capability
        for capability in device.capabilities
    }
    sections = (
        _device_section(device),
        *(
            _capability_section(capabilities[capability_id], device)
            for capability_id in capability_ids
            if capability_id in capabilities
        ),
    )
    return RelevantContext(
        knowledge_schema_version=selected.knowledge_schema_version,
        snapshot_captured_at=selected.snapshot_captured_at,
        scope=RelevantContextScope.DEVICE_DETAIL,
        reason=reason,
        incomplete=selected.incomplete,
        sources=_merge_sources(
            *(section.sources for section in sections),
        ),
        sections=sections,
    )


def _system_section(
    data: SystemStatusQueryData,
) -> RelevantContextSection:
    return RelevantContextSection(
        kind=RelevantContextSectionKind.SYSTEM,
        subject="alex",
        facts=(
            RelevantFact("version", data.version),
            RelevantFact("status", data.overall_status.value),
        ),
        observed_at=None,
        stale=KnowledgeValue.UNKNOWN,
        sources=data.overall_sources,
    )


def _service_section(
    data: ServiceQueryData,
) -> RelevantContextSection:
    return RelevantContextSection(
        kind=RelevantContextSectionKind.SERVICE,
        subject=data.name,
        facts=(
            RelevantFact("status", data.status.value),
            RelevantFact("available", _compact_value(data.available)),
        ),
        observed_at=data.observed_at,
        stale=data.stale,
        sources=data.sources,
    )


def _maintenance_section(
    data: MaintenanceQueryData,
) -> RelevantContextSection:
    return RelevantContextSection(
        kind=RelevantContextSectionKind.MAINTENANCE,
        subject=data.name,
        facts=(
            RelevantFact("status", data.status.value),
            RelevantFact("available", _compact_value(data.available)),
        ),
        observed_at=data.observed_at,
        stale=data.stale,
        sources=data.sources,
    )


def _device_section(
    device: DeviceKnowledge,
) -> RelevantContextSection:
    return RelevantContextSection(
        kind=RelevantContextSectionKind.DEVICE,
        subject=device.device_id,
        facts=(
            RelevantFact("known", _compact_value(device.known)),
            RelevantFact("available", _compact_value(device.available)),
            RelevantFact("online", _compact_value(device.online)),
            RelevantFact("status", device.status.value),
            RelevantFact(
                "hardware_verified",
                _compact_value(device.hardware_verified),
            ),
            RelevantFact(
                "verification_status",
                device.verification_status,
            ),
        ),
        observed_at=device.observed_at,
        stale=KnowledgeValue.UNKNOWN,
        sources=device.sources,
    )


def _capability_section(
    capability: CapabilityKnowledge,
    device: DeviceKnowledge,
) -> RelevantContextSection:
    facts = [
        RelevantFact(
            "availability",
            _compact_value(capability.availability),
        ),
        RelevantFact(
            "verification_status",
            capability.verification_status,
        ),
        RelevantFact(
            "hardware_verified",
            _compact_value(capability.hardware_verified),
        ),
        RelevantFact(
            "command_allowed",
            _compact_value(capability.command_allowed),
        ),
    ]
    state = _safe_scalar(capability.state)
    if state is not None:
        facts.append(RelevantFact("state", state))
    if capability.restriction_reason is not None:
        facts.append(
            RelevantFact(
                "restriction_reason",
                capability.restriction_reason,
            )
        )
    return RelevantContextSection(
        kind=RelevantContextSectionKind.CAPABILITY,
        subject=f"{device.device_id}.{capability.capability_id}",
        facts=tuple(facts),
        observed_at=capability.observed_at,
        stale=KnowledgeValue.UNKNOWN,
        sources=capability.sources,
    )


def _referenced_capability_ids(
    normalized_text: str,
    detail: DeviceDetailQueryData,
    snapshot: SystemKnowledgeSnapshot,
) -> tuple[str, ...]:
    if not detail.found:
        return ()
    device = next(
        (
            item
            for item in snapshot.devices
            if item.device_id == detail.requested_device_id
        ),
        None,
    )
    if device is None:
        return ()
    text = (
        normalized_text.casefold()
        if isinstance(normalized_text, str)
        else ""
    )
    return tuple(
        capability.capability_id
        for capability in device.capabilities
        if _contains_exact_identifier(
            text,
            capability.capability_id.casefold(),
        )
    )


def _contains_exact_identifier(text: str, identifier: str) -> bool:
    pattern = re.compile(
        rf"(?<![a-z0-9_-]){re.escape(identifier)}(?![a-z0-9_-])",
        re.IGNORECASE,
    )
    return pattern.search(text) is not None


def _selected_context(
    selected: KnowledgeQueryResult,
    scope: RelevantContextScope,
    reason: RelevantContextReason,
    sections: tuple[RelevantContextSection, ...],
) -> RelevantContext:
    return RelevantContext(
        knowledge_schema_version=selected.knowledge_schema_version,
        snapshot_captured_at=selected.snapshot_captured_at,
        scope=scope,
        reason=reason,
        incomplete=selected.incomplete,
        sources=_merge_sources(
            *(section.sources for section in sections),
        ),
        sections=sections,
    )


def _unsupported_plan(
    snapshot: SystemKnowledgeSnapshot,
) -> RelevantContext:
    return _empty_context(
        knowledge_schema_version=snapshot.schema_version,
        snapshot_captured_at=snapshot.captured_at,
        scope=RelevantContextScope.UNSUPPORTED,
        reason=RelevantContextReason.UNSUPPORTED_PLAN,
        incomplete=True,
    )


def _empty_context(
    *,
    knowledge_schema_version: int,
    snapshot_captured_at: str,
    scope: RelevantContextScope,
    reason: RelevantContextReason,
    incomplete: bool,
) -> RelevantContext:
    return RelevantContext(
        knowledge_schema_version=knowledge_schema_version,
        snapshot_captured_at=snapshot_captured_at,
        scope=scope,
        reason=reason,
        incomplete=incomplete,
        sources=(),
        sections=(),
    )


def _compact_value(value: KnowledgeValue) -> bool | str:
    if value is KnowledgeValue.KNOWN_TRUE:
        return True
    if value is KnowledgeValue.KNOWN_FALSE:
        return False
    return value.value


def _compact_sources(
    sources: tuple[KnowledgeSource, ...],
) -> list[str]:
    return [source.value for source in sources]


def _merge_sources(
    *source_groups: tuple[KnowledgeSource, ...],
) -> tuple[KnowledgeSource, ...]:
    sources = {
        source
        for group in source_groups
        for source in group
    }
    if len(sources) > 1:
        sources.discard(KnowledgeSource.UNKNOWN)
    return tuple(sorted(sources, key=lambda item: item.value))


def _safe_scalar(value: JsonScalar) -> JsonScalar:
    if isinstance(value, str):
        return safe_text(value)
    return value
