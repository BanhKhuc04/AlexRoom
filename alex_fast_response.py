from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from alex_intelligence import IntelligenceRoute
from alex_intent_planner import IntentCertainty, IntentStep
from alex_knowledge_contracts import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeSource,
    KnowledgeStatus,
    KnowledgeValue,
)
from alex_knowledge_query import (
    DeviceDetailQueryData,
    DeviceListQueryData,
    DeviceQueryData,
    KnowledgeQueryResult,
    KnowledgeQueryScope,
    MaintenanceQueryData,
    ServiceQueryData,
    SystemStatusQueryData,
)


class FastResponseReason(str, Enum):
    COMPOSED_SYSTEM_STATUS = "composed_system_status"
    COMPOSED_DEVICE_LIST = "composed_device_list"
    COMPOSED_DEVICE_DETAIL = "composed_device_detail"
    STEP_REQUIRES_CLARIFICATION = "step_requires_clarification"
    UNKNOWN_INTENT_CERTAINTY = "unknown_intent_certainty"
    UNSUPPORTED_ROUTE = "unsupported_route"
    UNSUPPORTED_STEP_SCOPE = "unsupported_step_scope"
    UNSUPPORTED_KNOWLEDGE_SCOPE = "unsupported_knowledge_scope"
    UNSUPPORTED_KNOWLEDGE_SCHEMA = "unsupported_knowledge_schema"
    INCOMPATIBLE_SCOPE = "incompatible_scope"
    INVALID_KNOWLEDGE_DATA = "invalid_knowledge_data"
    INSUFFICIENT_KNOWLEDGE = "insufficient_knowledge"


@dataclass(frozen=True, slots=True)
class FastResponseMetadata:
    snapshot_captured_at: str
    observations: tuple[tuple[str, str], ...]
    sources: tuple[KnowledgeSource, ...]

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "snapshot_captured_at": self.snapshot_captured_at,
            "observations": [
                {"subject": subject, "observed_at": observed_at}
                for subject, observed_at in self.observations
            ],
            "sources": [source.value for source in self.sources],
        }


@dataclass(frozen=True, slots=True)
class FastResponseResult:
    handled: bool
    text: str | None
    reason: FastResponseReason
    scope: KnowledgeQueryScope
    incomplete: bool
    warnings: tuple[str, ...]
    knowledge_schema_version: int
    metadata: FastResponseMetadata

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "handled": self.handled,
            "text": self.text,
            "reason": self.reason.value,
            "scope": self.scope.value,
            "incomplete": self.incomplete,
            "warnings": list(self.warnings),
            "knowledge_schema_version": self.knowledge_schema_version,
            "metadata": self.metadata.to_compact_dict(),
        }


_ONLINE_STATUSES = {KnowledgeStatus.ONLINE, KnowledgeStatus.CONNECTED}
_OPERATING_STATUSES = {
    KnowledgeStatus.ACTIVE, KnowledgeStatus.HEALTHY, KnowledgeStatus.RUNNING
}
_UNHEALTHY_STATUS_TEXT = {
    KnowledgeStatus.CRITICAL: "đang ở trạng thái nghiêm trọng",
    KnowledgeStatus.DEGRADED: "đang bị suy giảm",
    KnowledgeStatus.INACTIVE: "đang không hoạt động",
    KnowledgeStatus.WARNING: "đang ở trạng thái cảnh báo",
    KnowledgeStatus.WAKING: "đang khởi động",
}
_UNAVAILABLE_VALUES = {KnowledgeValue.KNOWN_FALSE, KnowledgeValue.UNAVAILABLE}


def compose_fast_response(
    *,
    step: IntentStep,
    knowledge: KnowledgeQueryResult,
) -> FastResponseResult:
    """Compose one factual read-only response without external operations."""

    if knowledge.knowledge_schema_version != KNOWLEDGE_SCHEMA_VERSION:
        return _decline(
            knowledge, FastResponseReason.UNSUPPORTED_KNOWLEDGE_SCHEMA,
            incomplete=True,
        )
    if step.requires_clarification:
        return _decline(
            knowledge, FastResponseReason.STEP_REQUIRES_CLARIFICATION
        )
    if step.certainty is IntentCertainty.UNKNOWN:
        return _decline(
            knowledge, FastResponseReason.UNKNOWN_INTENT_CERTAINTY
        )
    if (
        step.decision.route is not IntelligenceRoute.SYSTEM
        or not step.decision.matched
    ):
        return _decline(knowledge, FastResponseReason.UNSUPPORTED_ROUTE)
    if knowledge.scope is KnowledgeQueryScope.UNSUPPORTED:
        return _decline(
            knowledge, FastResponseReason.UNSUPPORTED_KNOWLEDGE_SCOPE
        )

    tools = step.decision.allowed_tool_names
    if tools == ("system_status",):
        if knowledge.scope is not KnowledgeQueryScope.SYSTEM_STATUS:
            return _decline(
                knowledge, FastResponseReason.INCOMPATIBLE_SCOPE
            )
        return _compose_system_status(knowledge)
    if tools == ("list_devices",):
        if knowledge.scope is KnowledgeQueryScope.DEVICE_LIST:
            return _compose_device_list(knowledge)
        if knowledge.scope is KnowledgeQueryScope.DEVICE_DETAIL:
            return _compose_device_detail(knowledge)
        return _decline(knowledge, FastResponseReason.INCOMPATIBLE_SCOPE)
    return _decline(knowledge, FastResponseReason.UNSUPPORTED_STEP_SCOPE)


