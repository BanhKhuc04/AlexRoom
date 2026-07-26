from __future__ import annotations

from typing import Any, Mapping

from alex_knowledge_contracts import (
    CapabilityKnowledge,
    DeviceKnowledge,
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeSource,
    KnowledgeStatus,
    KnowledgeValue,
    MaintenanceKnowledge,
    RuntimeKnowledge,
    ServiceKnowledge,
    SystemKnowledgeSnapshot,
)
from alex_knowledge_normalization import (
    availability_from_online as _availability_from_online,
    availability_from_status as _availability_from_status,
    capability_state as _capability_state,
    device_sources as _device_sources,
    identifier as _identifier,
    knowledge_value as _value,
    mapping as _mapping,
    named_mappings as _named_mappings,
    observation_timestamp as _observation_timestamp,
    online_value as _online_value,
    safe_detail as _safe_detail,
    safe_text as _safe_text,
    sequence as _sequence,
    sources as _sources,
    status as _status,
    text as _text,
    verification as _verification,
    verified_value as _verified_value,
)


def build_system_knowledge_snapshot(
    *,
    captured_at: str,
    version: str,
    overall_status: object = None,
    health_report: object = None,
    services: object = None,
    devices: object = None,
    maintenance: object = None,
    runtime: object = None,
) -> SystemKnowledgeSnapshot:
    """Normalize caller-supplied canonical data without querying any authority."""

    if not isinstance(captured_at, str):
        raise TypeError("captured_at_must_be_string")
    if not isinstance(version, str):
        raise TypeError("version_must_be_string")

    health_envelope = _mapping(health_report)
    report = _mapping(health_envelope.get("report"))
    if not report:
        report = health_envelope
    health_status = health_envelope.get("status", report.get("status"))
    normalized_overall = _status(
        overall_status if overall_status is not None else health_status
    )
    overall_sources = (
        (KnowledgeSource.HEALTH_REPORT,)
        if health_envelope
        else (KnowledgeSource.UNKNOWN,)
    )

    normalized_services = _build_services(services)
    normalized_devices = _build_devices(devices)
    normalized_maintenance = _build_maintenance(
        health_envelope,
        report,
        maintenance,
    )
    normalized_runtime = _build_runtime(runtime)

    return SystemKnowledgeSnapshot(
        captured_at=captured_at,
        version=version,
        overall_status=normalized_overall,
        overall_sources=overall_sources,
        services=normalized_services,
        devices=normalized_devices,
        maintenance=normalized_maintenance,
        runtime=normalized_runtime,
    )


def compact_system_knowledge(
    snapshot: SystemKnowledgeSnapshot,
) -> dict[str, Any]:
    return snapshot.to_compact_dict()


def _build_services(raw_services: object) -> tuple[ServiceKnowledge, ...]:
    source_map = _named_mappings(raw_services, ("name", "service"))
    entries: list[ServiceKnowledge] = []
    for name in sorted({"core", "brain", *source_map}):
        data = source_map.get(name, {})
        status = _status(data.get("status", data.get("state")))
        available = _value(data.get("available"))
        if available is KnowledgeValue.UNKNOWN:
            available = _availability_from_status(status)
        if available is KnowledgeValue.KNOWN_FALSE and status in {
            KnowledgeStatus.HEALTHY,
            KnowledgeStatus.ONLINE,
            KnowledgeStatus.ACTIVE,
            KnowledgeStatus.RUNNING,
        }:
            status = KnowledgeStatus.UNAVAILABLE
        entries.append(
            ServiceKnowledge(
                name=name,
                status=status,
                available=available,
                detail=_safe_detail(data),
                observed_at=_observation_timestamp(data.get("observed_at")),
                stale=_value(data.get("stale")),
                sources=_sources(
                    data.get("source", data.get("sources")),
                    (
                        (KnowledgeSource.CORE_RUNTIME,)
                        if data
                        else (KnowledgeSource.UNKNOWN,)
                    ),
                ),
            )
        )
    return tuple(entries)


def _build_devices(raw_devices: object) -> tuple[DeviceKnowledge, ...]:
    source_map = _named_mappings(raw_devices, ("device_id", "node_id"))
    entries: list[DeviceKnowledge] = []
    for device_id in sorted(source_map):
        data = source_map[device_id]
        verification = _verification(data.get("verification_status"))
        known = _value(data.get("known"))
        if known is KnowledgeValue.UNKNOWN and (
            verification != "unknown"
            or isinstance(data.get("capabilities"), Mapping)
        ):
            known = KnowledgeValue.KNOWN_TRUE

        status = _status(
            data.get("connection", data.get("availability", data.get("status")))
        )
        online = _online_value(
            data.get("online"),
            data.get("connection", data.get("availability")),
        )
        available = _value(data.get("available"))
        if available is KnowledgeValue.UNKNOWN:
            available = _availability_from_online(online)

        hardware_verified = _verified_value(
            data.get("hardware_verified"),
            known=known,
            verification_status=verification,
        )
        sources = _device_sources(data)
        observed_at = _observation_timestamp(
            data.get("observed_at"),
            data.get("last_seen_at"),
            data.get("last_seen"),
        )
        capabilities = _build_capabilities(data, sources, observed_at)
        entries.append(
            DeviceKnowledge(
                device_id=device_id,
                known=known,
                available=available,
                online=online,
                status=status,
                observed_at=observed_at,
                hardware_verified=hardware_verified,
                verification_status=verification,
                capabilities=capabilities,
                sources=sources,
            )
        )
    return tuple(entries)


