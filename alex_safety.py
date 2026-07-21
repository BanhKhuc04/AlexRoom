from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from alex_hardware import CommandService


@dataclass(frozen=True)
class Capability:
    node_id: str
    capability_id: str
    risk_level: str
    supported_actions: frozenset[str]
    basic_physical_validation: bool
    hardware_verified: bool
    command_allowed: bool
    allowed_modes: frozenset[str]

    @property
    def verification_status(self) -> str:
        if self.hardware_verified:
            return "hardware_verified"
        if self.basic_physical_validation:
            return "basic_physical_validation"
        return "not_hardware_verified"


@dataclass(frozen=True)
class NodeCapabilities:
    node_id: str
    hardware_verified: bool
    capabilities: Mapping[str, Capability]


class CapabilityRegistry:
    """Server-authoritative capability truth, separate from whole-node status."""

    def __init__(self, nodes: Mapping[str, NodeCapabilities] | None = None) -> None:
        self._nodes = dict(nodes or self._default_nodes())

    @staticmethod
    def _default_nodes() -> dict[str, NodeCapabilities]:
        capabilities: dict[str, Capability] = {
            "test_led": Capability(
                node_id="esp01",
                capability_id="test_led",
                risk_level="safe",
                supported_actions=frozenset({"set"}),
                basic_physical_validation=True,
                hardware_verified=False,
                command_allowed=True,
                allowed_modes=frozenset({"hardware", "simulator"}),
            ),
        }
        for relay_id in range(1, 5):
            capability_id = f"relay_{relay_id}"
            capabilities[capability_id] = Capability(
                node_id="esp01",
                capability_id=capability_id,
                risk_level="restricted",
                supported_actions=frozenset({"on", "off"}),
                basic_physical_validation=False,
                hardware_verified=False,
                command_allowed=False,
                allowed_modes=frozenset(),
            )
        return {
            "esp01": NodeCapabilities(
                node_id="esp01",
                hardware_verified=False,
                capabilities=capabilities,
            ),
        }

    def node(self, node_id: str) -> NodeCapabilities | None:
        return self._nodes.get(node_id.lower())

    def capability(self, node_id: str, capability_id: str) -> Capability | None:
        node = self.node(node_id)
        return node.capabilities.get(capability_id.lower()) if node else None

    def public_snapshot(self) -> dict[str, Any]:
        return {
            node_id: {
                "node_id": node.node_id,
                "hardware_verified": node.hardware_verified,
                "capabilities": {
                    capability_id: {
                        **asdict(capability),
                        "supported_actions": sorted(capability.supported_actions),
                        "allowed_modes": sorted(capability.allowed_modes),
                        "verification_status": capability.verification_status,
                    }
                    for capability_id, capability in node.capabilities.items()
                },
            }
            for node_id, node in self._nodes.items()
        }


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str
    node_id: str
    capability_id: str
    action: str
    risk_level: str
    verification_status: str
    node_hardware_verified: bool
    execution_mode: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SafetyPolicy:
    """Final authorization policy. Client metadata is deliberately not accepted."""

    def __init__(self, registry: CapabilityRegistry, *, simulator_mode: bool) -> None:
        self.registry = registry
        self.execution_mode = "simulator" if simulator_mode else "hardware"

    def authorize(self, node_id: str, capability_id: str, action: str) -> SafetyDecision:
        normalized_node = node_id.lower()
        normalized_capability = capability_id.lower()
        normalized_action = action.lower()
        node = self.registry.node(normalized_node)
        if node is None:
            return self._denied(normalized_node, normalized_capability, normalized_action, "node_not_registered")
        capability = self.registry.capability(normalized_node, normalized_capability)
        if capability is None:
            return self._denied(
                normalized_node,
                normalized_capability,
                normalized_action,
                "capability_not_registered",
                node_hardware_verified=node.hardware_verified,
            )
        common = {
            "node_id": normalized_node,
            "capability_id": normalized_capability,
            "action": normalized_action,
            "risk_level": capability.risk_level,
            "verification_status": capability.verification_status,
            "node_hardware_verified": node.hardware_verified,
            "execution_mode": self.execution_mode,
        }
        if normalized_action not in capability.supported_actions:
            return SafetyDecision(False, "action_not_supported", **common)
        if capability.risk_level == "restricted":
            return SafetyDecision(False, "restricted_capability", **common)
        if not capability.command_allowed:
            return SafetyDecision(False, "command_not_allowed", **common)
        if not (capability.hardware_verified or capability.basic_physical_validation):
            return SafetyDecision(False, "capability_not_verified", **common)
        if self.execution_mode not in capability.allowed_modes:
            return SafetyDecision(False, "execution_mode_not_allowed", **common)
        return SafetyDecision(True, "authorized", **common)

    def _denied(
        self,
        node_id: str,
        capability_id: str,
        action: str,
        reason: str,
        *,
        node_hardware_verified: bool = False,
    ) -> SafetyDecision:
        return SafetyDecision(
            allowed=False,
            reason=reason,
            node_id=node_id,
            capability_id=capability_id,
            action=action,
            risk_level="unknown",
            verification_status="unknown",
            node_hardware_verified=node_hardware_verified,
            execution_mode=self.execution_mode,
        )


@dataclass(frozen=True)
class GatewayResult:
    decision: SafetyDecision
    command: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.decision.allowed,
            "decision": self.decision.as_dict(),
            "command": deepcopy(self.command),
        }


class CommandGateway:
    """The single runtime entry point for commands that can reach a device."""

    def __init__(self, policy: SafetyPolicy, command_service: CommandService) -> None:
        self.policy = policy
        self.command_service = command_service

    def request(
        self,
        *,
        node_id: str,
        capability_id: str,
        action: str,
        payload: Mapping[str, Any] | None = None,
        origin: str = "system",
    ) -> GatewayResult:
        decision = self.policy.authorize(node_id, capability_id, action)
        if not decision.allowed:
            return GatewayResult(decision)

        command_payload = dict(payload or {})
        if capability_id.lower() == "test_led" and action.lower() == "set":
            value = command_payload.get("value")
            if not isinstance(value, bool):
                return GatewayResult(
                    SafetyDecision(
                        **{**decision.as_dict(), "allowed": False, "reason": "invalid_boolean_payload"}
                    )
                )
            source = "simulated" if self.policy.execution_mode == "simulator" else "local_software"
            command = self.command_service._create_test_led_command(value, origin, source)
            return GatewayResult(decision, command)

        return GatewayResult(
            SafetyDecision(**{**decision.as_dict(), "allowed": False, "reason": "transport_not_implemented"})
        )

    def authorize_batch(self, requests: Iterable[tuple[str, str, str]]) -> list[SafetyDecision]:
        """Authorize a group before any execution, preventing partial relay-all behavior."""
        return [self.policy.authorize(node_id, capability_id, action) for node_id, capability_id, action in requests]

    def command(self, command_id: str) -> dict[str, Any] | None:
        return self.command_service.command(command_id)

    def device(self) -> dict[str, Any]:
        return self.command_service.device()

