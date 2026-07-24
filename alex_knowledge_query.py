from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeAlias

from alex_intelligence import IntelligenceDecision, IntelligenceRoute
from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    DeviceKnowledge,
    KnowledgeSource,
    KnowledgeStatus,
    KnowledgeValue,
    MaintenanceKnowledge,
    ServiceKnowledge,
    SystemKnowledgeSnapshot,
)


_DEVICE_LIKE_ID = re.compile(
    r"(?<![a-z0-9_-])([a-z][a-z0-9-]*\d+)(?![a-z0-9_-])",
    re.IGNORECASE,
)


class KnowledgeQueryScope(str, Enum):
    SYSTEM_STATUS = "system_status"
    DEVICE_LIST = "device_list"
    DEVICE_DETAIL = "device_detail"
    UNSUPPORTED = "unsupported"


class KnowledgeQueryReason(str, Enum):
    SELECTED_SYSTEM_STATUS = "selected_system_status"
    SELECTED_DEVICE_LIST = "selected_device_list"
    SELECTED_DEVICE_DETAIL = "selected_device_detail"
    DEVICE_NOT_FOUND = "device_not_found"
    NO_DEVICES = "no_devices"
    PARTIAL_KNOWLEDGE = "partial_knowledge"
    AMBIGUOUS_DEVICE_IDS = "ambiguous_device_ids"
    UNSUPPORTED_ROUTE = "unsupported_route"
    UNSUPPORTED_SYSTEM_SCOPE = "unsupported_system_scope"
    UNSUPPORTED_KNOWLEDGE_SCHEMA = "unsupported_knowledge_schema"


@dataclass(frozen=True, slots=True)
class ServiceQueryData:
    name: str
    status: KnowledgeStatus
    available: KnowledgeValue
    observed_at: str | None
    stale: KnowledgeValue
    sources: tuple[KnowledgeSource, ...]

    def to_compact_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "available": _compact_value(self.available),
            "stale": _compact_value(self.stale),
            "sources": _compact_sources(self.sources),
        }
        if self.observed_at is not None:
            result["observed_at"] = self.observed_at
        return result


@dataclass(frozen=True, slots=True)
class MaintenanceQueryData:
    name: str
    status: KnowledgeStatus
    available: KnowledgeValue
    observed_at: str | None
    stale: KnowledgeValue
    sources: tuple[KnowledgeSource, ...]

    def to_compact_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "available": _compact_value(self.available),
            "stale": _compact_value(self.stale),
            "sources": _compact_sources(self.sources),
        }
        if self.observed_at is not None:
            result["observed_at"] = self.observed_at
        return result


@dataclass(frozen=True, slots=True)
class DeviceQueryData:
    device_id: str
    known: KnowledgeValue
    available: KnowledgeValue
    online: KnowledgeValue
    observed_at: str | None
    stale: KnowledgeValue
    hardware_verified: KnowledgeValue
    sources: tuple[KnowledgeSource, ...]

    def to_compact_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "device_id": self.device_id,
            "known": _compact_value(self.known),
            "available": _compact_value(self.available),
            "online": _compact_value(self.online),
            "stale": _compact_value(self.stale),
            "hardware_verified": _compact_value(self.hardware_verified),
            "sources": _compact_sources(self.sources),
        }
        if self.observed_at is not None:
            result["observed_at"] = self.observed_at
        return result


@dataclass(frozen=True, slots=True)
class SystemStatusQueryData:
    version: str
    overall_status: KnowledgeStatus
    overall_sources: tuple[KnowledgeSource, ...]
    services: tuple[ServiceQueryData, ...]
    maintenance: tuple[MaintenanceQueryData, ...]

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "overall": {
                "status": self.overall_status.value,
                "sources": _compact_sources(self.overall_sources),
            },
            "services": {
                item.name: item.to_compact_dict()
                for item in self.services
            },
            "maintenance": {
                item.name: item.to_compact_dict()
                for item in self.maintenance
            },
        }


@dataclass(frozen=True, slots=True)
class DeviceListQueryData:
    devices: tuple[DeviceQueryData, ...]

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "devices": [
                device.to_compact_dict()
                for device in self.devices
            ]
        }


@dataclass(frozen=True, slots=True)
class DeviceDetailQueryData:
    requested_device_id: str
    found: bool
    device: DeviceQueryData | None
    restricted_capabilities: tuple[str, ...] = ()

    def to_compact_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "requested_device_id": self.requested_device_id,
            "found": self.found,
        }
        if self.device is not None:
            result["device"] = self.device.to_compact_dict()
        if self.restricted_capabilities:
            result["restricted_capabilities"] = {
                capability_id: KnowledgeValue.RESTRICTED.value
                for capability_id in self.restricted_capabilities
            }
        return result