def _build_capabilities(
    device: Mapping[str, Any],
    device_sources: tuple[KnowledgeSource, ...],
    device_observed_at: str | None,
) -> tuple[CapabilityKnowledge, ...]:
    raw_capabilities = _mapping(device.get("capabilities"))
    restricted = {
        identifier
        for item in _sequence(device.get("restricted_capabilities"))
        if (identifier := _identifier(item)) is not None
    }
    reported = _mapping(device.get("reported_state"))
    capability_ids = sorted(
        {
            *(
                identifier
                for item in raw_capabilities
                if (identifier := _identifier(item)) is not None
            ),
            *restricted,
        }
    )
    entries: list[CapabilityKnowledge] = []
    for capability_id in capability_ids:
        raw = next(
            (
                value
                for key, value in raw_capabilities.items()
                if _identifier(key) == capability_id
            ),
            None,
        )
        data = _mapping(raw)
        verification = _verification(data.get("verification_status"))
        is_restricted = (
            capability_id in restricted
            or verification == "restricted"
            or _text(data.get("risk_level")) == "restricted"
            or _text(data.get("availability")) == "restricted"
        )
        command_allowed = _value(data.get("command_allowed"))
        availability = (
            KnowledgeValue.RESTRICTED
            if is_restricted
            else _value(data.get("available", data.get("availability")))
        )
        if (
            availability is KnowledgeValue.UNKNOWN
            and (data or capability_id in reported)
        ):
            availability = (
                KnowledgeValue.KNOWN_TRUE
                if command_allowed is not KnowledgeValue.KNOWN_FALSE
                else KnowledgeValue.UNKNOWN
            )
        hardware_verified = _verified_value(
            data.get("hardware_verified"),
            known=KnowledgeValue.KNOWN_TRUE,
            verification_status=verification,
        )
        state = None if is_restricted else _capability_state(
            capability_id,
            data,
            reported,
        )
        entries.append(
            CapabilityKnowledge(
                capability_id=capability_id,
                availability=availability,
                verification_status=verification,
                hardware_verified=hardware_verified,
                command_allowed=(
                    KnowledgeValue.KNOWN_FALSE
                    if is_restricted
                    else command_allowed
                ),
                state=state,
                observed_at=(
                    _observation_timestamp(
                        data.get("observed_at"),
                        device_observed_at,
                    )
                    if state is not None
                    else None
                ),
                restriction_reason=(
                    _safe_text(data.get("restriction_reason"))
                    if is_restricted
                    else None
                ),
                sources=_sources(
                    data.get("source", data.get("sources")),
                    (
                        KnowledgeSource.HARDWARE_REGISTRY,
                        *(
                            (KnowledgeSource.CORE_RUNTIME,)
                            if state is not None
                            else ()
                        ),
                    )
                    or device_sources,
                ),
            )
        )
    return tuple(entries)


def _build_maintenance(
    health_envelope: Mapping[str, Any],
    report: Mapping[str, Any],
    raw_maintenance: object,
) -> tuple[MaintenanceKnowledge, ...]:
    checks = _mapping(report.get("checks"))
    source_map = {
        name: _mapping(checks.get(name))
        for name in ("backup", "update")
    }
    if health_envelope:
        source_map["health"] = health_envelope
    explicit = _named_mappings(raw_maintenance, ("name",))
    source_map.update(explicit)
    report_observed_at = _observation_timestamp(
        report.get("generated_at"),
        health_envelope.get("generated_at"),
    )

    entries: list[MaintenanceKnowledge] = []
    for name in ("backup", "health", "update"):
        data = source_map.get(name, {})
        status = _status(data.get("status"))
        available = _value(data.get("available"))
        if available is KnowledgeValue.UNKNOWN and data:
            available = (
                KnowledgeValue.UNKNOWN
                if status is KnowledgeStatus.UNKNOWN
                else KnowledgeValue.KNOWN_TRUE
            )
        if available is KnowledgeValue.KNOWN_FALSE:
            status = KnowledgeStatus.UNAVAILABLE
        entries.append(
            MaintenanceKnowledge(
                name=name,
                status=status,
                available=available,
                detail=_safe_detail(data),
                observed_at=_observation_timestamp(
                    data.get("observed_at"),
                    data.get("generated_at"),
                    (
                        report_observed_at
                        if name not in explicit
                        else None
                    ),
                ),
                stale=_value(data.get("stale")),
                sources=_sources(
                    data.get("source", data.get("sources")),
                    (
                        (KnowledgeSource.HEALTH_REPORT,)
                        if name in source_map and name not in explicit
                        else (KnowledgeSource.UNKNOWN,)
                    ),
                ),
            )
        )
    return tuple(entries)


def _build_runtime(raw_runtime: object) -> RuntimeKnowledge:
    data = _mapping(raw_runtime)
    room_mode = _safe_text(data.get("room_mode", data.get("mode")))
    return RuntimeKnowledge(
        room_mode=room_mode,
        simulator=_value(data.get("simulator")),
        observed_at=_observation_timestamp(data.get("observed_at")),
        sources=_sources(
            data.get("source", data.get("sources")),
            (
                (KnowledgeSource.CORE_RUNTIME,)
                if data
                else (KnowledgeSource.UNKNOWN,)
            ),
        ),
    )
