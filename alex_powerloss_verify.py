from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from alex_powerloss_probe import (
    UNCOMMITTED_VALUE,
)


def verify_probe(
    database: Path,
    marker: Path,
) -> dict[str, Any]:

    database = (
        database.expanduser().resolve()
    )

    marker = (
        marker.expanduser().resolve()
    )

    if not database.is_file():
        return {
            "passed": False,
            "error": "probe_database_missing",
        }

    if not marker.is_file():
        return {
            "passed": False,
            "error": "probe_marker_missing",
        }

    marker_data = json.loads(
        marker.read_text(
            encoding="utf-8"
        )
    )

    expected = int(
        marker_data[
            "expected_committed_rows"
        ]
    )

    connection = sqlite3.connect(
        database,
        timeout=10,
    )

    try:
        quick = connection.execute(
            "PRAGMA quick_check"
        ).fetchone()[0]

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        committed = connection.execute(
            """
            SELECT COUNT(*)
            FROM powerloss_probe
            WHERE state LIKE 'committed-%'
            """
        ).fetchone()[0]

        uncommitted = connection.execute(
            """
            SELECT COUNT(*)
            FROM powerloss_probe
            WHERE state = ?
            """,
            (
                UNCOMMITTED_VALUE,
            ),
        ).fetchone()[0]

    finally:
        connection.close()

    passed = (
        quick == "ok"
        and integrity == "ok"
        and committed == expected
        and uncommitted == 0
    )

    return {
        "passed": passed,
        "quick_check": quick,
        "integrity_check": integrity,
        "expected_committed_rows": expected,
        "actual_committed_rows": committed,
        "uncommitted_rows": uncommitted,
    }


def main() -> int:
    parser = argparse.ArgumentParser()

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

    args = parser.parse_args()

    result = verify_probe(
        Path(args.database),
        Path(args.marker),
    )

    print(
        json.dumps(
            result,
            indent=2,
        ),
        flush=True,
    )

    return (
        0
        if result["passed"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