def compact_fast_response(result: FastResponseResult) -> dict[str, Any]:
    return result.to_compact_dict()


def _compose_system_status(
    knowledge: KnowledgeQueryResult,
) -> FastResponseResult:
    if not isinstance(knowledge.data, SystemStatusQueryData):
        return _decline(
            knowledge, FastResponseReason.INVALID_KNOWLEDGE_DATA
        )

    data = knowledge.data
    services = {item.name: item for item in data.services}
    maintenance = {item.name: item for item in data.maintenance}
    core = services.get("core")
    brain = services.get("brain")
    health = maintenance.get("health")
    backup = maintenance.get("backup")
    warnings = list(_base_warnings(knowledge))

    if _fully_healthy(data, core, brain, health, backup):
        text = "ALEX đang hoạt động bình thường. "
        if (
            core is not None
            and brain is not None
            and core.status in _ONLINE_STATUSES
            and brain.status in _ONLINE_STATUSES
        ):
            text += "Core và Brain đều online."
        else:
            text += "Core và Brain đều đang hoạt động."
        return _handled(
            knowledge, text, FastResponseReason.COMPOSED_SYSTEM_STATUS,
            warnings, _system_observations(data),
        )

    sentences: list[str] = []
    known_fact = False
    if data.overall_status is KnowledgeStatus.UNKNOWN:
        sentences.append("Trạng thái tổng thể của ALEX hiện chưa xác định.")
    elif data.overall_status is not KnowledgeStatus.HEALTHY:
        sentences.append(_overall_status_sentence(data.overall_status))
        known_fact = True

    for name, label in (("core", "Core"), ("brain", "Brain")):
        service = services.get(name)
        if service is None:
            sentences.append(f"Trạng thái {label} hiện chưa xác định.")
            continue
        sentence, item_known, item_warnings = _entity_status_sentence(
            label,
            service.status,
            service.available,
            service.stale,
        )
        sentences.append(sentence)
        known_fact = known_fact or item_known
        warnings.extend(item_warnings)

    for name, label in (("backup", "Backup"), ("health", "Health check")):
        item = maintenance.get(name)
        if item is None:
            continue
        effective = _effective_status(item.status, item.available)
        if effective is KnowledgeStatus.HEALTHY:
            warnings.extend(_freshness_warnings(item.stale))
            continue
        sentence, item_known, item_warnings = _entity_status_sentence(
            label,
            item.status,
            item.available,
            item.stale,
        )
        sentences.append(sentence)
        known_fact = known_fact or item_known
        warnings.extend(item_warnings)

    if not known_fact:
        return _decline(
            knowledge, FastResponseReason.INSUFFICIENT_KNOWLEDGE,
            warnings=warnings, observations=_system_observations(data),
        )
    return _handled(
        knowledge, " ".join(sentences),
        FastResponseReason.COMPOSED_SYSTEM_STATUS, warnings,
        _system_observations(data),
    )


def _compose_device_detail(
    knowledge: KnowledgeQueryResult,
) -> FastResponseResult:
    if not isinstance(knowledge.data, DeviceDetailQueryData):
        return _decline(
            knowledge, FastResponseReason.INVALID_KNOWLEDGE_DATA
        )

    data = knowledge.data
    device_id = data.requested_device_id.upper()
    warnings = list(_base_warnings(knowledge))
    if not data.found:
        text = (
            f"Không tìm thấy thiết bị {device_id} trong knowledge hiện tại."
        )
        return _handled(
            knowledge, text, FastResponseReason.COMPOSED_DEVICE_DETAIL,
            warnings, (),
        )
    if data.device is None:
        return _decline(
            knowledge, FastResponseReason.INVALID_KNOWLEDGE_DATA,
            warnings=warnings,
        )

    device = data.device
    warnings.extend(_freshness_warnings(device.stale))
    text = _device_detail_text(device)
    return _handled(
        knowledge, text, FastResponseReason.COMPOSED_DEVICE_DETAIL,
        warnings, _device_observations((device,)),
    )


