from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from alex_hardware import CommandService, RealtimeHub
from alex_store import AlexStore


class EspDisconnectSemanticsTests(unittest.TestCase):
    def make_service(
        self,
        heartbeat_timeout: float = 45.0,
    ):
        temp = tempfile.TemporaryDirectory()

        store = AlexStore(
            Path(temp.name) / "alex.db"
        )
        store.migrate()

        service = CommandService(
            store,
            lambda topic, payload, qos, retain: True,
            RealtimeHub(),
            heartbeat_timeout=heartbeat_timeout,
        )

        return temp, service

    def heartbeat(self, service):
        return service.handle_heartbeat(
            {
                "protocolVersion": 1,
                "nodeId": "esp01",
                "online": True,
                "firmware": "1.0.2",
                "ip": "192.168.0.136",
                "rssi": -40,
            },
            "mqtt",
        )

    def test_transient_disconnect_becomes_degraded_not_offline(
        self,
    ) -> None:
        temp, service = self.make_service()

        with temp:
            self.assertTrue(
                self.heartbeat(service)
            )

            self.assertEqual(
                service.device()["connection"],
                "online",
            )

            service.mark_degraded()

            self.assertEqual(
                service.device()["connection"],
                "degraded",
            )

    def test_heartbeat_recovers_degraded_device(
        self,
    ) -> None:
        temp, service = self.make_service()

        with temp:
            self.heartbeat(service)
            service.mark_degraded()

            self.heartbeat(service)

            self.assertEqual(
                service.device()["connection"],
                "online",
            )

    def test_sustained_loss_becomes_offline(
        self,
    ) -> None:
        temp, service = self.make_service(
            heartbeat_timeout=0.05
        )

        with temp:
            # Giống lifecycle thật:
            # start service trước, heartbeat đến sau.
            service.start()

            try:
                self.heartbeat(service)

                self.assertEqual(
                    service.device()["connection"],
                    "online",
                )

                # MQTT Last Will / mất kết nối tạm thời.
                service.mark_degraded()

                self.assertEqual(
                    service.device()["connection"],
                    "degraded",
                )

                # Không có heartbeat mới:
                # watchdog phải chuyển degraded -> offline.
                deadline = time.monotonic() + 1.0

                while (
                    time.monotonic() < deadline
                    and service.device()["connection"]
                    != "offline"
                ):
                    time.sleep(0.02)

                self.assertEqual(
                    service.device()["connection"],
                    "offline",
                )

            finally:
                service.stop()


if __name__ == "__main__":
    unittest.main()
