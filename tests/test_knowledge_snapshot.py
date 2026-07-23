from __future__ import annotations

import json
import time
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from alex_knowledge import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeSource,
    KnowledgeStatus,
    KnowledgeValue,
    build_system_knowledge_snapshot,
    compact_system_knowledge,
)
from alex_safety import CapabilityRegistry


CAPTURED_AT = "2026-07-24T08:15:30+00:00"
OBSERVED_AT = "2026-07-24T08:14:00+00:00"


def canonical_devices() -> dict[str, object]:
    registry = CapabilityRegistry().public_snapshot()
    return {
        "items": [
            {
                **registry["esp01"],
                "connection": "online",
                "reported_state": {
                    "test_led": {"on": True},
                    "relays": {
                        "1": "OFF",
                        "2": "OFF",
                        "3": "OFF",
                        "4": "OFF",
                    },
                },
                "source": "mqtt",
            }
        ]
    }


def build_snapshot(**overrides: object):
    arguments = {
        "captured_at": CAPTURED_AT,
        "version": "0.8.0",
        "health_report": {
            "available": True,
            "stale": False,
            "status": "healthy",
            "report": {
                "status": "healthy",
                "checks": {
                    "backup": {
                        "status": "healthy",
                        "message": "backup_age",
                    },
                    "update": {
                        "status": "unknown",
                        "message": "update_state_unavailable",
                    },
                },
            },
        },
        "services": {
            "core": {
                "status": "active",
                "source": "core_runtime",
            },
            "brain": {
                "state": "unknown",
                "source": "core_runtime",
            },
        },
        "devices": canonical_devices(),
        "runtime": {
            "room_mode": "home",
            "simulator": False,
        },
    }
    arguments.update(overrides)
    return build_system_knowledge_snapshot(**arguments)


def test_snapshot_and_nested_contracts_are_immutable() -> None:
    snapshot = build_snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.version = "9.9.9"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.devices[0].online = KnowledgeValue.KNOWN_FALSE  # type: ignore[misc]
    assert isinstance(snapshot.devices, tuple)
    assert isinstance(snapshot.devices[0].capabilities, tuple)


def test_version_and_captured_at_are_preserved_exactly() -> None:
    snapshot = build_snapshot()
    assert KNOWLEDGE_SCHEMA_VERSION == 1
    assert snapshot.schema_version == 1
    assert snapshot.version == "0.8.0"
    assert snapshot.captured_at == CAPTURED_AT
    compact = snapshot.to_compact_dict()
    assert compact["schema_version"] == 1
    assert compact["version"] == "0.8.0"
    assert compact["captured_at"] == CAPTURED_AT


def test_caller_cannot_spoof_knowledge_schema_version() -> None:
    with pytest.raises(TypeError, match="schema_version"):
        build_system_knowledge_snapshot(  # type: ignore[call-arg]
            captured_at=CAPTURED_AT,
            version="0.8.0",
            schema_version=99,
        )


def test_service_observed_at_from_caller_is_preserved() -> None:
    snapshot = build_snapshot(
        services={
            "core": {
                "status": "online",
                "observed_at": OBSERVED_AT,
            }
        }
    )
    core = snapshot.services[1]
    assert core.observed_at == OBSERVED_AT
    assert snapshot.to_compact_dict()["services"]["core"]["observed_at"] == (
        OBSERVED_AT
    )


def test_device_and_dynamic_capability_observed_at_are_preserved() -> None:
    devices = canonical_devices()
    devices["items"][0]["observed_at"] = OBSERVED_AT  # type: ignore[index]
    snapshot = build_snapshot(devices=devices)
    device = snapshot.devices[0]
    led = next(
        capability
        for capability in device.capabilities
        if capability.capability_id == "test_led"
    )
    relay = next(
        capability
        for capability in device.capabilities
        if capability.capability_id == "relay_1"
    )
    assert device.observed_at == OBSERVED_AT
    assert led.state is True
    assert led.observed_at == OBSERVED_AT
    assert relay.state is None
    assert relay.observed_at is None


def test_device_uses_real_last_seen_timestamp_when_supplied() -> None:
    devices = canonical_devices()
    devices["items"][0]["last_seen_at"] = OBSERVED_AT  # type: ignore[index]
    assert build_snapshot(devices=devices).devices[0].observed_at == OBSERVED_AT