def _compose_device_list(
    knowledge: KnowledgeQueryResult,
) -> FastResponseResult:
    if not isinstance(knowledge.data, DeviceListQueryData):
        return _decline(
            knowledge, FastResponseReason.INVALID_KNOWLEDGE_DATA
        )

    devices = knowledge.data.devices
    warnings = list(_base_warnings(knowledge))
    if not devices:
        return _handled(
            knowledge, "Snapshot hiện không có thiết bị nào để liệt kê.",
            FastResponseReason.COMPOSED_DEVICE_LIST, warnings, (),
        )

    summaries: list[str] = []
    for device in devices:
        summaries.append(_device_list_summary(device))
        warnings.extend(_freshness_warnings(device.stale))
    text = (
        f"Có {len(devices)} thiết bị trong snapshot: "
        + ", ".join(summaries)
        + "."
    )
    return _handled(
        knowledge, text, FastResponseReason.COMPOSED_DEVICE_LIST,
        warnings, _device_observations(devices),
    )


def _device_detail_text(device: DeviceQueryData) -> str:
    device_id = device.device_id.upper()
    state = _device_state_text(device.online)
    if device.online is KnowledgeValue.UNKNOWN:
        return f"Hiện chưa xác định được {device_id} có online hay không."
    if device.online is KnowledgeValue.UNAVAILABLE:
        return (
            f"Hiện không có dữ liệu khả dụng để xác định "
            f"{device_id} có online hay không."
        )
    if device.online is KnowledgeValue.RESTRICTED:
        return f"Trạng thái online của {device_id} đang bị giới hạn truy cập."
    if device.stale is KnowledgeValue.KNOWN_TRUE:
        return (
            f"Dữ liệu gần nhất cho thấy {device_id} {state}, "
            "nhưng thông tin này đã được đánh dấu là cũ."
        )
    if device.stale is not KnowledgeValue.KNOWN_FALSE:
        return (
            f"Snapshot ghi nhận {device_id} {state}, "
            "nhưng chưa xác định được độ mới của dữ liệu."
        )
    return f"{device_id} đang {state}."


def _device_list_summary(device: DeviceQueryData) -> str:
    device_id = device.device_id.upper()
    if device.online is KnowledgeValue.UNKNOWN:
        text = f"{device_id} chưa xác định trạng thái"
    elif device.online is KnowledgeValue.UNAVAILABLE:
        text = f"{device_id} chưa có dữ liệu trạng thái khả dụng"
    elif device.online is KnowledgeValue.RESTRICTED:
        text = f"{device_id} có trạng thái bị giới hạn truy cập"
    else:
        text = f"{device_id} {_device_state_text(device.online)}"

    if device.stale is KnowledgeValue.KNOWN_TRUE:
        return f"{text} (dữ liệu cũ)"
    if device.stale is not KnowledgeValue.KNOWN_FALSE:
        return f"{text} (chưa xác định độ mới)"
    return text


def _device_state_text(value: KnowledgeValue) -> str:
    if value is KnowledgeValue.KNOWN_TRUE:
        return "online"
    if value is KnowledgeValue.KNOWN_FALSE:
        return "offline"
    return "chưa xác định trạng thái"


def _fully_healthy(
    data: SystemStatusQueryData,
    core: ServiceQueryData | None,
    brain: ServiceQueryData | None,
    health: MaintenanceQueryData | None,
    backup: MaintenanceQueryData | None,
) -> bool:
    if data.overall_status is not KnowledgeStatus.HEALTHY or None in (
        core, brain, health, backup
    ):
        return False
    assert core is not None
    assert brain is not None
    assert health is not None
    assert backup is not None
    return all(
        item.status in _ONLINE_STATUSES | _OPERATING_STATUSES
        and item.available is KnowledgeValue.KNOWN_TRUE
        and item.stale is KnowledgeValue.KNOWN_FALSE
        for item in (core, brain)
    ) and all(
        item.status is KnowledgeStatus.HEALTHY
        and item.available is KnowledgeValue.KNOWN_TRUE
        and item.stale is KnowledgeValue.KNOWN_FALSE
        for item in (health, backup)
    )


