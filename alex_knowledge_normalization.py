from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

from alex_knowledge_contracts import (
    JsonScalar,
    KnowledgeSource,
    KnowledgeStatus,
    KnowledgeValue,
)


_SECRET_TEXT = re.compile(
    r"(?i)(?:api[_-]?key|client[_-]?key|password|passwd|secret|token|authorization|(?:^|[_-])key(?:$|[_-]))"
)
_ONLINE_STATUSES = frozenset({"active", "connected", "healthy", "online", "running"})
_OFFLINE_STATUSES = frozenset({"disconnected", "inactive", "offline"})
_KNOWN_VERIFICATION_STATUSES = frozenset(
    {
        "unknown",
        "simulated",
        "software_verified",
        "basic_physical_validated",
        "hardware_verified",
        "restricted",
    }
)


def named_mappings(
    raw: object,
    id_fields: tuple[str, ...],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw, Mapping):
        items = raw.get("items")
        if is_sequence(items):
            raw = items
        else:
            for key, value in raw.items():
                name = identifier(key)
                if name and isinstance(value, Mapping):
                    result[name] = value
            return result
    if is_sequence(raw):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            name = next(
                (
                    identifier(item.get(field))
                    for field in id_fields
                    if identifier(item.get(field))
                ),
                None,
            )
            if name is not None and name not in result:
                result[name] = item
    return result


def device_sources(data: Mapping[str, Any]) -> tuple[KnowledgeSource, ...]:
    inferred: list[KnowledgeSource] = []
    if any(
        key in data
        for key in ("connection", "online", "reported_state", "last_seen_at")
    ):
        inferred.append(KnowledgeSource.CORE_RUNTIME)
    if any(
        key in data
        for key in ("capabilities", "hardware_verified", "verification_status")
    ):
        inferred.append(KnowledgeSource.HARDWARE_REGISTRY)
    explicit = sources(
        data.get(
            "knowledge_source",
            data.get("sources", data.get("source")),
        ),
        (),
    )
    combined = {
        *inferred,
        *(
            ()
            if explicit == (KnowledgeSource.UNKNOWN,)
            else explicit
        ),
    }
    if not combined:
        combined.add(KnowledgeSource.UNKNOWN)
    return tuple(sorted(combined, key=lambda item: item.value))


def sources(
    raw: object,
    inferred: tuple[KnowledgeSource, ...],
) -> tuple[KnowledgeSource, ...]:
    aliases = {
        "core_runtime": KnowledgeSource.CORE_RUNTIME,
        "local_software": KnowledgeSource.CORE_RUNTIME,
        "mqtt": KnowledgeSource.CORE_RUNTIME,
        "simulated": KnowledgeSource.CORE_RUNTIME,
        "hardware_registry": KnowledgeSource.HARDWARE_REGISTRY,
        "server_authoritative": KnowledgeSource.HARDWARE_REGISTRY,
        "health_report": KnowledgeSource.HEALTH_REPORT,
        "sqlite": KnowledgeSource.STORE,
        "store": KnowledgeSource.STORE,
        "unknown": KnowledgeSource.UNKNOWN,
    }
    candidates = sequence(raw) if is_sequence(raw) else (raw,)
    normalized = {
        aliases[value]
        for candidate in candidates
        if (value := text(candidate)) in aliases
    }
    if not normalized and inferred:
        normalized = set(inferred)
    if not normalized:
        normalized = {KnowledgeSource.UNKNOWN}
    if len(normalized) > 1:
        normalized.discard(KnowledgeSource.UNKNOWN)
    return tuple(sorted(normalized, key=lambda item: item.value))


def status(raw: object) -> KnowledgeStatus:
    value = text(raw)
    try:
        return KnowledgeStatus(value)
    except ValueError:
        return KnowledgeStatus.UNKNOWN


def knowledge_value(raw: object) -> KnowledgeValue:
    if raw is True:
        return KnowledgeValue.KNOWN_TRUE
    if raw is False:
        return KnowledgeValue.KNOWN_FALSE
    aliases = {
        "available": KnowledgeValue.KNOWN_TRUE,
        "known_true": KnowledgeValue.KNOWN_TRUE,
        "true": KnowledgeValue.KNOWN_TRUE,
        "known_false": KnowledgeValue.KNOWN_FALSE,
        "false": KnowledgeValue.KNOWN_FALSE,
        "unknown": KnowledgeValue.UNKNOWN,
        "unavailable": KnowledgeValue.UNAVAILABLE,
        "restricted": KnowledgeValue.RESTRICTED,
    }
    return aliases.get(text(raw), KnowledgeValue.UNKNOWN)


