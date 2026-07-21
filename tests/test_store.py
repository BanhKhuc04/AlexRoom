from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alex_store import AlexStore


class AlexStoreTests(unittest.TestCase):
    def test_migration_is_idempotent_and_records_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AlexStore(Path(directory) / "alex.db")
            store.migrate()
            store.migrate()
            self.assertEqual(store.health()["schema_version"], 2)
            store.put_record("scenes", "study", {"name": "Study", "safety_level": "safe"})
            self.assertEqual(store.records("scenes")[0]["name"], "Study")
            store.add_audit("test", "verified", "success")
            self.assertEqual(store.recent_audit(1)[0]["source"], "local_software")

    def test_command_source_and_backup_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AlexStore(root / "alex.db")
            store.migrate()
            store.put_command({
                "command_id": "cmd-1", "target": "demo", "action": "inspect",
                "payload": {}, "phase": "confirmed", "source": "simulated",
                "requested_at": "2026-01-01T00:00:00+00:00",
                "acknowledged_at": "2026-01-01T00:00:01+00:00", "failure_reason": None,
            })
            backup = store.backup(root / "backups" / "alex.db")
            self.assertTrue(backup.is_file())
            self.assertGreater(backup.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
