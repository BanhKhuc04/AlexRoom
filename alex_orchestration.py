from __future__ import annotations

import time
import threading
import uuid
from copy import deepcopy
from typing import Any

from alex_hardware import CommandService, TERMINAL_PHASES
from alex_store import AlexStore, utc_now


class MissionExecutor:
    """Sequential, auditable safe-action mission executor."""

    def __init__(self, store: AlexStore, commands: CommandService, timeout: float = 12.0) -> None:
        self.store = store
        self.commands = commands
        self.timeout = timeout

    def run(self, definition: dict[str, Any], origin: str = "system") -> dict[str, Any]:
        mission = {
            "mission_id": f"mission_{uuid.uuid4().hex}",
            "name": definition.get("name", "Mission"),
            "status": "running",
            "started_at": utc_now(),
            "completed_at": None,
            "steps": [],
            "source": definition.get("source", "local_software"),
        }
        self.store.put_record("mission_runs", mission["mission_id"], mission)
        successful = 0
        failed = 0
        for index, spec in enumerate(definition.get("steps", [])):
            step = {
                "index": index, "target": spec.get("target"), "action": spec.get("action"),
                "status": "running", "command_id": None, "failure_reason": None,
                "started_at": utc_now(), "completed_at": None,
            }
            mission["steps"].append(step)
            self.store.put_record("mission_runs", mission["mission_id"], mission)
            if spec.get("risk_level") == "restricted" or spec.get("target") != "test_led" or spec.get("action") != "set":
                step.update(status="failed", failure_reason="unsupported_or_restricted_action", completed_at=utc_now())
                failed += 1
                continue
            try:
                command = self.commands.create_test_led_command(bool(spec.get("value")), origin, mission["source"])
                step["command_id"] = command["command_id"]
                step["status"] = "waiting_ack"
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    current = self.commands.command(command["command_id"])
                    if current and current["phase"] in TERMINAL_PHASES:
                        break
                    time.sleep(0.02)
                current = self.commands.command(command["command_id"])
                if current and current["phase"] == "confirmed":
                    step["status"] = "confirmed"
                    successful += 1
                else:
                    step["status"] = "failed"
                    step["failure_reason"] = (current or {}).get("failure_reason", "mission_step_timeout")
                    failed += 1
            except RuntimeError as error:
                step.update(status="failed", failure_reason=str(error))
                failed += 1
            step["completed_at"] = utc_now()
            self.store.put_record("mission_runs", mission["mission_id"], mission)
        mission["completed_at"] = utc_now()
        if failed == 0:
            mission["status"] = "completed"
        elif successful > 0:
            mission["status"] = "partial"
        else:
            mission["status"] = "failed"
        self.store.put_record("mission_runs", mission["mission_id"], mission)
        self.store.add_audit("mission", f"{mission['mission_id']} {mission['status']}", "success" if mission["status"] == "completed" else "warning", mission["source"])
        return deepcopy(mission)


class AutomationExecutor:
    """Evaluates explicit safe rules; scheduling is driven by backend tick/manual events."""

    SUPPORTED_TRIGGERS = {"time", "device_state", "heartbeat_offline", "manual"}

    def __init__(self, store: AlexStore, missions: MissionExecutor, commands: CommandService) -> None:
        self.store = store
        self.missions = missions
        self.commands = commands

    def evaluate(self, rule: dict[str, Any], trigger: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        result = {"matched": False, "blocked_reason": None, "mission": None}
        trigger_type = str(trigger.get("type", ""))
        if not rule.get("enabled", False):
            result["blocked_reason"] = "rule_disabled"
        elif trigger_type not in self.SUPPORTED_TRIGGERS or rule.get("trigger", {}).get("type") != trigger_type:
            result["blocked_reason"] = "trigger_not_matched"
        elif any(action.get("risk_level") == "restricted" for action in rule.get("actions", []) if isinstance(action, dict)):
            result["blocked_reason"] = "restricted_action"
        elif not self._conditions_match(rule.get("conditions", [])):
            result["blocked_reason"] = "conditions_not_met"
        else:
            result["matched"] = True
            result["mission"] = self.missions.run({
                "name": f"Automation · {rule.get('name', 'rule')}",
                "steps": rule.get("actions", []),
                "source": rule.get("source", "local_software"),
            }, "automation")
        now = utc_now()
        updated = {**rule, "lastEvaluation": now, "lastRun": now if result["matched"] else rule.get("lastRun"),
                   "blockedReason": result["blocked_reason"], "result": (result["mission"] or {}).get("status"),
                   "duration": round((time.monotonic() - started) * 1000)}
        if rule.get("id"):
            self.store.put_record("automations", str(rule["id"]), {key: value for key, value in updated.items() if key not in {"id", "updated_at"}})
        return {**result, "evaluation": updated}

    def _conditions_match(self, conditions: list[Any]) -> bool:
        device = self.commands.device()
        for condition in conditions:
            if not isinstance(condition, dict):
                return False
            if condition.get("type") == "node_connection" and device["connection"] != condition.get("equals"):
                return False
            if condition.get("type") == "reported_state":
                actual = device["reported_state"].get(condition.get("target"), {}).get(condition.get("field"))
                if actual != condition.get("equals"):
                    return False
        return True


class AutomationScheduler:
    """Dispatches time/device/offline triggers without blocking MQTT callbacks."""

    def __init__(self, store: AlexStore, executor: AutomationExecutor, hub: Any) -> None:
        self.store = store
        self.executor = executor
        self.hub = hub
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_dispatch: dict[str, float] = {}
        self._time_runs: set[str] = set()

    def start(self) -> None:
        self._stop.clear()
        self.hub.add_listener(self._on_event)
        self._thread = threading.Thread(target=self._tick, name="alex-automation-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.hub.remove_listener(self._on_event)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _on_event(self, event: dict[str, Any]) -> None:
        mapping = {"reported_state": "device_state", "state_mismatch": "device_state", "node_offline": "heartbeat_offline"}
        trigger_type = mapping.get(event.get("type"))
        if trigger_type:
            threading.Thread(target=self.dispatch, args=({"type": trigger_type, "event": event},), daemon=True).start()

    def dispatch(self, trigger: dict[str, Any]) -> list[dict[str, Any]]:
        results = []
        now = time.monotonic()
        for rule in self.store.records("automations"):
            key = f"{rule['id']}:{trigger.get('type')}"
            if now - self._last_dispatch.get(key, 0) < 2:
                continue
            if rule.get("trigger", {}).get("type") != trigger.get("type"):
                continue
            self._last_dispatch[key] = now
            results.append(self.executor.evaluate(rule, trigger))
        return results

    def _tick(self) -> None:
        while not self._stop.wait(15):
            local = time.localtime()
            minute = time.strftime("%H:%M", local)
            day = time.strftime("%Y-%m-%d", local)
            for rule in self.store.records("automations"):
                trigger = rule.get("trigger", {})
                run_key = f"{rule['id']}:{day}:{minute}"
                if trigger.get("type") == "time" and trigger.get("at") == minute and run_key not in self._time_runs:
                    self._time_runs.add(run_key)
                    self.executor.evaluate(rule, {"type": "time", "at": minute})
            if len(self._time_runs) > 200:
                self._time_runs = {item for item in self._time_runs if f":{day}:" in item}