KnowledgeQueryData: TypeAlias = (
    SystemStatusQueryData
    | DeviceListQueryData
    | DeviceDetailQueryData
    | None
)


@dataclass(frozen=True, slots=True)
class KnowledgeQueryResult:
    knowledge_schema_version: int
    snapshot_captured_at: str
    scope: KnowledgeQueryScope
    data: KnowledgeQueryData
    sources: tuple[KnowledgeSource, ...]
    incomplete: bool
    reason: KnowledgeQueryReason

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "knowledge_schema_version": self.knowledge_schema_version,
            "snapshot_captured_at": self.snapshot_captured_at,
            "scope": self.scope.value,
            "data": (
                self.data.to_compact_dict()
                if self.data is not None
                else None
            ),
            "sources": _compact_sources(self.sources),
            "incomplete": self.incomplete,
            "reason": self.reason.value,
        }


def query_knowledge(
    snapshot: SystemKnowledgeSnapshot,
    decision: IntelligenceDecision,
    user_text: str,
) -> KnowledgeQueryResult:
    """Select relevant Snapshot v1 data without executing any operation."""

    if snapshot.schema_version != KNOWLEDGE_SCHEMA_VERSION:
        return _unsupported_result(
            snapshot,
            KnowledgeQueryReason.UNSUPPORTED_KNOWLEDGE_SCHEMA,
        )
    if decision.route is not IntelligenceRoute.SYSTEM:
        return _unsupported_result(
            snapshot,
            KnowledgeQueryReason.UNSUPPORTED_ROUTE,
        )
    if decision.allowed_tool_names == ("system_status",):
        return _select_system_status(snapshot)
    if decision.allowed_tool_names == ("list_devices",):
        return _select_device_knowledge(snapshot, user_text)
    return _unsupported_result(
        snapshot,
        KnowledgeQueryReason.UNSUPPORTED_SYSTEM_SCOPE,
    )


def compact_knowledge_query(result: KnowledgeQueryResult) -> dict[str, Any]:
    return result.to_compact_dict()


def _select_system_status(
    snapshot: SystemKnowledgeSnapshot,
) -> KnowledgeQueryResult:
    services = tuple(
        _service_data(item)
        for item in snapshot.services
        if item.name in {"brain", "core"}
    )
    maintenance = tuple(
        _maintenance_data(item)
        for item in snapshot.maintenance
        if item.name in {"backup", "health"}
    )
    data = SystemStatusQueryData(
        version=snapshot.version,
        overall_status=snapshot.overall_status,
        overall_sources=snapshot.overall_sources,
        services=services,
        maintenance=maintenance,
    )
    incomplete = (
        {item.name for item in services} != {"brain", "core"}
        or {item.name for item in maintenance} != {"backup", "health"}
        or snapshot.overall_status is KnowledgeStatus.UNKNOWN
        or any(item.status is KnowledgeStatus.UNKNOWN for item in services)
        or any(item.status is KnowledgeStatus.UNKNOWN for item in maintenance)
    )
    return KnowledgeQueryResult(
        knowledge_schema_version=snapshot.schema_version,
        snapshot_captured_at=snapshot.captured_at,
        scope=KnowledgeQueryScope.SYSTEM_STATUS,
        data=data,
        sources=_merge_sources(
            snapshot.overall_sources,
            *(item.sources for item in services),
            *(item.sources for item in maintenance),
        ),
        incomplete=incomplete,
        reason=(
            KnowledgeQueryReason.PARTIAL_KNOWLEDGE
            if incomplete
            else KnowledgeQueryReason.SELECTED_SYSTEM_STATUS
        ),
    )


def _select_device_knowledge(
    snapshot: SystemKnowledgeSnapshot,
    user_text: str,
) -> KnowledgeQueryResult:
    requested_id, matched_device, ambiguous = _extract_device(
        snapshot,
        user_text,
    )
    if ambiguous:
        return KnowledgeQueryResult(
            knowledge_schema_version=snapshot.schema_version,
            snapshot_captured_at=snapshot.captured_at,
            scope=KnowledgeQueryScope.UNSUPPORTED,
            data=None,
            sources=(KnowledgeSource.UNKNOWN,),
            incomplete=True,
            reason=KnowledgeQueryReason.AMBIGUOUS_DEVICE_IDS,
        )
    if requested_id is not None:
        return _select_device_detail(
            snapshot,
            requested_id,
            matched_device,
        )

    devices = tuple(_device_data(item) for item in snapshot.devices)
    return KnowledgeQueryResult(
        knowledge_schema_version=snapshot.schema_version,
        snapshot_captured_at=snapshot.captured_at,
        scope=KnowledgeQueryScope.DEVICE_LIST,
        data=DeviceListQueryData(devices=devices),
        sources=_merge_sources(*(item.sources for item in devices)),
        incomplete=not devices,
        reason=(
            KnowledgeQueryReason.NO_DEVICES
            if not devices
            else KnowledgeQueryReason.SELECTED_DEVICE_LIST
        ),
    )