def online_value(explicit: object, connection: object) -> KnowledgeValue:
    normalized = knowledge_value(explicit)
    if normalized is not KnowledgeValue.UNKNOWN:
        return normalized
    value = text(connection)
    if value == "online":
        return KnowledgeValue.KNOWN_TRUE
    if value in {"offline", "disconnected", "degraded"}:
        return KnowledgeValue.KNOWN_FALSE
    return KnowledgeValue.UNKNOWN


def availability_from_online(online: KnowledgeValue) -> KnowledgeValue:
    if online is KnowledgeValue.KNOWN_TRUE:
        return KnowledgeValue.KNOWN_TRUE
    if online is KnowledgeValue.KNOWN_FALSE:
        return KnowledgeValue.KNOWN_FALSE
    return KnowledgeValue.UNKNOWN


def availability_from_status(value: KnowledgeStatus) -> KnowledgeValue:
    if value.value in _ONLINE_STATUSES:
        return KnowledgeValue.KNOWN_TRUE
    if value.value in _OFFLINE_STATUSES:
        return KnowledgeValue.KNOWN_FALSE
    if value is KnowledgeStatus.UNAVAILABLE:
        return KnowledgeValue.UNAVAILABLE
    if value is KnowledgeStatus.RESTRICTED:
        return KnowledgeValue.RESTRICTED
    return KnowledgeValue.UNKNOWN


def verified_value(
    raw: object,
    *,
    known: KnowledgeValue,
    verification_status: str,
) -> KnowledgeValue:
    if raw is False:
        return KnowledgeValue.KNOWN_FALSE
    if (
        raw is True
        and known is KnowledgeValue.KNOWN_TRUE
        and verification_status == "hardware_verified"
    ):
        return KnowledgeValue.KNOWN_TRUE
    return KnowledgeValue.UNKNOWN


def verification(raw: object) -> str:
    value = text(raw)
    return value if value in _KNOWN_VERIFICATION_STATUSES else "unknown"


def capability_state(
    capability_id: str,
    data: Mapping[str, Any],
    reported: Mapping[str, Any],
) -> JsonScalar:
    for key in ("state", "value", "on"):
        value = data.get(key)
        if key in data and is_json_scalar(value):
            return value
    value = reported.get(capability_id)
    if isinstance(value, Mapping):
        on = value.get("on")
        return on if is_json_scalar(on) else None
    if is_json_scalar(value):
        return value
    if capability_id.startswith("relay_"):
        relay_id = capability_id.removeprefix("relay_")
        relay_state = mapping(reported.get("relays")).get(relay_id)
        return relay_state if is_json_scalar(relay_state) else None
    return None


def safe_detail(data: Mapping[str, Any]) -> str | None:
    for key in ("detail", "reason", "message"):
        value = safe_text(data.get(key))
        if value is not None:
            return value
    return None


def safe_text(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    return "[redacted]" if _SECRET_TEXT.search(value) else value[:500]


def observation_timestamp(*values: object) -> str | None:
    for raw in values:
        if isinstance(raw, str) and raw:
            return raw
    return None


def identifier(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if not value or _SECRET_TEXT.search(value):
        return None
    return value[:100]


def text(raw: object) -> str:
    return raw.strip().lower() if isinstance(raw, str) else ""


def mapping(raw: object) -> Mapping[str, Any]:
    return raw if isinstance(raw, Mapping) else {}


def is_sequence(raw: object) -> bool:
    return isinstance(raw, Sequence) and not isinstance(
        raw,
        (str, bytes, bytearray),
    )


def sequence(raw: object) -> Sequence[object]:
    return raw if is_sequence(raw) else ()


def is_json_scalar(raw: object) -> bool:
    if isinstance(raw, float):
        return math.isfinite(raw)
    return raw is None or isinstance(raw, (str, int, bool))
