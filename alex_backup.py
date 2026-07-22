from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alex_store import AlexStore


class BackupService:
    """Create, describe, list, and retain consistent ALEX SQLite backups."""

    def __init__(
        self,
        store: AlexStore,
        backup_dir: Path,
        retention: int = 7,
    ) -> None:
        if retention < 1:
            raise ValueError(
                "Backup retention must be at least 1"
            )

        self.store = store
        self.backup_dir = Path(backup_dir)
        self.retention = retention

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
    def _metadata_path(
        database_path: Path,
    ) -> Path:
        return database_path.with_suffix(".json")

    def _write_metadata(
        self,
        path: Path,
        metadata: dict[str, Any],
    ) -> None:
        temporary = path.with_name(
            f".{path.name}.tmp"
        )

        temporary.write_text(
            json.dumps(
                metadata,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(path)

    def create(self) -> dict[str, Any]:
        self.backup_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        now = datetime.now(timezone.utc)

        stamp = now.strftime(
            "%Y%m%dT%H%M%S%fZ"
        )

        database_path = (
            self.backup_dir
            / f"alex-{stamp}.db"
        )

        self.store.backup(
            database_path
        )

        metadata = {
            "file": database_path.name,
            "metadata_file": (
                self._metadata_path(
                    database_path
                ).name
            ),
            "created_at": now.isoformat(),
            "size_bytes": (
                database_path.stat().st_size
            ),
            "sha256": self._sha256(
                database_path
            ),
            "integrity": "ok",
            "source_database": (
                self.store.path.name
            ),
        }

        metadata_path = (
            self._metadata_path(
                database_path
            )
        )

        self._write_metadata(
            metadata_path,
            metadata,
        )

        removed = self.prune()

        return {
            **metadata,
            "retention": self.retention,
            "retention_removed": removed,
        }

    def list_backups(
        self,
    ) -> list[dict[str, Any]]:
        if not self.backup_dir.exists():
            return []

        items: list[dict[str, Any]] = []

        database_files = sorted(
            self.backup_dir.glob(
                "alex-*.db"
            ),
            reverse=True,
        )

        for database_path in database_files:
            metadata_path = (
                self._metadata_path(
                    database_path
                )
            )

            if metadata_path.is_file():
                try:
                    metadata = json.loads(
                        metadata_path.read_text(
                            encoding="utf-8"
                        )
                    )

                    if isinstance(
                        metadata,
                        dict,
                    ):
                        items.append(
                            metadata
                        )
                        continue

                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    pass

            items.append(
                {
                    "file": database_path.name,
                    "metadata_file": (
                        metadata_path.name
                    ),
                    "size_bytes": (
                        database_path.stat().st_size
                    ),
                    "sha256": self._sha256(
                        database_path
                    ),
                    "integrity": "metadata_missing",
                }
            )

        return items

    def prune(
        self,
    ) -> list[str]:
        if not self.backup_dir.exists():
            return []

        backups = sorted(
            self.backup_dir.glob(
                "alex-*.db"
            ),
            reverse=True,
        )

        removed: list[str] = []

        for database_path in backups[
            self.retention :
        ]:
            metadata_path = (
                self._metadata_path(
                    database_path
                )
            )

            database_path.unlink(
                missing_ok=True
            )

            metadata_path.unlink(
                missing_ok=True
            )

            removed.append(
                database_path.name
            )

        return removed