def _select_device_detail(
    snapshot: SystemKnowledgeSnapshot,
    requested_id: str,
    device: DeviceKnowledge | None,
) -> KnowledgeQueryResult:
    if device is None:
        return KnowledgeQueryResult(
            knowledge_schema_version=snapshot.schema_version,
            snapshot_captured_at=snapshot.captured_at,
            scope=KnowledgeQueryScope.DEVICE_DETAIL,
            data=DeviceDetailQueryData(
                requested_device_id=requested_id,
                found=False,
                device=None,
            ),
            sources=(KnowledgeSource.UNKNOWN,),
            incomplete=True,
            reason=KnowledgeQueryReason.DEVICE_NOT_FOUND,
        )

    selected = _device_data(device)
    restricted = tuple(
        capability.capability_id
        for capability in device.capabilities
        if capability.availability is KnowledgeValue.RESTRICTED
    )
    incomplete = (
        device.known is not KnowledgeValue.KNOWN_TRUE
        or device.online is KnowledgeValue.UNKNOWN
    )
    return KnowledgeQueryResult(
        knowledge_schema_version=snapshot.schema_version,
        snapshot_captured_at=snapshot.captured_at,
        scope=KnowledgeQueryScope.DEVICE_DETAIL,
        data=DeviceDetailQueryData(
            requested_device_id=device.device_id,
            found=True,
            device=selected,
            restricted_capabilities=restricted,
        ),
        sources=selected.sources,
        incomplete=incomplete,
        reason=(
            KnowledgeQueryReason.PARTIAL_KNOWLEDGE
            if incomplete
            else KnowledgeQueryReason.SELECTED_DEVICE_DETAIL
        ),
    )


def _extract_device(
    snapshot: SystemKnowledgeSnapshot,
    user_text: str,
) -> tuple[str | None, DeviceKnowledge | None, bool]:
    text = user_text.casefold() if isinstance(user_text, str) else ""
    canonical = {
        device.device_id.casefold(): device
        for device in snapshot.devices
    }
    candidates = {
        match.group(1).casefold()
        for match in _DEVICE_LIKE_ID.finditer(text)
    }
    for device_id in canonical:
        if _contains_exact_identifier(text, device_id):
            candidates.add(device_id)
    if not candidates:
        return None, None, False
    if len(candidates) > 1:
        return None, None, True
    requested_id = next(iter(candidates))
    return requested_id, canonical.get(requested_id), False


def _contains_exact_identifier(text: str, identifier: str) -> bool:
    pattern = re.compile(
        rf"(?<![a-z0-9_-]){re.escape(identifier)}(?![a-z0-9_-])",
        re.IGNORECASE,
    )
    return pattern.search(text) is not None


def _service_data(item: ServiceKnowledge) -> ServiceQueryData:
    return ServiceQueryData(
        name=item.name,
        status=item.status,
        available=item.available,
        observed_at=item.observed_at,
        stale=item.stale,
        sources=item.sources,
    )


def _maintenance_data(item: MaintenanceKnowledge) -> MaintenanceQueryData:
    return MaintenanceQueryData(
        name=item.name,
        status=item.status,
        available=item.available,
        observed_at=item.observed_at,
        stale=item.stale,
        sources=item.sources,
    )


def _device_data(item: DeviceKnowledge) -> DeviceQueryData:
    return DeviceQueryData(
        device_id=item.device_id,
        known=item.known,
        available=item.available,
        online=item.online,
        observed_at=item.observed_at,
        stale=KnowledgeValue.UNKNOWN,
        hardware_verified=item.hardware_verified,
        sources=item.sources,
    )


def _unsupported_result(
    snapshot: SystemKnowledgeSnapshot,
    reason: KnowledgeQueryReason,
) -> KnowledgeQueryResult:
    return KnowledgeQueryResult(
        knowledge_schema_version=snapshot.schema_version,
        snapshot_captured_at=snapshot.captured_at,
        scope=KnowledgeQueryScope.UNSUPPORTED,
        data=None,
        sources=(KnowledgeSource.UNKNOWN,),
        incomplete=True,
        reason=reason,
    )


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
    if not sources:
        sources.add(KnowledgeSource.UNKNOWN)
    return tuple(sorted(sources, key=lambda item: item.value))


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
