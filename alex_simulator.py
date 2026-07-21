from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from alex_hardware import PROTOCOL_VERSION, NODE_ID, epoch_ms


class Esp01Simulator:
    """Explicit test_led simulator; all callbacks are tagged simulated."""

    VALID_SCENARIOS = {
        "normal", "delayed_ack", "missing_ack", "wrong_reported_state",
        "offline", "high_latency", "duplicate_message",
    }

    def __init__(
        self,
        on_heartbeat: Callable[[dict[str, Any], str], bool],
        on_ack: Callable[[dict[str, Any], str], bool],
        on_reported: Callable[[dict[str, Any], str], bool],
        *,
        scenario: str = "normal",
    ) -> None:
        self.on_heartbeat = on_heartbeat
        self.on_ack = on_ack
        self.on_reported = on_reported
        self.scenario = scenario if scenario in self.VALID_SCENARIOS else "normal"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._recent: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._state = False
        self.execution_count = 0

    def start(self) -> None:
        self._stop.clear()
        self._heartbeat()
        self._thread = threading.Thread(target=self._heartbeat_loop, name="esp01-simulator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def set_scenario(self, scenario: str) -> None:
        if scenario not in self.VALID_SCENARIOS:
            raise ValueError("unknown_simulator_scenario")
        self.scenario = scenario

    def publish(self, topic: str, raw: str, qos: int, retain: bool) -> bool:
        del topic, qos, retain
        if self.scenario == "offline":
            return False
        try:
            command = json.loads(raw)
        except json.JSONDecodeError:
            return False
        delay = 1.2 if self.scenario == "high_latency" else 0.35 if self.scenario == "delayed_ack" else 0.03
        threading.Timer(delay, self._handle, args=(command,)).start()
        return True

    def _handle(self, command: dict[str, Any]) -> None:
        command_id = str(command.get("commandId", ""))
        if command_id in self._recent:
            previous = self._recent[command_id]
            self.on_ack({**previous["ack"], "status": "duplicate", "timestamp": epoch_ms()}, "simulated")
            self.on_reported({**previous["reported"], "timestamp": epoch_ms()}, "simulated")
            return
        if self.scenario == "missing_ack":
            return
        ack = {
            "protocolVersion": PROTOCOL_VERSION, "commandId": command_id,
            "nodeId": NODE_ID, "status": "accepted", "timestamp": epoch_ms(),
        }
        self.on_ack(ack, "simulated")
        desired = bool(command.get("value"))
        reported_value = not desired if self.scenario == "wrong_reported_state" else desired
        self._state = reported_value
        self.execution_count += 1
        reported = {
            "protocolVersion": PROTOCOL_VERSION, "nodeId": NODE_ID,
            "target": "test_led", "state": {"on": reported_value},
            "commandId": command_id, "timestamp": epoch_ms(),
        }
        self._recent[command_id] = {"ack": ack, "reported": reported}
        while len(self._recent) > 12:
            self._recent.popitem(last=False)
        report_delay = 1.0 if self.scenario == "high_latency" else 0.04
        threading.Timer(report_delay, self.on_reported, args=(reported, "simulated")).start()
        if self.scenario == "duplicate_message":
            threading.Timer(report_delay + 0.02, self._handle, args=(command,)).start()

    def _heartbeat(self) -> None:
        if self.scenario == "offline":
            return
        self.on_heartbeat({
            "protocolVersion": PROTOCOL_VERSION, "nodeId": NODE_ID, "online": True,
            "uptime": int(time.monotonic()), "rssi": -42, "firmware": "sim-1.0.0",
            "ip": "simulated", "timestamp": epoch_ms(),
        }, "simulated")

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(5):
            self._heartbeat()

