from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"

START_MARKER = "<!-- ALEX:CURRENT-STATUS:START -->"
END_MARKER = "<!-- ALEX:CURRENT-STATUS:END -->"

TARGET_NAMES = (
    "PROJECT_PROGRESS_AND_ROADMAP.md",
    "IMPLEMENTATION_STATUS.md",
    "FINAL_REPORT.md",
    "HARDWARE_V1_SUMMARY.md",
    "RELEASE_NOTES.md",
    "DEPLOYMENT.md",
    "README.md",
)

CANONICAL_STATUS_FILE = (
    REPO_ROOT / "docs" / "CURRENT_PROJECT_STATUS.md"
)


def read_version() -> str:
    if not VERSION_FILE.exists():
        raise RuntimeError(
            "Canonical VERSION file is missing"
        )

    version = VERSION_FILE.read_text(
        encoding="utf-8-sig"
    ).strip()

    if not re.fullmatch(
        r"(0|[1-9]\d*)\."
        r"(0|[1-9]\d*)\."
        r"(0|[1-9]\d*)"
        r"(?:-[0-9A-Za-z-]+"
        r"(?:\.[0-9A-Za-z-]+)*)?"
        r"(?:\+[0-9A-Za-z-]+"
        r"(?:\.[0-9A-Za-z-]+)*)?",
        version,
    ):
        raise RuntimeError(
            f"Invalid canonical version: {version}"
        )

    return version


def find_target_docs() -> list[Path]:
    candidates: list[Path] = []

    for name in TARGET_NAMES:
        for path in (
            REPO_ROOT / name,
            REPO_ROOT / "docs" / name,
        ):
            if path.exists() and path.is_file():
                candidates.append(path)

    return list(dict.fromkeys(candidates))


def build_status_block(version: str) -> str:
    return f"""{START_MARKER}
## Current verified project status

> This block is managed by `scripts/sync_project_docs.py`.

- ALEX Core version: `{version}`
- Production platform: Orange Pi
- Production service: `alex-core.service`
- Automatic Core updater: `alex-update.timer`
- Backend: FastAPI
- Database: SQLite
- Realtime transport: SSE + MQTT
- MQTT broker: Mosquitto with authentication and ACL
- Production MQTT state: connected
- ESP01 hardware node: online
- ESP01 communication: command + ACK + reported state + heartbeat
- ESP01 physical onboard LED control: hardware verified
- Simulator in production: disabled
- API health: online
- Release pipeline:
  - Semantic Version calculation
  - Release notes generation
  - Canonical version synchronization
  - Full quality gate
  - Safe ZIP packaging
  - SHA256 generation
  - Annotated Git tag
  - GitHub Release publishing
- Release preparation:
  - One-click `ALEX Prepare Release`
  - Automatically calculates next version
  - Updates `VERSION`, `package.json`, `package-lock.json`, and `CHANGELOG.md`
  - Runs quality gates
  - Creates and pushes `chore(release): vX.Y.Z`
  - Does **not** publish a tag or GitHub Release
- Release publication:
  - Manual `ALEX Release`
  - Requires `mode=publish`
  - Requires confirmation `RELEASE`
- Current production release: `v{version}`

### Verified production chain

~~~text
Windows development
→ GitHub
→ CI
→ Orange Pi automatic update
→ alex-core restart
→ health verification
→ MQTT
→ ESP01 hardware
~~~

### Release chain

~~~text
Code changes
→ ALEX Prepare Release
→ release commit
→ production verification
→ ALEX Release
→ annotated tag
→ ZIP
→ SHA256
→ GitHub Release
~~~

### Safety state

- Relay outputs remain restricted until hardware safety interlocks are completed.
- No unrestricted mains-voltage control is considered production-ready.
- LLM/AI components must not publish directly to MQTT; ALEX Core remains the authority boundary.

{END_MARKER}
"""


def build_canonical_status_document(
    version: str,
) -> str:
    return (
        "# ALEX Current Project Status\n\n"
        f"Canonical Core version: `{version}`\n\n"
        + build_status_block(version)
        + "\n"
    )


def inject_status_block(
    original: str,
    block: str,
) -> str:
    text = original.lstrip("\ufeff")

    start_count = text.count(START_MARKER)
    end_count = text.count(END_MARKER)

    if start_count != end_count:
        raise RuntimeError(
            "Document contains unmatched status markers"
        )

    if start_count > 1:
        raise RuntimeError(
            "Document contains duplicate managed status blocks"
        )

    if start_count == 1:
        start = text.index(START_MARKER)

        end = (
            text.index(
                END_MARKER,
                start,
            )
            + len(END_MARKER)
        )

        before = text[:start].rstrip()
        after = text[end:].lstrip()

        parts = [
            part
            for part in (
                before,
                block,
                after,
            )
            if part
        ]

        return (
            "\n\n".join(parts).rstrip()
            + "\n"
        )

    heading = re.search(
        r"(?m)^# .+$",
        text,
    )

    if heading:
        line_end = text.find(
            "\n",
            heading.end(),
        )

        if line_end == -1:
            line_end = len(text)

        before = text[:line_end].rstrip()
        after = text[line_end:].lstrip()

        parts = [
            part
            for part in (
                before,
                block,
                after,
            )
            if part
        ]

        return (
            "\n\n".join(parts).rstrip()
            + "\n"
        )

    parts = [
        part
        for part in (
            block,
            text.lstrip(),
        )
        if part
    ]

    return (
        "\n\n".join(parts).rstrip()
        + "\n"
    )


def collect_changes(
    version: str,
) -> dict[Path, str]:
    changes: dict[Path, str] = {}

    canonical = (
        build_canonical_status_document(
            version
        )
    )

    existing_canonical = (
        CANONICAL_STATUS_FILE.read_text(
            encoding="utf-8-sig"
        )
        if CANONICAL_STATUS_FILE.exists()
        else None
    )

    if existing_canonical != canonical:
        changes[
            CANONICAL_STATUS_FILE
        ] = canonical

    block = build_status_block(version)

    for path in find_target_docs():
        original = path.read_text(
            encoding="utf-8-sig"
        )

        updated = inject_status_block(
            original,
            block,
        )

        if (
            updated
            != original.lstrip("\ufeff")
        ):
            changes[path] = updated

    return changes


def write_changes(
    changes: dict[Path, str],
) -> None:
    for path, content in changes.items():
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize verified current ALEX "
            "project status into managed "
            "documentation blocks."
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write documentation changes.",
    )

    args = parser.parse_args()

    try:
        version = read_version()
        targets = find_target_docs()
        changes = collect_changes(version)

        print("ALEX DOCUMENTATION SYNC")
        print(
            f"Canonical version : {version}"
        )

        print(
            "Mode              : "
            + (
                "apply"
                if args.apply
                else "dry-run"
            )
        )

        print(
            f"Target docs found : "
            f"{len(targets)}"
        )

        if not changes:
            print(
                "Documents already synchronized."
            )
            return 0

        print("Files to update:")

        for path in changes:
            print(
                f"- {path.relative_to(REPO_ROOT)}"
            )

        if not args.apply:
            print(
                "Dry-run only. "
                "No files were changed."
            )
            return 0

        write_changes(changes)

        print(
            "Documentation synchronized."
        )

        return 0

    except (
        OSError,
        RuntimeError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