def test_maintenance_observed_at_from_caller_is_preserved() -> None:
    snapshot = build_snapshot(
        maintenance={
            "backup": {
                "status": "healthy",
                "observed_at": OBSERVED_AT,
            }
        }
    )
    backup = snapshot.maintenance[0]
    assert backup.observed_at == OBSERVED_AT
    assert snapshot.to_compact_dict()["maintenance"]["backup"][
        "observed_at"
    ] == OBSERVED_AT


def test_health_generated_at_is_a_real_maintenance_observation() -> None:
    snapshot = build_snapshot(
        health_report={
            "available": True,
            "stale": False,
            "status": "healthy",
            "report": {
                "generated_at": OBSERVED_AT,
                "status": "healthy",
                "checks": {
                    "backup": {"status": "healthy"},
                    "update": {"status": "unknown"},
                },
            },
        }
    )
    maintenance = {item.name: item for item in snapshot.maintenance}
    assert maintenance["health"].observed_at == OBSERVED_AT
    assert maintenance["backup"].observed_at == OBSERVED_AT
    assert maintenance["update"].observed_at == OBSERVED_AT


def test_runtime_observed_at_is_optional_and_preserved() -> None:
    runtime = build_snapshot(
        runtime={
            "room_mode": "home",
            "simulator": False,
            "observed_at": OBSERVED_AT,
        }
    ).runtime
    assert runtime.observed_at == OBSERVED_AT


def test_missing_observed_at_is_never_replaced_with_captured_at() -> None:
    snapshot = build_snapshot()
    assert snapshot.captured_at == CAPTURED_AT
    assert all(service.observed_at is None for service in snapshot.services)
    assert snapshot.devices[0].observed_at is None
    assert snapshot.runtime.observed_at is None
    assert all(
        maintenance.observed_at is None
        for maintenance in snapshot.maintenance
    )
    compact = snapshot.to_compact_dict()
    assert all(
        "observed_at" not in service
        for service in compact["services"].values()
    )
    assert all(
        "observed_at" not in device
        for device in compact["devices"].values()
    )
    assert all(
        "observed_at" not in maintenance
        for maintenance in compact["maintenance"].values()
    )
    assert "runtime" not in compact or "observed_at" not in compact["runtime"]


def test_builder_does_not_read_current_clock_for_observed_at() -> None:
    with (
        patch("time.time", side_effect=AssertionError("clock access")),
        patch(
            "datetime.datetime",
            side_effect=AssertionError("clock access"),
        ),
    ):
        snapshot = build_system_knowledge_snapshot(
            captured_at=CAPTURED_AT,
            version="0.8.0",
        )
    assert snapshot.runtime.observed_at is None


def test_stale_false_and_true_preserve_real_observation_time() -> None:
    snapshot = build_snapshot(
        services={
            "core": {
                "status": "online",
                "stale": False,
                "observed_at": OBSERVED_AT,
            }
        },
        maintenance={
            "backup": {
                "status": "warning",
                "stale": True,
                "observed_at": OBSERVED_AT,
            }
        },
    )
    core = snapshot.services[1]
    backup = snapshot.maintenance[0]
    assert core.stale is KnowledgeValue.KNOWN_FALSE
    assert core.observed_at == OBSERVED_AT
    assert backup.stale is KnowledgeValue.KNOWN_TRUE
    assert backup.observed_at == OBSERVED_AT


def test_unknown_stale_remains_unknown() -> None:
    snapshot = build_snapshot(
        services={
            "core": {
                "status": "online",
                "observed_at": OBSERVED_AT,
            }
        }
    )
    assert snapshot.services[1].stale is KnowledgeValue.UNKNOWN


def test_known_core_active_is_normalized() -> None:
    core = build_snapshot().services[1]
    assert core.name == "core"
    assert core.status is KnowledgeStatus.ACTIVE
    assert core.available is KnowledgeValue.KNOWN_TRUE
    assert core.sources == (KnowledgeSource.CORE_RUNTIME,)


def test_unknown_brain_does_not_become_online() -> None:
    brain = build_snapshot(services={"core": {"status": "active"}}).services[0]
    assert brain.name == "brain"
    assert brain.status is KnowledgeStatus.UNKNOWN
    assert brain.available is KnowledgeValue.UNKNOWN
    assert brain.sources == (KnowledgeSource.UNKNOWN,)


