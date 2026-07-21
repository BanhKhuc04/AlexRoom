from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from alex_store import AlexStore, utc_now


PROTOCOL_VERSION = 1
NODE_ID = "esp01"
TOPIC_ROOT = f"alex/v1/nodes/{NODE_ID}"
COMMAND_TOPIC = f"{TOPIC_ROOT}/command"
ACK_TOPIC = f"{TOPIC_ROOT}/ack"
REPORTED_TOPIC = f"{TOPIC_ROOT}/reported"
HEARTBEAT_TOPIC = f"{TOPIC_ROOT}/heartbeat"
TELEMETRY_TOPIC = f"{TOPIC_ROOT}/telemetry"
STATUS_TOPIC = f"{TOPIC_ROOT}/status"

TERMINAL_PHASES = {"confirmed", "failed", "timed_out", "cancelled"}
LEGACY_VERIFICATION_FIELDS = {
    "capabilities", "risk_level", "basic_physical_validation",
    "verification_status", "hardware_verified",
}


def epoch_ms() -> int:
    return int(time.time() * 1000)


class RealtimeHub:
    """Thread-safe fan-out used by SSE clients and software integrations."""

    def __init__(self, history_size: int = 200) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self._listeners: set[Callable[[dict[str, Any]], None]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)

    def emit(self, event_type: str, data: dict[str, Any], source: str = "local_software") -> dict[str, Any]:
        event = {
            "id": f"evt_{uuid.uuid4().hex}",
            "type": event_type,
            "timestamp": utc_now(),
            "source": source,
            "data": deepcopy(data),
        }
        with self._lock:
            self._history.append(event)
            subscribers = tuple(self._subscribers)
            listeners = tuple(self._listeners)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except queue.Empty:
                    pass
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # Event delivery must never break MQTT/command processing.
                pass
        return event

    def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._listeners.add(listener)

    def remove_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._listeners.discard(listener)

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def history(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)[-max(1, min(limit, 200)):]


