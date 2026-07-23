from __future__ import annotations

import unittest

from alex_brain_automations import StoredSafeAutomationExecutor
from alex_safety import SafetyDecision


class DictStore:
    def __init__(self, records: dict[str, dict[str, object]]) -> None:
        self.records = records
        self.lookups: list[tuple[str, str]] = []

    def get_record(
        self,
        domain: str,
        record_id: str,
    ) -> dict[str, object] | None:
        self.lookups.append((domain, record_id))
        return self.records.get(record_id)


class AutomationExecutorSpy:
    def __init__(
        self,
        result: dict[str, object] | None = None,
    ) -> None:
        self.result = result or {
            "matched": True,
            "blocked_reason": None,
            "mission": {
                "mission_id": "mission-spy",
                "status": "completed",
                "steps": [],
            },
        }
        self.calls: list[
            tuple[dict[str, object], dict[str, object]]
        ] = []

    def evaluate(
        self,
        rule: dict[str, object],
        trigger: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append((rule, trigger))
        return self.result


def safety_decision(
    capability: str,
    action: str,
    *,
    allowed: bool,
) -> SafetyDecision:
    return SafetyDecision(
        allowed=allowed,
        reason="authorized" if allowed else "restricted_capability",
        node_id="esp01",
        capability_id=capability,
        action=action,
        risk_level="safe" if allowed else "restricted",
        verification_status=(
            "basic_physical_validated" if allowed else "restricted"
        ),
        node_hardware_verified=False,
        execution_mode="simulator",
    )


class PreflightGatewaySpy:
    def __init__(self) -> None:
        self.batches: list[list[tuple[str, str, str]]] = []

    def authorize_batch(self, requests) -> list[SafetyDecision]:
        batch = list(requests)
        self.batches.append(batch)
        return [
            safety_decision(
                capability,
                action,
                allowed=not capability.startswith("relay_"),
            )
            for _, capability, action in batch
        ]


class StoredSafeAutomationExecutorTests(unittest.TestCase):
    def execute(
        self,
        records: dict[str, dict[str, object]],
        automation_id: str = "safe-automation",
        *,
        runner_result: dict[str, object] | None = None,
    ):
        store = DictStore(records)
        runner = AutomationExecutorSpy(runner_result)
        gateway = PreflightGatewaySpy()
        executor = StoredSafeAutomationExecutor(
            store,
            runner,
            gateway,
        )
        return executor.execute(automation_id), store, runner, gateway

    def test_missing_automation_is_rejected(self) -> None:
        outcome, store, runner, gateway = self.execute({})
        self.assertEqual(outcome.status, "rejected")
        self.assertEqual(outcome.reason, "automation_not_found")
        self.assertEqual(
            store.lookups,
            [("automations", "safe-automation")],
        )
        self.assertEqual(runner.calls, [])
        self.assertEqual(gateway.batches, [])

    def test_brain_allowed_requires_exact_true(self) -> None:
        for value in (False, None, "true", 1, "yes"):
            with self.subTest(value=value):
                record = {
                    "enabled": True,
                    "trigger": {"type": "manual"},
                    "actions": [
                        {
                            "target": "test_led",
                            "action": "set",
                            "value": True,
                        }
                    ],
                }
                if value is not None:
                    record["brain_allowed"] = value
                outcome, _, runner, gateway = self.execute(
                    {"safe-automation": record}
                )
                self.assertEqual(
                    outcome.reason,
                    "automation_not_brain_allowed",
                )
                self.assertEqual(
                    outcome.audit_events[-1].stage,
                    "automation_brain_allowed",
                )
                self.assertFalse(
                    outcome.audit_events[-1].details["allowed"]
                )
                self.assertEqual(runner.calls, [])
                self.assertEqual(gateway.batches, [])

    def test_existing_disabled_states_are_respected(self) -> None:
        variants = (
            {},
            {"enabled": False},
            {"enabled": "true"},
            {"enabled": True, "active": False},
            {"enabled": True, "disabled": True},
            {"enabled": True, "status": "disabled"},
            {"enabled": True, "status": "inactive"},
        )
        for variant in variants:
            with self.subTest(variant=variant):
                automation = {
                    "brain_allowed": True,
                    "trigger": {"type": "manual"},
                    "actions": [
                        {
                            "target": "test_led",
                            "action": "set",
                            "value": True,
                        }
                    ],
                    **variant,
                }
                outcome, _, runner, gateway = self.execute(
                    {"safe-automation": automation}
                )
                self.assertEqual(outcome.reason, "automation_disabled")
                self.assertEqual(runner.calls, [])
                self.assertEqual(gateway.batches, [])

    def test_safe_inline_actions_preflight_then_existing_executor(self) -> None:
        automation = {
            "id": "safe-automation",
            "name": "Safe",
            "brain_allowed": True,
            "enabled": True,
            "trigger": {"type": "manual"},
            "conditions": [],
            "actions": [
                {
                    "node_id": "esp01",
                    "target": "test_led",
                    "action": "set",
                    "value": True,
                },
                {
                    "node_id": "esp01",
                    "target": "test_led",
                    "action": "set",
                    "payload": {"value": False},
                },
            ],
        }
        outcome, _, runner, gateway = self.execute(
            {"safe-automation": automation}
        )
        self.assertEqual(outcome.status, "completed")
        self.assertIsNone(outcome.reason)
        self.assertEqual(
            gateway.batches,
            [
                [
                    ("esp01", "test_led", "set"),
                    ("esp01", "test_led", "set"),
                ]
            ],
        )
        self.assertEqual(
            runner.calls,
            [(automation, {"type": "manual"})],
        )
        self.assertEqual(
            [event.stage for event in outcome.audit_events[-2:]],
            [
                "automation_execution_start",
                "automation_execution_outcome",
            ],
        )

    def test_relay_rejects_before_existing_executor(self) -> None:
        automation = {
            "brain_allowed": True,
            "enabled": True,
            "trigger": {"type": "manual"},
            "actions": [
                {
                    "target": "test_led",
                    "action": "set",
                    "value": True,
                },
                {"target": "relay_1", "action": "on"},
            ],
        }
        outcome, _, runner, gateway = self.execute(
            {"safe-automation": automation}
        )
        self.assertEqual(outcome.status, "rejected")
        self.assertEqual(
            outcome.reason,
            "automation_preflight_failed",
        )
        self.assertEqual(runner.calls, [])
        self.assertEqual(len(gateway.batches), 1)
        preflight = outcome.result["preflight"]
        self.assertEqual(preflight["denied_step_index"], 1)
        self.assertEqual(preflight["denied_capability"], "relay_1")
        self.assertEqual(
            outcome.audit_events[-1].stage,
            "automation_preflight",
        )
        self.assertFalse(outcome.audit_events[-1].details["allowed"])

    def test_malformed_actions_fail_before_existing_executor(self) -> None:
        for actions in (
            [],
            ["bad-action"],
            [
                {
                    "target": "test_led",
                    "action": "set",
                    "value": "true",
                }
            ],
        ):
            with self.subTest(actions=actions):
                outcome, _, runner, _ = self.execute(
                    {
                        "safe-automation": {
                            "brain_allowed": True,
                            "enabled": True,
                            "trigger": {"type": "manual"},
                            "actions": actions,
                        }
                    }
                )
                self.assertEqual(
                    outcome.reason,
                    "automation_preflight_failed",
                )
                self.assertEqual(runner.calls, [])

    def test_authoritative_lifecycle_is_preserved(self) -> None:
        cases = (
            ("running", "running", None),
            ("pending", "pending", None),
            ("failed", "failed", "automation_execution_failed"),
        )
        for mission_status, expected, reason in cases:
            with self.subTest(mission_status=mission_status):
                outcome, _, _, _ = self.execute(
                    {
                        "safe-automation": {
                            "brain_allowed": True,
                            "enabled": True,
                            "trigger": {"type": "manual"},
                            "actions": [
                                {
                                    "target": "test_led",
                                    "action": "set",
                                    "value": True,
                                }
                            ],
                        }
                    },
                    runner_result={
                        "matched": True,
                        "blocked_reason": None,
                        "mission": {"status": mission_status},
                    },
                )
                self.assertEqual(outcome.status, expected)
                self.assertEqual(outcome.reason, reason)

    def test_trigger_or_condition_block_is_not_fake_success(self) -> None:
        outcome, _, _, _ = self.execute(
            {
                "safe-automation": {
                    "brain_allowed": True,
                    "enabled": True,
                    "trigger": {"type": "time"},
                    "actions": [
                        {
                            "target": "test_led",
                            "action": "set",
                            "value": True,
                        }
                    ],
                }
            },
            runner_result={
                "matched": False,
                "blocked_reason": "trigger_not_matched",
                "mission": None,
            },
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.reason, "automation_execution_failed")


if __name__ == "__main__":
    unittest.main()