def test_hardware_verified_false_is_preserved() -> None:
    device = build_snapshot().devices[0]
    assert device.hardware_verified is KnowledgeValue.KNOWN_FALSE
    compact = build_snapshot().to_compact_dict()
    assert compact["devices"]["esp01"]["hardware_verified"] is False


def test_restricted_relay_is_not_normalized_as_off_or_available() -> None:
    snapshot = build_snapshot()
    relay = next(
        capability
        for capability in snapshot.devices[0].capabilities
        if capability.capability_id == "relay_1"
    )
    assert relay.availability is KnowledgeValue.RESTRICTED
    assert relay.command_allowed is KnowledgeValue.KNOWN_FALSE
    assert relay.state is None
    assert snapshot.to_compact_dict()["devices"]["esp01"]["capabilities"][
        "relay_1"
    ] == "restricted"


def test_known_test_led_capability_and_state_are_preserved() -> None:
    snapshot = build_snapshot()
    led = next(
        capability
        for capability in snapshot.devices[0].capabilities
        if capability.capability_id == "test_led"
    )
    assert led.availability is KnowledgeValue.KNOWN_TRUE
    assert led.verification_status == "basic_physical_validated"
    assert led.state is True


def test_unknown_device_cannot_become_hardware_verified() -> None:
    snapshot = build_snapshot(
        devices=[
            {
                "device_id": "mystery",
                "known": False,
                "hardware_verified": True,
                "verification_status": "hardware_verified",
            }
        ]
    )
    device = snapshot.devices[0]
    assert device.known is KnowledgeValue.KNOWN_FALSE
    assert device.hardware_verified is KnowledgeValue.UNKNOWN
    assert device.hardware_verified is not KnowledgeValue.KNOWN_TRUE


def test_backup_healthy_is_normalized_from_health_report() -> None:
    backup = build_snapshot().maintenance[0]
    assert backup.name == "backup"
    assert backup.status is KnowledgeStatus.HEALTHY
    assert backup.available is KnowledgeValue.KNOWN_TRUE
    assert backup.sources == (KnowledgeSource.HEALTH_REPORT,)


def test_unavailable_backup_never_fakes_healthy() -> None:
    snapshot = build_snapshot(
        maintenance={
            "backup": {
                "status": "healthy",
                "available": False,
                "message": "backup_reader_unavailable",
            }
        }
    )
    backup = snapshot.maintenance[0]
    assert backup.status is KnowledgeStatus.UNAVAILABLE
    assert backup.available is KnowledgeValue.KNOWN_FALSE


def test_unknown_update_remains_unknown() -> None:
    update = build_snapshot().maintenance[2]
    assert update.name == "update"
    assert update.status is KnowledgeStatus.UNKNOWN
    assert update.available is KnowledgeValue.UNKNOWN


def test_compact_representation_is_strict_json_serializable() -> None:
    document = compact_system_knowledge(build_snapshot())
    encoded = json.dumps(document, allow_nan=False)
    assert json.loads(encoded) == document


def test_compact_representation_is_deterministic() -> None:
    left = build_snapshot(
        services={
            "core": {"status": "active"},
            "brain": {"status": "offline"},
        }
    )
    right = build_snapshot(
        services={
            "brain": {"status": "offline"},
            "core": {"status": "active"},
        }
    )
    assert json.dumps(left.to_compact_dict()) == json.dumps(
        right.to_compact_dict()
    )


def test_compact_representation_excludes_secret_shaped_fields() -> None:
    secret = "NEVER_INCLUDE_THIS_VALUE"
    snapshot = build_snapshot(
        services={
            "core": {
                "status": "active",
                "token": secret,
                "authorization": f"Bearer {secret}",
                "detail": f"Authorization: Bearer {secret}",
            },
            "client_key": {"status": "online", "value": secret},
        },
        devices={
            "esp01": {
                **canonical_devices()["items"][0],  # type: ignore[index]
                "password": secret,
                "capabilities": {
                    **canonical_devices()["items"][0]["capabilities"],  # type: ignore[index]
                    "api_key": {"state": secret},
                },
            },
            "mqtt_password": {"hardware_verified": True},
        },
        maintenance={
            "backup": {
                "status": "healthy",
                "secret": secret,
            }
        },
    )
    encoded = json.dumps(snapshot.to_compact_dict()).lower()
    assert secret.lower() not in encoded
    for forbidden in (
        "client_key",
        "api_key",
        "mqtt_password",
        "authorization:",
    ):
        assert forbidden not in encoded