class CommandService:
    """Owns MQTT V1 command causality, digital twin and bounded retries."""

    def __init__(
        self,
        store: AlexStore,
        publisher: Callable[[str, str, int, bool], bool],
        hub: RealtimeHub,
        *,
        ack_timeout: float = 2.0,
        reported_timeout: float = 3.0,
        max_retries: int = 2,
        heartbeat_timeout: float = 45.0,
        simulator_mode: bool = False,
    ) -> None:
        self.store = store
        self.publisher = publisher
        self.hub = hub
        self.ack_timeout = ack_timeout
        self.reported_timeout = reported_timeout
        self.max_retries = max_retries
        self.heartbeat_timeout = heartbeat_timeout
        self.simulator_mode = simulator_mode
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._commands: dict[str, dict[str, Any]] = {}
        self._device = self._default_device()

    @staticmethod
    def _default_device() -> dict[str, Any]:
        return {
            "node_id": NODE_ID,
            "friendly_name": "ESP01 · Test LED",
            "firmware": None,
            "ip": None,
            "rssi": None,
            "last_seen_at": None,
            "connection": "unknown",
            "reported_state": {"test_led": {"on": False}},
            "desired_state": None,
            "current_command_id": None,
            "source": "mqtt",
        }

    def start(self) -> None:
        self.store.fail_pending_commands("backend_restarted")
        saved = self.store.get_device(NODE_ID)
        if saved:
            self._device.update(saved)
            self._device["connection"] = "unknown"
        for field in LEGACY_VERIFICATION_FIELDS:
            self._device.pop(field, None)
        self._stop.clear()
        self._worker = threading.Thread(target=self._watch, name="alex-command-watch", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)

    def device(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._device)

    def command(self, command_id: str) -> dict[str, Any] | None:
        with self._lock:
            command = self._commands.get(command_id)
        return deepcopy(command) if command else self.store.get_command(command_id)

    def recent_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.recent_commands(limit)

    def cancel(self, command_id: str) -> dict[str, Any] | None:
        with self._lock:
            command = self._commands.get(command_id)
            if command is None:
                return None
            if command["phase"] in TERMINAL_PHASES:
                return deepcopy(command)
            self._device["current_command_id"] = None
            self.store.put_device(self._device)
            self._transition(command, "cancelled", "command_cancelled", "cancelled_by_user")
            return deepcopy(command)

    def _create_test_led_command(self, value: bool, origin: str, source: str) -> dict[str, Any]:
        """Execute an authorized low-voltage command. Runtime callers use CommandGateway."""
        with self._lock:
            if self._device["connection"] != "online":
                raise RuntimeError("esp01_offline")
            now = utc_now()
            command_id = f"cmd_{uuid.uuid4().hex}"
            command = {
                "command_id": command_id,
                "node_id": NODE_ID,
                "target": "test_led",
                "action": "set",
                "desired_state": {"on": bool(value)},
                "reported_state": deepcopy(self._device["reported_state"].get("test_led")),
                "payload": {"value": bool(value)},
                "phase": "queued",
                "source": source,
                "origin": origin,
                "created_at": now,
                "requested_at": now,
                "sent_at": None,
                "acknowledged_at": None,
                "confirmed_at": None,
                "updated_at": now,
                "retry_count": 0,
                "failure_reason": None,
                "ack_status": None,
                "deadline": None,
            }
            self._commands[command_id] = command
            self._device["desired_state"] = {"test_led": {"on": bool(value)}}
            self._device["current_command_id"] = command_id
            self.store.put_device(self._device)
            self.store.put_command(command)
            self._transition(command, "queued", "command_created")
            self._send(command)
            return deepcopy(command)

    def _transition(self, command: dict[str, Any], phase: str, event_type: str, failure_reason: str | None = None) -> None:
        command["phase"] = phase
        command["updated_at"] = utc_now()
        if failure_reason:
            command["failure_reason"] = failure_reason
        self.store.put_command(command)
        self.store.add_command_event(command["command_id"], phase, event_type, command["source"], failure_reason)
        self.hub.emit(event_type, self._public_command(command), command["source"])

    def _send(self, command: dict[str, Any]) -> None:
        self._transition(command, "sending", "command_sending")
        payload = json.dumps({
            "protocolVersion": PROTOCOL_VERSION,
            "commandId": command["command_id"],
            "target": command["target"],
            "action": command["action"],
            "value": command["desired_state"]["on"],
            "timestamp": epoch_ms(),
            "source": command["source"],
        }, separators=(",", ":"))
        if not self.publisher(COMMAND_TOPIC, payload, 1, False):
            self._transition(command, "failed", "command_failed", "mqtt_publish_failed")
            return
        command["sent_at"] = utc_now()
        command["deadline"] = time.monotonic() + self.ack_timeout
        self._transition(command, "waiting_ack", "command_sent")

    def handle_ack(self, payload: dict[str, Any], source: str = "mqtt") -> bool:
        if source == "simulated" and not self.simulator_mode:
            return False
        if payload.get("protocolVersion") != PROTOCOL_VERSION or payload.get("nodeId") != NODE_ID:
            return False
        command_id = str(payload.get("commandId", ""))
        with self._lock:
            command = self._commands.get(command_id)
            if not command or command["phase"] in TERMINAL_PHASES:
                return False
            if (command["source"] == "simulated") != (source == "simulated"):
                return False
            if command["phase"] in {"accepted", "waiting_reported_state"}:
                return True
            if source == "simulated":
                command["source"] = "simulated"
            status = payload.get("status")
            if status not in {"accepted", "duplicate"}:
                self._transition(command, "failed", "command_failed", str(payload.get("reason", "device_rejected")))
                return True
            command["ack_status"] = status
            command["acknowledged_at"] = utc_now()
            self._transition(command, "accepted", "command_ack")
            command["deadline"] = time.monotonic() + self.reported_timeout
            self._transition(command, "waiting_reported_state", "command_waiting_reported")
            return True

    def handle_reported(self, payload: dict[str, Any], source: str = "mqtt") -> bool:
        if source == "simulated" and not self.simulator_mode:
            return False
        if payload.get("protocolVersion") != PROTOCOL_VERSION or payload.get("nodeId") != NODE_ID:
            return False
        if payload.get("target") != "test_led" or not isinstance(payload.get("state"), dict):
            return False
        command_id = str(payload.get("commandId", ""))
        reported = {"on": bool(payload["state"].get("on"))}
        with self._lock:
            self._device["reported_state"]["test_led"] = reported
            self._device["last_seen_at"] = utc_now()
            self._device["connection"] = "online"
            self._device["source"] = source
            command = self._commands.get(command_id)
            if not command:
                if command_id == "boot":
                    stale_desired = self._device.get("desired_state")
                    stale_on = stale_desired.get("test_led", {}).get("on") if stale_desired else None
                    if stale_on is not None and stale_on != reported["on"]:
                        old_desired = deepcopy(stale_desired)
                        self._device["desired_state"] = {"test_led": deepcopy(reported)}
                        self._device["current_command_id"] = None
                        self.store.put_device(self._device)
                        self.hub.emit("device_boot_safe_state_reconciliation", {
                            "node_id": NODE_ID,
                            "capability": "test_led",
                            "old_desired": old_desired,
                            "reported": reported,
                            "reason": "device_boot_safe_state_reconciliation",
                            "timestamp": utc_now()
                        }, source)
                    else:
                        self.store.put_device(self._device)
                else:
                    self.store.put_device(self._device)
                self.hub.emit("reported_state", {"node_id": NODE_ID, "target": "test_led", "state": reported}, source)
                return False
            if (command["source"] == "simulated") != (source == "simulated"):
                return False
            if source == "simulated":
                command["source"] = "simulated"
            command["reported_state"] = reported
            if command["phase"] not in {"accepted", "waiting_reported_state"}:
                return False
            if reported != command["desired_state"]:
                self._device["desired_state"] = {"test_led": deepcopy(command["desired_state"])}
                self._device["current_command_id"] = None
                self.store.put_device(self._device)
                self._transition(command, "failed", "state_mismatch", "reported_state_mismatch")
                return True
            command["confirmed_at"] = utc_now()
            self._device["desired_state"] = {"test_led": reported}
            self._device["current_command_id"] = None
            self.store.put_device(self._device)
            self._transition(command, "confirmed", "command_confirmed")
            return True

    def handle_heartbeat(self, payload: dict[str, Any], source: str = "mqtt") -> bool:
        if source == "simulated" and not self.simulator_mode:
            return False
        if payload.get("protocolVersion") != PROTOCOL_VERSION or payload.get("nodeId") != NODE_ID:
            return False
        now = utc_now()
        with self._lock:
            was_online = self._device["connection"] == "online"
            self._device.update({
                "firmware": payload.get("firmware"),
                "ip": payload.get("ip"),
                "rssi": payload.get("rssi"),
                "last_seen_at": now,
                "connection": "online" if payload.get("online") is True else "offline",
                "source": source,
                "last_seen_monotonic": time.monotonic(),
            })
            self.store.put_device(self._device)
            event_type = "heartbeat" if was_online else "node_online"
            self.hub.emit(event_type, self.device(), source)
            return True

    def mark_offline(self, source: str = "mqtt") -> None:
        with self._lock:
            if self._device["connection"] == "offline":
                return
            self._device["connection"] = "offline"
            self._device["source"] = source
            self.store.put_device(self._device)
            self.hub.emit("node_offline", self.device(), source)

    def mark_degraded(self, source: str = "mqtt") -> None:
        with self._lock:
            if self._device["connection"] != "online":
                return
            self._device["connection"] = "degraded"
            self._device["source"] = source
            self.store.put_device(self._device)
            self.hub.emit("node_degraded", self.device(), source)

    def _watch(self) -> None:
        while not self._stop.wait(0.05):
            now = time.monotonic()
            with self._lock:
                last_seen = self._device.get("last_seen_monotonic")
                if last_seen and self._device["connection"] in {"online", "degraded"} and now - float(last_seen) > self.heartbeat_timeout:
                    self.mark_offline(self._device.get("source", "mqtt"))
                for command in tuple(self._commands.values()):
                    deadline = command.get("deadline")
                    if not deadline or now < float(deadline) or command["phase"] in TERMINAL_PHASES:
                        continue
                    if command["phase"] == "waiting_ack" and command["retry_count"] < self.max_retries:
                        command["retry_count"] += 1
                        self._transition(command, "retrying", "command_retry")
                        self._send(command)
                    else:
                        reason = "ack_timeout" if command["phase"] == "waiting_ack" else "reported_state_timeout"
                        self._device["current_command_id"] = None
                        self.store.put_device(self._device)
                        self._transition(command, "timed_out", "command_timeout", reason)

    @staticmethod
    def _public_command(command: dict[str, Any]) -> dict[str, Any]:
        return {key: deepcopy(value) for key, value in command.items() if key != "deadline"}
