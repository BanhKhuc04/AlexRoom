from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
KNOWLEDGE_SCHEMA_VERSION = 1


class KnowledgeValue(str, Enum):
    """Five-valued knowledge used where a boolean would lose safety meaning."""

    KNOWN_TRUE = "known_true"
    KNOWN_FALSE = "known_false"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    RESTRICTED = "restricted"


class KnowledgeStatus(str, Enum):
    ACTIVE = "active"
    CONNECTED = "connected"
    CRITICAL = "critical"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    HEALTHY = "healthy"
    INACTIVE = "inactive"
    OFFLINE = "offline"
    ONLINE = "online"
    RESTRICTED = "restricted"
    RUNNING = "running"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    WAKING = "waking"
    WARNING = "warning"


class KnowledgeSource(str, Enum):
    CORE_RUNTIME = "core_runtime"
    HARDWARE_REGISTRY = "hardware_registry"
    HEALTH_REPORT = "health_report"
    STORE = "store"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ServiceKnowledge:
    name: str
    status: KnowledgeStatus
    available: KnowledgeValue
    detail: str | None
    observed_at: str | None
    stale: KnowledgeValue
    sources: tuple[KnowledgeSource, ...]


@dataclass(frozen=True, slots=True)
class CapabilityKnowledge:
    capability_id: str
    availability: KnowledgeValue
    verification_status: str
    hardware_verified: KnowledgeValue
    command_allowed: KnowledgeValue
    state: JsonScalar
    observed_at: str | None
    restriction_reason: str | None
    sources: tuple[KnowledgeSource, ...]


@dataclass(frozen=True, slots=True)
class DeviceKnowledge:
    device_id: str
    known: KnowledgeValue
    available: KnowledgeValue
    online: KnowledgeValue
    status: KnowledgeStatus
    observed_at: str | None
    hardware_verified: KnowledgeValue
    verification_status: str
    capabilities: tuple[CapabilityKnowledge, ...]
    sources: tuple[KnowledgeSource, ...]


@dataclass(frozen=True, slots=True)
class MaintenanceKnowledge:
    name: str
    status: KnowledgeStatus
    available: KnowledgeValue
    detail: str | None
    observed_at: str | None
    stale: KnowledgeValue
    sources: tuple[KnowledgeSource, ...]


@dataclass(frozen=True, slots=True)
class RuntimeKnowledge:
    room_mode: str | None
    simulator: KnowledgeValue
    observed_at: str | None
    sources: tuple[KnowledgeSource, ...]


@dataclass(frozen=True, slots=True)
class SystemKnowledgeSnapshot:
    """Immutable in-memory view. Canonical ALEX services remain authoritative."""

    schema_version: int = field(
        init=False,
        default=KNOWLEDGE_SCHEMA_VERSION,
    )
    captured_at: str
    version: str
    overall_status: KnowledgeStatus
    overall_sources: tuple[KnowledgeSource, ...]
    services: tuple[ServiceKnowledge, ...]
    devices: tuple[DeviceKnowledge, ...]
    maintenance: tuple[MaintenanceKnowledge, ...]
    runtime: RuntimeKnowledge

    def to_compact_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "version": self.version,
            "system": {
                "status": self.overall_status.value,
                "sources": _compact_sources(self.overall_sources),
            },
            "services": {},
            "devices": {},
            "maintenance": {},
        }

        services: dict[str, Any] = result["services"]
        for service in self.services:
            item: dict[str, Any] = {
                "status": service.status.value,
                "available": _compact_value(service.available),
                "sources": _compact_sources(service.sources),
            }
            if service.detail is not None:
                item["detail"] = service.detail
            if service.observed_at is not None:
                item["observed_at"] = service.observed_at
            if service.stale is not KnowledgeValue.UNKNOWN:
                item["stale"] = _compact_value(service.stale)
            services[service.name] = item

        devices: dict[str, Any] = result["devices"]
        for device in self.devices:
            item = {
                "known": _compact_value(device.known),
                "available": _compact_value(device.available),
                "online": _compact_value(device.online),
                "status": device.status.value,
                "hardware_verified": _compact_value(device.hardware_verified),
                "verification_status": device.verification_status,
                "sources": _compact_sources(device.sources),
                "capabilities": {},
            }
            compact_capabilities: dict[str, Any] = item["capabilities"]
            for capability in device.capabilities:
                if capability.availability is KnowledgeValue.RESTRICTED:
                    compact_capabilities[capability.capability_id] = "restricted"
                    continue
                compact_capability: dict[str, Any] = {
                    "availability": _compact_value(capability.availability),
                    "hardware_verified": _compact_value(
                        capability.hardware_verified
                    ),
                }
                if capability.verification_status != "unknown":
                    compact_capability["verification_status"] = (
                        capability.verification_status
                    )
                if capability.command_allowed is not KnowledgeValue.UNKNOWN:
                    compact_capability["command_allowed"] = _compact_value(
                        capability.command_allowed
                    )
                if capability.state is not None:
                    compact_capability["state"] = capability.state
                if capability.observed_at is not None:
                    compact_capability["observed_at"] = capability.observed_at
                compact_capabilities[capability.capability_id] = compact_capability
            if device.observed_at is not None:
                item["observed_at"] = device.observed_at
            devices[device.device_id] = item

        maintenance: dict[str, Any] = result["maintenance"]
        for entry in self.maintenance:
            item = {
                "status": entry.status.value,
                "available": _compact_value(entry.available),
                "sources": _compact_sources(entry.sources),
            }
            if entry.detail is not None:
                item["detail"] = entry.detail
            if entry.observed_at is not None:
                item["observed_at"] = entry.observed_at
            if entry.stale is not KnowledgeValue.UNKNOWN:
                item["stale"] = _compact_value(entry.stale)
            maintenance[entry.name] = item

        if (
            self.runtime.room_mode is not None
            or self.runtime.simulator is not KnowledgeValue.UNKNOWN
            or self.runtime.observed_at is not None
        ):
            result["runtime"] = {
                "room_mode": self.runtime.room_mode,
                "simulator": _compact_value(self.runtime.simulator),
                "sources": _compact_sources(self.runtime.sources),
            }
            if self.runtime.observed_at is not None:
                result["runtime"]["observed_at"] = self.runtime.observed_at
        return result


def _compact_value(value: KnowledgeValue) -> bool | str:
    if value is KnowledgeValue.KNOWN_TRUE:
        return True
    if value is KnowledgeValue.KNOWN_FALSE:
        return False
    return value.value


def _compact_sources(sources: tuple[KnowledgeSource, ...]) -> list[str]:
    return [source.value for source in sources]
