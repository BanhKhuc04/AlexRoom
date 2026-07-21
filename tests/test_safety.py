from __future__ import annotations

import unittest

from alex_safety import Capability, CapabilityRegistry, CommandGateway, NodeCapabilities, SafetyPolicy


class FakeCommandService:
    def __init__(self) -> None:
        self.created: list[tuple[bool, str, str]] = []

    def _create_test_led_command(self, value: bool, origin: str, source: str) -> dict:
        self.created.append((value, origin, source))
        return {"command_id": "cmd_safe", "phase": "waiting_ack"}

    def command(self, command_id: str) -> dict:
        return {"command_id": command_id, "phase": "waiting_ack"}

    def device(self) -> dict:
        return {"connection": "online", "reported_state": {"test_led": {"on": False}}}


class CentralSafetyPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.service = FakeCommandService()
        self.policy = SafetyPolicy(self.registry, simulator_mode=False)
        self.gateway = CommandGateway(self.policy, self.service)

    def test_registry_separates_capability_validation_from_node_verification(self) -> None:
        node = self.registry.node("esp01")
        led = self.registry.capability("esp01", "test_led")
        self.assertIsNotNone(node)
        self.assertIsNotNone(led)
        self.assertEqual(node.verification_status, "basic_physical_validated")
        self.assertFalse(node.hardware_verified)
        self.assertEqual(led.verification_status, "basic_physical_validated")
        self.assertTrue(led.basic_physical_validation)
        self.assertFalse(led.hardware_verified)
        self.assertTrue(led.command_allowed)
        for relay_id in range(1, 5):
            relay = self.registry.capability("esp01", f"relay_{relay_id}")
            self.assertEqual(relay.risk_level, "restricted")
            self.assertEqual(relay.verification_status, "restricted")
            self.assertFalse(relay.hardware_verified)
            self.assertFalse(relay.command_allowed)

    def test_every_relay_on_and_off_is_denied_before_command_service(self) -> None:
        for relay_id in range(1, 5):
            for action in ("on", "off"):
                result = self.gateway.request(
                    node_id="esp01", capability_id=f"relay_{relay_id}",
                    action=action, payload={}, origin="test",
                )
                self.assertFalse(result.decision.allowed)
                self.assertEqual(result.decision.reason, "restricted_capability")
                self.assertEqual(result.decision.verification_status, "restricted")
        self.assertEqual(self.service.created, [])

    def test_client_risk_metadata_cannot_change_server_policy(self) -> None:
        client_payload = {"risk_level": "safe"}
        result = self.gateway.request(
            node_id="esp01", capability_id="relay_1", action="on",
            payload=client_payload, origin="untrusted_client",
        )
        self.assertFalse(result.decision.allowed)
        self.assertEqual(result.decision.risk_level, "restricted")
        self.assertEqual(self.service.created, [])

    def test_test_led_remains_authorized_after_basic_physical_validation(self) -> None:
        result = self.gateway.request(
            node_id="esp01", capability_id="test_led", action="set",
            payload={"value": True}, origin="test",
        )
        self.assertTrue(result.decision.allowed)
        self.assertEqual(result.decision.verification_status, "basic_physical_validated")
        self.assertFalse(result.decision.node_hardware_verified)
        self.assertEqual(self.service.created, [(True, "test", "local_software")])

    def test_policy_evaluates_registration_action_verification_permission_and_mode(self) -> None:
        self.assertEqual(self.policy.authorize("esp99", "test_led", "set").reason, "node_not_registered")
        self.assertEqual(self.policy.authorize("esp01", "missing", "set").reason, "capability_not_registered")
        self.assertEqual(self.policy.authorize("esp01", "test_led", "toggle").reason, "action_not_supported")

        def policy_for(capability: Capability, *, simulator_mode: bool = False) -> SafetyPolicy:
            node = NodeCapabilities("esp01", "software_verified", {capability.capability_id: capability})
            return SafetyPolicy(CapabilityRegistry({"esp01": node}), simulator_mode=simulator_mode)

        base = {
            "node_id": "esp01", "capability_id": "safe_output", "risk_level": "safe",
            "supported_actions": frozenset({"set"}),
        }
        unverified = Capability(
            **base, verification_status="software_verified", command_allowed=True,
            allowed_modes=frozenset({"hardware"}),
        )
        self.assertEqual(policy_for(unverified).authorize("esp01", "safe_output", "set").reason, "capability_not_verified")
        not_permitted = Capability(
            **base, verification_status="basic_physical_validated", command_allowed=False,
            allowed_modes=frozenset({"hardware"}),
        )
        self.assertEqual(policy_for(not_permitted).authorize("esp01", "safe_output", "set").reason, "command_not_allowed")
        hardware_only = Capability(
            **base, verification_status="basic_physical_validated", command_allowed=True,
            allowed_modes=frozenset({"hardware"}),
        )
        self.assertEqual(
            policy_for(hardware_only, simulator_mode=True).authorize("esp01", "safe_output", "set").reason,
            "execution_mode_not_allowed",
        )

    def test_simulator_mode_never_dispatches_legacy_relay_transport(self) -> None:
        simulator_service = FakeCommandService()
        gateway = CommandGateway(
            SafetyPolicy(self.registry, simulator_mode=True),
            simulator_service,
        )
        decisions = gateway.authorize_batch(
            ("esp01", f"relay_{relay_id}", "off") for relay_id in range(1, 5)
        )
        self.assertTrue(all(not decision.allowed for decision in decisions))
        self.assertEqual(simulator_service.created, [])

    def test_public_registry_snapshot_is_machine_readable(self) -> None:
        node = self.registry.get_node_status("esp01")
        self.assertEqual(node["verification_status"], "basic_physical_validated")
        self.assertFalse(node["hardware_verified"])
        self.assertEqual(node["capabilities"]["test_led"]["verification_status"], "basic_physical_validated")
        self.assertEqual(node["capabilities"]["relay_4"]["verification_status"], "restricted")

    def test_gateway_emits_structured_decision_for_every_denial(self) -> None:
        denied = []
        gateway = CommandGateway(self.policy, self.service, on_denied=denied.append)
        result = gateway.request(
            node_id="esp01", capability_id="relay_2", action="on", payload={}, origin="test",
        )
        self.assertFalse(result.decision.allowed)
        self.assertEqual(denied, [result.decision])


if __name__ == "__main__":
    unittest.main()
