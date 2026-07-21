from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AlexStore:
    """Small SQLite boundary for durable MARK III domain and audit data."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def session(self):
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.session() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                  kind TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL,
                  source TEXT NOT NULL DEFAULT 'local_software',
                  detail_json TEXT
                );
                CREATE TABLE IF NOT EXISTS commands (
                  command_id TEXT PRIMARY KEY, target TEXT NOT NULL, action TEXT NOT NULL,
                  payload_json TEXT NOT NULL, phase TEXT NOT NULL, source TEXT NOT NULL,
                  requested_at TEXT NOT NULL, acknowledged_at TEXT, failure_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS domain_records (
                  domain TEXT NOT NULL, record_id TEXT NOT NULL, body_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL, PRIMARY KEY(domain, record_id)
                );
                CREATE TABLE IF NOT EXISTS command_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  command_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  phase TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  source TEXT NOT NULL,
                  detail TEXT
                );
                CREATE TABLE IF NOT EXISTS device_registry (
                  node_id TEXT PRIMARY KEY,
                  body_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            existing = {row[1] for row in db.execute("PRAGMA table_info(commands)").fetchall()}
            additions = {
                "node_id": "TEXT",
                "desired_json": "TEXT",
                "reported_json": "TEXT",
                "created_at": "TEXT",
                "sent_at": "TEXT",
                "confirmed_at": "TEXT",
                "updated_at": "TEXT",
                "retry_count": "INTEGER NOT NULL DEFAULT 0",
                "origin": "TEXT NOT NULL DEFAULT 'system'",
                "ack_status": "TEXT",
            }
            for column, definition in additions.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE commands ADD COLUMN {column} {definition}")
            audit_columns = {row[1] for row in db.execute("PRAGMA table_info(audit_events)").fetchall()}
            if "detail_json" not in audit_columns:
                db.execute("ALTER TABLE audit_events ADD COLUMN detail_json TEXT")
            db.execute(
                "INSERT INTO metadata(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def add_audit(
        self,
        kind: str,
        message: str,
        level: str,
        source: str = "local_software",
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self.session() as db:
            db.execute(
                "INSERT INTO audit_events(created_at,kind,level,message,source,detail_json) VALUES(?,?,?,?,?,?)",
                (utc_now(), kind, level, message, source, json.dumps(details, ensure_ascii=False) if details else None),
            )

    def recent_audit(self, limit: int = 80) -> list[dict[str, Any]]:
        bounded = max(1, min(200, limit))
        with self._lock, self.session() as db:
            rows = db.execute(
                "SELECT created_at,kind,level,message,source,detail_json FROM audit_events ORDER BY id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return [
            {
                "created_at": row["created_at"],
                "kind": row["kind"],
                "level": row["level"],
                "message": row["message"],
                "source": row["source"],
                "details": json.loads(row["detail_json"]) if row["detail_json"] else None,
            }
            for row in rows
        ]

    def put_record(self, domain: str, record_id: str, body: dict[str, Any]) -> None:
        with self._lock, self.session() as db:
            db.execute(
                "INSERT INTO domain_records(domain,record_id,body_json,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(domain,record_id) DO UPDATE SET body_json=excluded.body_json,updated_at=excluded.updated_at",
                (domain, record_id, json.dumps(body, ensure_ascii=False), utc_now()),
            )

    def records(self, domain: str) -> list[dict[str, Any]]:
        with self._lock, self.session() as db:
            rows = db.execute(
                "SELECT record_id,body_json,updated_at FROM domain_records WHERE domain=? ORDER BY record_id",
                (domain,),
            ).fetchall()
        return [{"id": row["record_id"], **json.loads(row["body_json"]), "updated_at": row["updated_at"]} for row in rows]

    def get_record(self, domain: str, record_id: str) -> dict[str, Any] | None:
        with self._lock, self.session() as db:
            row = db.execute(
                "SELECT body_json,updated_at FROM domain_records WHERE domain=? AND record_id=?",
                (domain, record_id),
            ).fetchone()
        return {"id": record_id, **json.loads(row["body_json"]), "updated_at": row["updated_at"]} if row else None

    def put_command(self, command: dict[str, Any]) -> None:
        with self._lock, self.session() as db:
            db.execute(
                """INSERT INTO commands(
                  command_id,target,action,payload_json,phase,source,requested_at,acknowledged_at,failure_reason,
                  node_id,desired_json,reported_json,created_at,sent_at,confirmed_at,updated_at,retry_count,origin,ack_status
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(command_id) DO UPDATE SET
                  phase=excluded.phase, payload_json=excluded.payload_json,
                  source=excluded.source,
                  acknowledged_at=excluded.acknowledged_at, failure_reason=excluded.failure_reason,
                  desired_json=excluded.desired_json, reported_json=excluded.reported_json,
                  sent_at=excluded.sent_at, confirmed_at=excluded.confirmed_at,
                  updated_at=excluded.updated_at, retry_count=excluded.retry_count,
                  ack_status=excluded.ack_status""",
                (
                    command["command_id"], command["target"], command["action"],
                    json.dumps(command.get("payload", {}), ensure_ascii=False), command["phase"],
                    command["source"], command["requested_at"], command.get("acknowledged_at"),
                    command.get("failure_reason"),
                    command.get("node_id"), json.dumps(command.get("desired_state"), ensure_ascii=False),
                    json.dumps(command.get("reported_state"), ensure_ascii=False),
                    command.get("created_at", command["requested_at"]), command.get("sent_at"),
                    command.get("confirmed_at"), command.get("updated_at", command["requested_at"]),
                    int(command.get("retry_count", 0)), command.get("origin", "system"),
                    command.get("ack_status"),
                ),
            )

    @staticmethod
    def _command_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "command_id": row["command_id"], "node_id": row["node_id"],
            "target": row["target"], "action": row["action"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "desired_state": json.loads(row["desired_json"] or "null"),
            "reported_state": json.loads(row["reported_json"] or "null"),
            "phase": row["phase"], "source": row["source"], "origin": row["origin"],
            "created_at": row["created_at"], "requested_at": row["requested_at"],
            "sent_at": row["sent_at"], "acknowledged_at": row["acknowledged_at"],
            "confirmed_at": row["confirmed_at"], "updated_at": row["updated_at"],
            "retry_count": row["retry_count"], "failure_reason": row["failure_reason"],
            "ack_status": row["ack_status"],
        }

    def get_command(self, command_id: str) -> dict[str, Any] | None:
        with self._lock, self.session() as db:
            row = db.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
        return self._command_from_row(row) if row else None

    def recent_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 200))
        with self._lock, self.session() as db:
            rows = db.execute("SELECT * FROM commands ORDER BY COALESCE(created_at,requested_at) DESC LIMIT ?", (bounded,)).fetchall()
        return [self._command_from_row(row) for row in rows]

    def add_command_event(self, command_id: str, phase: str, event_type: str, source: str, detail: str | None = None) -> None:
        with self._lock, self.session() as db:
            db.execute(
                "INSERT INTO command_events(command_id,created_at,phase,event_type,source,detail) VALUES(?,?,?,?,?,?)",
                (command_id, utc_now(), phase, event_type, source, detail),
            )

    def command_events(self, command_id: str) -> list[dict[str, Any]]:
        with self._lock, self.session() as db:
            rows = db.execute(
                "SELECT created_at,phase,event_type,source,detail FROM command_events WHERE command_id=? ORDER BY id",
                (command_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fail_pending_commands(self, reason: str) -> int:
        with self._lock, self.session() as db:
            cursor = db.execute(
                "UPDATE commands SET phase='failed',failure_reason=?,updated_at=? WHERE phase NOT IN ('confirmed','failed','timed_out','cancelled')",
                (reason, utc_now()),
            )
        return cursor.rowcount

    def put_device(self, device: dict[str, Any]) -> None:
        durable = {key: value for key, value in device.items() if key != "last_seen_monotonic"}
        with self._lock, self.session() as db:
            db.execute(
                "INSERT INTO device_registry(node_id,body_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(node_id) DO UPDATE SET body_json=excluded.body_json,updated_at=excluded.updated_at",
                (device["node_id"], json.dumps(durable, ensure_ascii=False), utc_now()),
            )

    def get_device(self, node_id: str) -> dict[str, Any] | None:
        with self._lock, self.session() as db:
            row = db.execute("SELECT body_json FROM device_registry WHERE node_id=?", (node_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def backup(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            shutil.copy2(self.path, destination)
        return destination

    def health(self) -> dict[str, Any]:
        with self._lock, self.session() as db:
            version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            db.execute("SELECT 1").fetchone()
        return {"state": "online", "schema_version": int(version[0]) if version else 0, "path": self.path.name}
