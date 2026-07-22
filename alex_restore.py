from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alex_store import AlexStore


class RestoreService:
    """Validate and perform guarded offline SQLite restores."""

    def __init__(
        self,
        store: AlexStore,
        backup_dir: Path,
        rollback_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.backup_dir = Path(backup_dir)

        self.rollback_dir = (
            Path(rollback_dir)
            if rollback_dir is not None
            else self.store.path.parent / "restore-rollback"
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as stream:
            for chunk in iter(
                lambda: stream.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _quick_check(path: Path) -> None:
        db = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=5,
        )

        try:
            result = db.execute(
                "PRAGMA quick_check"
            ).fetchone()

        finally:
            db.close()

        if (
            result is None
            or str(result[0]).lower() != "ok"
        ):
            detail = (
                result[0]
                if result is not None
                else "no result"
            )

            raise RuntimeError(
                "SQLite integrity check failed: "
                f"{detail}"
            )

    def _resolve_backup(
        self,
        filename: str,
    ) -> Path:
        requested = Path(filename)

        if (
            requested.name != filename
            or requested.suffix != ".db"
            or not filename.startswith("alex-")
        ):
            raise ValueError(
                "Invalid backup filename"
            )

        path = (
            self.backup_dir
            / filename
        )

        if not path.is_file():
            raise FileNotFoundError(
                f"Backup not found: {filename}"
            )

        return path

    def validate(
        self,
        filename: str,
    ) -> dict[str, Any]:
        database_path = (
            self._resolve_backup(filename)
        )

        metadata_path = (
            database_path.with_suffix(".json")
        )

        if not metadata_path.is_file():
            raise RuntimeError(
                "Backup metadata is missing"
            )

        metadata = json.loads(
            metadata_path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(metadata, dict):
            raise RuntimeError(
                "Backup metadata is invalid"
            )

        if metadata.get("file") != filename:
            raise RuntimeError(
                "Backup metadata filename mismatch"
            )

        expected_hash = metadata.get(
            "sha256"
        )

        if not isinstance(
            expected_hash,
            str,
        ):
            raise RuntimeError(
                "Backup SHA256 metadata is missing"
            )

        actual_hash = self._sha256(
            database_path
        )

        if actual_hash != expected_hash:
            raise RuntimeError(
                "Backup SHA256 mismatch"
            )

        self._quick_check(
            database_path
        )

        return {
            **metadata,
            "validated": True,
            "actual_sha256": actual_hash,
        }

    @staticmethod
    def _copy_sqlite(
        source_path: Path,
        destination_path: Path,
    ) -> None:
        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination_path.unlink(
            missing_ok=True
        )

        source = sqlite3.connect(
            f"file:{source_path}?mode=ro",
            uri=True,
            timeout=5,
        )

        try:
            target = sqlite3.connect(
                destination_path,
                timeout=5,
            )

            try:
                source.backup(target)
                target.commit()

                result = target.execute(
                    "PRAGMA quick_check"
                ).fetchone()

                if (
                    result is None
                    or str(result[0]).lower()
                    != "ok"
                ):
                    raise RuntimeError(
                        "Restored temporary database "
                        "failed integrity check"
                    )

            finally:
                target.close()

        finally:
            source.close()

    def restore_rollback(
        self,
        filename: str,
        *,
        confirmation: str,
        service_stopped: bool,
    ) -> dict[str, Any]:
        if confirmation != "ROLLBACK":
            raise PermissionError(
                "Rollback confirmation must be ROLLBACK"
            )

        if not service_stopped:
            raise RuntimeError(
                "alex-core must be stopped before rollback"
            )

        requested = Path(filename)

        if (
            requested.name != filename
            or requested.suffix != ".db"
            or not filename.startswith("pre-restore-")
        ):
            raise ValueError(
                "Invalid rollback filename"
            )

        rollback_path = (
            self.rollback_dir
            / filename
        )

        if not rollback_path.is_file():
            raise FileNotFoundError(
                f"Rollback snapshot not found: {filename}"
            )

        self._quick_check(
            rollback_path
        )

        live_path = self.store.path

        temporary = live_path.with_name(
            f".{live_path.name}.rollback.tmp"
        )

        temporary.unlink(
            missing_ok=True
        )

        try:
            self._copy_sqlite(
                rollback_path,
                temporary,
            )

            temporary.replace(
                live_path
            )

            Path(
                str(live_path) + "-wal"
            ).unlink(
                missing_ok=True
            )

            Path(
                str(live_path) + "-shm"
            ).unlink(
                missing_ok=True
            )

            self._quick_check(
                live_path
            )

            health = self.store.health()

            if health.get("state") != "online":
                raise RuntimeError(
                    "Rollback database health check failed"
                )

        except Exception:
            temporary.unlink(
                missing_ok=True
            )
            raise

        return {
            "rolled_back": True,
            "rollback_file": filename,
            "integrity": "ok",
        }

    def restore(
        self,
        filename: str,
        *,
        confirmation: str,
        service_stopped: bool,
    ) -> dict[str, Any]:
        if confirmation != "RESTORE":
            raise PermissionError(
                "Restore confirmation must be RESTORE"
            )

        if not service_stopped:
            raise RuntimeError(
                "alex-core must be stopped before restore"
            )

        validated = self.validate(
            filename
        )

        source_path = (
            self.backup_dir
            / filename
        )

        live_path = self.store.path

        stamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%dT%H%M%SZ"
        )

        rollback_path = (
            self.rollback_dir
            / f"pre-restore-{stamp}.db"
        )

        self.rollback_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Preserve the current live database first.
        self.store.backup(
            rollback_path
        )

        temporary = live_path.with_name(
            f".{live_path.name}.restore.tmp"
        )

        replaced = False

        try:
            self._copy_sqlite(
                source_path,
                temporary,
            )

            temporary.replace(
                live_path
            )

            replaced = True

            # Prevent stale WAL/SHM files from an older
            # live database being associated with the
            # restored database.
            Path(
                str(live_path) + "-wal"
            ).unlink(
                missing_ok=True
            )

            Path(
                str(live_path) + "-shm"
            ).unlink(
                missing_ok=True
            )

            self._quick_check(
                live_path
            )

            health = self.store.health()

            if health.get("state") != "online":
                raise RuntimeError(
                    "Restored database health check failed"
                )

        except Exception as error:
            temporary.unlink(
                missing_ok=True
            )

            if replaced:
                rollback_temp = (
                    live_path.with_name(
                        f".{live_path.name}.rollback.tmp"
                    )
                )

                self._copy_sqlite(
                    rollback_path,
                    rollback_temp,
                )

                rollback_temp.replace(
                    live_path
                )

                Path(
                    str(live_path) + "-wal"
                ).unlink(
                    missing_ok=True
                )

                Path(
                    str(live_path) + "-shm"
                ).unlink(
                    missing_ok=True
                )

            raise RuntimeError(
                "Restore failed; rollback snapshot preserved"
            ) from error

        return {
            "restored": True,
            "file": filename,
            "sha256": validated[
                "actual_sha256"
            ],
            "rollback_file": (
                rollback_path.name
            ),
            "integrity": "ok",
        }
