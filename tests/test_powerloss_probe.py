from pathlib import Path

from alex_powerloss_probe import (
    arm_probe,
)
from alex_powerloss_verify import (
    verify_probe,
)


def test_probe_has_durable_commits_but_hides_open_transaction(
    tmp_path: Path,
):
    database = tmp_path / "probe.db"
    marker = tmp_path / "armed.json"

    connection = arm_probe(
        database=database,
        marker=marker,
        committed_rows=5,
        reset=True,
    )

    try:
        result = verify_probe(
            database,
            marker,
        )

        assert result["passed"] is True
        assert (
            result["actual_committed_rows"]
            == 5
        )
        assert (
            result["uncommitted_rows"]
            == 0
        )

    finally:
        connection.rollback()
        connection.close()


def test_probe_reset_replaces_previous_run(
    tmp_path: Path,
):
    database = tmp_path / "probe.db"
    marker = tmp_path / "armed.json"

    first = arm_probe(
        database,
        marker,
        committed_rows=2,
        reset=True,
    )

    first.rollback()
    first.close()

    second = arm_probe(
        database,
        marker,
        committed_rows=4,
        reset=True,
    )

    try:
        result = verify_probe(
            database,
            marker,
        )

        assert (
            result["actual_committed_rows"]
            == 4
        )

    finally:
        second.rollback()
        second.close()
