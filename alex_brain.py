from __future__ import annotations

import re
import socket
import threading
import time
from copy import deepcopy
from typing import Callable

from alex_hardware import RealtimeHub
from alex_store import AlexStore, utc_now


class BrainService:
    """Wake-on-LAN preparation with bounded host verification."""

    def __init__(
        self,
        store: AlexStore,
        hub: RealtimeHub,
        mac: str | None,
        host: str | None,
        port: int = 22,
        timeout: float = 45,
        sender: Callable[[bytes], None] | None = None,
        probe: Callable[[], bool] | None = None,
    ) -> None:
        self.store = store
        self.hub = hub
        self.mac = mac
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sender = sender or self._send_packet
        self.probe = probe or self._probe
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = {
            "state": "offline", "requested_at": None, "confirmed_at": None,
            "failure_reason": None, "host": host, "hardware_verified": False,
        }

    def status(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def wake(self) -> dict:
        if not self.mac or not self.host:
            raise RuntimeError("brain_not_configured")
        packet = self.magic_packet(self.mac)
        with self._lock:
            if self._state["state"] == "waking":
                return deepcopy(self._state)
            self._state.update(state="waking", requested_at=utc_now(), confirmed_at=None, failure_reason=None)
        self.sender(packet)
        self.store.add_audit("brain", "Wake-on-LAN packet sent; waiting for host evidence", "info")
        self.hub.emit("brain_waking", self.status())
        self._thread = threading.Thread(target=self._verify, name="alex-brain-verify", daemon=True)
        self._thread.start()
        return self.status()

    def wait(self, timeout: float = 2) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    @staticmethod
    def magic_packet(mac: str) -> bytes:
        normalized = re.sub(r"[^0-9A-Fa-f]", "", mac)
        if len(normalized) != 12:
            raise ValueError("invalid_mac_address")
        return bytes.fromhex("FF" * 6 + normalized * 16)

    def _send_packet(self, packet: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            client.sendto(packet, ("255.255.255.255", 9))

    def _probe(self) -> bool:
        if not self.host:
            return False
        try:
            with socket.create_connection((self.host, self.port), timeout=1):
                return True
        except OSError:
            return False

    def _verify(self) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.probe():
                with self._lock:
                    self._state.update(state="online", confirmed_at=utc_now(), failure_reason=None)
                self.store.add_audit("brain", "ALEX Brain host became reachable", "success")
                self.hub.emit("brain_online", self.status())
                return
            time.sleep(min(2, self.timeout / 4))
        with self._lock:
            self._state.update(state="degraded", failure_reason="host_probe_timeout")
        self.store.add_audit("brain", "Wake-on-LAN host probe timed out", "warning")
        self.hub.emit("brain_wake_timeout", self.status())
