from __future__ import annotations

import unittest

from alex_brain_missions import StoredSafeMissionExecutor
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


class MissionRunnerSpy:
    def __init__(
        self,
        result: dict[str, object] | None = None,
    ) -> None:
        self.result = result or {
            "mission_id": "mission_run_spy",
            "status": "completed",
            "steps": [],
        }
        self.calls: list[tuple[dict[str, object], str]] = []

    def run(
        self,
        definition: dict[str, object],
        origin: str,
    ) -> dict[str, object]:
        self.calls.append((definition, origin))
        return self.result


def decision(
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

    def authorize_batch(
        self,
        requests,
    ) -> list[SafetyDecision]:
        batch = list(requests)
        self.batches.append(batch)
        return [
            decision(
                capability,
                action,
                allowed=not capability.startswith("relay_"),
            )
            for _, capability, action in batch
        ]


class StoredSafeMissionExecutorTests(unittest.TestCase):
    def execute(
        self,
        records: dict[str, dict[str, object]],
        mission_id: str = "safe-mission",
        *,
        runner_result: dict[str, object] | None = None,
    ):
        store = DictStore(records)
        runner = MissionRunnerSpy(runner_result)
        gateway = PreflightGatewaySpy()
        executor = StoredSafeMissionExecutor(store, runner, gateway)
        return executor.execute(mission_id), store, runner, gateway

    def test_missing_mission_is_rejected(self) -> None:
        outcome, store, runner, gateway = self.execute({})
        self.assertEqual(outcome.status, "rejected")
        self.assertEqual(outcome.reason, "mission_not_found")
        self.assertEqual(store.lookups, [("missions", "safe-mission")])
        self.assertEqual(runner.calls, [])
        self.assertEqual(gateway.batches, [])

    def test_brain_allowed_requires_exact_true(self) -> None:
        values = (False, None, "true", 1, "yes")
        for value in values:
            with self.subTest(value=value):
                record = {
                    "name": "Denied",
                    "steps": [
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
                    {"safe-mission": record}
                )
                self.assertEqual(
                    outcome.reason,
                    "mission_not_brain_allowed",
                )
                self.assertEqual(runner.calls, [])
                self.assertEqual(gateway.batches, [])

    def test_explicit_disabled_states_are_respected(self) -> None:
        disabled_variants = (
            {"enabled": False},
            {"enabled": "true"},
            {"active": False},
            {"disabled": True},
            {"status": "disabled"},
            {"status": "inactive"},
            {"enabled": True, "active": False},
            {"enabled": True, "disabled": True},
            {"enabled": True, "status": "disabled"},
            {"active": True, "disabled": True},
        )
        for variant in disabled_variants:
            with self.subTest(variant=variant):
                mission = {
                    "brain_allowed": True,
                    "steps": [
                        {
                            "target": "test_led",
                            "action": "set",
                            "value": True,
                        }
                    ],
                    **variant,
                }
                outcome, _, runner, gateway = self.execute(
                    {"safe-mission": mission}
                )
                self.assertEqual(outcome.reason, "mission_disabled")
                self.assertEqual(runner.calls, [])
                self.assertEqual(gateway.batches, [])

    def test_safe_test_led_only_mission_passes_complete_preflight(self) -> None:
        mission = {
            "name": "Safe",
            "brain_allowed": True,
            "steps": [
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
            {"safe-mission": mission}
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
        self.assertEqual(runner.calls, [(mission, "brain")])

    def test_relay_step_rejects_before_mission_executor(self) -> None:
        mission = {
            "brain_allowed": True,
            "steps": [
                {
                    "target": "test_led",
                    "action": "set",
                    "value": True,
                },
                {"target": "relay_1", "action": "on"},
            ],
        }
        outcome, _, runner, gateway = self.execute(
            {"safe-mission": mission}
        )
        self.assertEqual(outcome.status, "rejected")
        self.assertEqual(outcome.reason, "mission_preflight_failed")
        self.assertEqual(runner.calls, [])
        self.assertEqual(len(gateway.batches), 1)
        preflight = outcome.result["preflight"]
        self.assertEqual(preflight["denied_step_index"], 1)
        self.assertEqual(preflight["denied_capability"], "relay_1")
        self.assertEqual(
            preflight["reason"],
            "restricted_capability",
        )

    def test_malformed_or_non_boolean_steps_fail_before_executor(self) -> None:
        variants = (
            [],
            ["bad-step"],
            [
                {
                    "target": "test_led",
                    "action": "set",
                    "value": "true",
                }
            ],
            [
                {
                    "target": "test_led",
                    "action": "set",
                    "payload": {"value": True, "topic": "forbidden"},
                }
            ],
        )
        for steps in variants:
            with self.subTest(steps=steps):
                outcome, _, runner, _ = self.execute(
                    {
                        "safe-mission": {
                            "brain_allowed": True,
                            "steps": steps,
                        }
                    }
                )
                self.assertEqual(
                    outcome.reason,
                    "mission_preflight_failed",
                )
                self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
