from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UNCOMMITTED_VALUE = "UNCOMMITTED_SHOULD_ROLLBACK"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if os.name != "nt":
        os.chmod(path.parent, 0o700)

    temp = path.with_name(
        path.name + ".tmp"
    )

    with temp.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            payload,
            handle,
            indent=2,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    if os.name != "nt":
        os.chmod(temp, 0o600)

    temp.replace(path)


def reset_probe_files(
    database: Path,
    marker: Path,
) -> None:

    for path in (
        database,
        database.with_name(
            database.name + "-wal"
        ),
        database.with_name(
            database.name + "-shm"
        ),
        marker,
    ):
        path.unlink(
            missing_ok=True
        )


def arm_probe(
    database: Path,
    marker: Path,
    committed_rows: int = 20,
    reset: bool = False,
) -> sqlite3.Connection:

    if committed_rows < 1:
        raise ValueError(
            "committed_rows_must_be_positive"
        )

    database = database.expanduser().resolve()
    marker = marker.expanduser().resolve()

    database.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if os.name != "nt":
        os.chmod(
            database.parent,
            0o700,
        )

    if reset:
        reset_probe_files(
            database,
            marker,
        )

    connection = sqlite3.connect(
        database,
        timeout=10,
    )

    journal_mode = connection.execute(
        "PRAGMA journal_mode=WAL"
    ).fetchone()[0]

    connection.execute(
        "PRAGMA synchronous=FULL"
    )

    connection.execute(
        "PRAGMA wal_autocheckpoint=0"
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS powerloss_probe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    connection.commit()

    connection.execute(
        "DELETE FROM powerloss_probe"
    )

    connection.commit()

    for index in range(
        1,
        committed_rows + 1,
    ):
        connection.execute(
            """
            INSERT INTO powerloss_probe(
                state,
                created_at
            )
            VALUES (?, ?)
            """,
            (
                f"committed-{index}",
                utc_now(),
            ),
        )

        # Every row is intentionally durable before
        # moving to the next one.
        connection.commit()

    # Begin a transaction which must NOT survive
    # the simulated power loss.
    connection.execute(
        "BEGIN IMMEDIATE"
    )

    connection.execute(
        """
        INSERT INTO powerloss_probe(
            state,
            created_at
        )
        VALUES (?, ?)
        """,
        (
            UNCOMMITTED_VALUE,
            utc_now(),
        ),
    )

    marker_payload = {
        "armed": True,
        "database": str(database),
        "journal_mode": journal_mode,
        "synchronous": "FULL",
        "expected_committed_rows": (
            committed_rows
        ),
        "uncommitted_value": (
            UNCOMMITTED_VALUE
        ),
        "pid": os.getpid(),
        "armed_at": utc_now(),
    }

    write_json_atomic(
        marker,
        marker_payload,
    )

    return connection


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Arm an SQLite transaction for "
            "ALEX power-loss testing"
        )
    )

    parser.add_argument(
        "--database",
        default=(
            "/var/lib/alex/powerloss/"
            "probe.db"
        ),
    )

    parser.add_argument(
        "--marker",
        default=(
            "/var/lib/alex/powerloss/"
            "armed.json"
        ),
    )

    parser.add_argument(
        "--committed",
        type=int,
        default=20,
    )

    parser.add_argument(
        "--reset",
        action="store_true",
    )

    args = parser.parse_args()

    connection = None

    try:
        connection = arm_probe(
            database=Path(
                args.database
            ),
            marker=Path(
                args.marker
            ),
            committed_rows=(
                args.committed
            ),
            reset=args.reset,
        )

        print(
            "POWERLOSS_PROBE_ARMED "
            f"pid={os.getpid()} "
            f"committed={args.committed}",
            flush=True,
        )

        # Deliberately hold the uncommitted
        # transaction open until power disappears.
        while True:
            time.sleep(60)

    except KeyboardInterrupt:
        return 0

    finally:
        if connection is not None:
            # Normal shutdown rolls it back.
            # Dirty reboot will never reach here.
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