def _overall_status_sentence(status: KnowledgeStatus) -> str:
    labels = {
        KnowledgeStatus.CRITICAL: "nghiêm trọng",
        KnowledgeStatus.DEGRADED: "suy giảm",
        KnowledgeStatus.OFFLINE: "offline",
        KnowledgeStatus.UNAVAILABLE: "không khả dụng",
        KnowledgeStatus.WARNING: "cảnh báo",
    }
    label = labels.get(status, status.value)
    return f"Snapshot ghi nhận trạng thái tổng thể của ALEX là {label}."


def _entity_status_sentence(
    label: str,
    status: KnowledgeStatus,
    available: KnowledgeValue,
    stale: KnowledgeValue,
) -> tuple[str, bool, tuple[str, ...]]:
    effective = _effective_status(status, available)
    warnings = _freshness_warnings(stale)
    if effective is KnowledgeStatus.UNKNOWN:
        return f"Trạng thái {label} hiện chưa xác định.", False, warnings
    if effective is KnowledgeStatus.UNAVAILABLE:
        state = "hiện không có dữ liệu khả dụng"
    elif effective is KnowledgeStatus.RESTRICTED:
        state = "có trạng thái bị giới hạn truy cập"
    elif effective in _ONLINE_STATUSES:
        state = "online"
    elif effective in {KnowledgeStatus.OFFLINE, KnowledgeStatus.DISCONNECTED}:
        state = "offline"
    elif effective in _OPERATING_STATUSES:
        state = "đang hoạt động"
    else:
        state = _UNHEALTHY_STATUS_TEXT.get(
            effective,
            f"đang ở trạng thái {effective.value}",
        )

    if stale is KnowledgeValue.KNOWN_TRUE:
        text = (
            f"Dữ liệu gần nhất ghi nhận {label} {state}, "
            "nhưng thông tin này đã được đánh dấu là cũ."
        )
    elif stale is not KnowledgeValue.KNOWN_FALSE:
        text = (
            f"Snapshot ghi nhận {label} {state}, "
            "nhưng chưa xác định được độ mới của dữ liệu."
        )
    else:
        text = f"{label} {state}."
    return text, True, warnings


def _effective_status(
    status: KnowledgeStatus,
    available: KnowledgeValue,
) -> KnowledgeStatus:
    if available in _UNAVAILABLE_VALUES:
        return KnowledgeStatus.UNAVAILABLE
    if available is KnowledgeValue.RESTRICTED:
        return KnowledgeStatus.RESTRICTED
    return status


def _base_warnings(
    knowledge: KnowledgeQueryResult,
) -> tuple[str, ...]:
    return ("incomplete_knowledge",) if knowledge.incomplete else ()


def _freshness_warnings(stale: KnowledgeValue) -> tuple[str, ...]:
    if stale is KnowledgeValue.KNOWN_TRUE:
        return ("stale_data",)
    if stale is not KnowledgeValue.KNOWN_FALSE:
        return ("freshness_unknown",)
    return ()


def _system_observations(
    data: SystemStatusQueryData,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (item.name, item.observed_at)
        for item in (*data.services, *data.maintenance)
        if item.observed_at is not None
    )


def _device_observations(
    devices: tuple[DeviceQueryData, ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (device.device_id, device.observed_at)
        for device in devices
        if device.observed_at is not None
    )


def _handled(
    knowledge: KnowledgeQueryResult,
    text: str,
    reason: FastResponseReason,
    warnings: list[str],
    observations: tuple[tuple[str, str], ...],
) -> FastResponseResult:
    return FastResponseResult(
        handled=True, text=text, reason=reason, scope=knowledge.scope,
        incomplete=knowledge.incomplete,
        warnings=_unique(warnings),
        knowledge_schema_version=knowledge.knowledge_schema_version,
        metadata=_metadata(knowledge, observations),
    )


def _decline(
    knowledge: KnowledgeQueryResult,
    reason: FastResponseReason,
    *,
    incomplete: bool | None = None,
    warnings: list[str] | None = None,
    observations: tuple[tuple[str, str], ...] = (),
) -> FastResponseResult:
    selected_warnings = list(
        warnings if warnings is not None else _base_warnings(knowledge)
    )
    return FastResponseResult(
        handled=False, text=None, reason=reason, scope=knowledge.scope,
        incomplete=(
            knowledge.incomplete if incomplete is None else incomplete
        ),
        warnings=_unique(selected_warnings),
        knowledge_schema_version=knowledge.knowledge_schema_version,
        metadata=_metadata(knowledge, observations),
    )


def _metadata(
    knowledge: KnowledgeQueryResult,
    observations: tuple[tuple[str, str], ...],
) -> FastResponseMetadata:
    return FastResponseMetadata(
        snapshot_captured_at=knowledge.snapshot_captured_at,
        observations=observations,
        sources=knowledge.sources,
    )


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