def test_builder_does_not_mutate_input_mappings_or_lists() -> None:
    services = {
        "brain": {
            "state": "unknown",
            "metadata": ["keep", {"token": "still-input-only"}],
        }
    }
    devices = canonical_devices()
    before = json.dumps(
        {"services": services, "devices": devices},
        sort_keys=True,
    )
    build_snapshot(services=services, devices=devices)
    after = json.dumps(
        {"services": services, "devices": devices},
        sort_keys=True,
    )
    assert after == before


def test_empty_inputs_produce_a_safe_snapshot() -> None:
    snapshot = build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
    )
    assert snapshot.overall_status is KnowledgeStatus.UNKNOWN
    assert snapshot.devices == ()
    assert [service.status for service in snapshot.services] == [
        KnowledgeStatus.UNKNOWN,
        KnowledgeStatus.UNKNOWN,
    ]
    assert all(
        item.status is KnowledgeStatus.UNKNOWN
        for item in snapshot.maintenance
    )


def test_malformed_optional_inputs_fail_safe_to_unknown() -> None:
    snapshot = build_system_knowledge_snapshot(
        captured_at=CAPTURED_AT,
        version="0.8.0",
        overall_status={"not": "a status"},
        health_report=["not", "a", "mapping"],
        services="online",
        devices=[None, 42, {"node_id": ""}],
        maintenance=object(),
        runtime={"simulator": "maybe", "room_mode": {"bad": "shape"}},
    )
    assert snapshot.overall_status is KnowledgeStatus.UNKNOWN
    assert snapshot.devices == ()
    assert snapshot.runtime.room_mode is None
    assert snapshot.runtime.simulator is KnowledgeValue.UNKNOWN


def test_builder_performs_no_network_mqtt_or_ollama_execution() -> None:
    with (
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("urllib.request.urlopen", side_effect=AssertionError("network")),
    ):
        snapshot = build_snapshot()
    assert snapshot.devices[0].device_id == "esp01"


def test_all_four_relay_safety_semantics_regression() -> None:
    snapshot = build_snapshot()
    capabilities = {
        capability.capability_id: capability
        for capability in snapshot.devices[0].capabilities
    }
    compact = snapshot.to_compact_dict()["devices"]["esp01"]["capabilities"]
    for relay_id in range(1, 5):
        relay = f"relay_{relay_id}"
        assert capabilities[relay].availability is KnowledgeValue.RESTRICTED
        assert capabilities[relay].hardware_verified is KnowledgeValue.KNOWN_FALSE
        assert capabilities[relay].command_allowed is KnowledgeValue.KNOWN_FALSE
        assert compact[relay] == "restricted"


def test_health_freshness_and_provenance_are_preserved() -> None:
    health = build_snapshot().maintenance[1]
    assert health.name == "health"
    assert health.stale is KnowledgeValue.KNOWN_FALSE
    assert health.sources == (KnowledgeSource.HEALTH_REPORT,)


def test_builder_handles_one_hundred_devices_without_external_dependencies() -> None:
    registry_node = CapabilityRegistry().public_snapshot()["esp01"]
    devices = {
        f"esp{index:03d}": {
            **registry_node,
            "node_id": f"esp{index:03d}",
            "connection": "online" if index % 2 == 0 else "offline",
        }
        for index in range(100)
    }
    started = time.perf_counter()
    snapshot = build_snapshot(devices=devices)
    elapsed = time.perf_counter() - started
    assert len(snapshot.devices) == 100
    assert elapsed < 2.0


def test_captured_at_and_version_require_explicit_strings() -> None:
    with pytest.raises(TypeError, match="captured_at"):
        build_system_knowledge_snapshot(  # type: ignore[arg-type]
            captured_at=None,
            version="0.8.0",
        )
    with pytest.raises(TypeError, match="version"):
        build_system_knowledge_snapshot(  # type: ignore[arg-type]
            captured_at=CAPTURED_AT,
            version=None,
        )
