from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"

SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

RELEASE_HEADING_PATTERN = re.compile(
    r"^# ALEX(?: NEXUS OS)? v(?P<version>[^\s]+)"
    r"(?:\s+—\s+\S.*)?\s*$",
    re.MULTILINE,
)


def validate_version(version: str) -> None:
    if not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid semantic version: {version}")


def extract_release_notes(
    changelog: str,
    version: str,
) -> str:
    validate_version(version)

    normalized = changelog.lstrip("\ufeff")

    matches = list(
        RELEASE_HEADING_PATTERN.finditer(normalized)
    )

    target_index: int | None = None

    for index, match in enumerate(matches):
        if match.group("version") == version:
            target_index = index
            break

    if target_index is None:
        raise ValueError(
            f"Release notes not found for version {version}"
        )

    start = matches[target_index].start()

    if target_index + 1 < len(matches):
        end = matches[target_index + 1].start()
    else:
        end = len(normalized)

    notes = normalized[start:end].strip()

    if not notes:
        raise ValueError(
            f"Release notes are empty for version {version}"
        )

    return notes + "\n"


def write_output(
    output_path: Path,
    content: str,
) -> None:
    resolved_output = output_path.resolve()
    resolved_changelog = CHANGELOG_FILE.resolve()

    if resolved_output == resolved_changelog:
        raise ValueError(
            "Refusing to overwrite canonical CHANGELOG.md"
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract release notes for one ALEX version "
            "from CHANGELOG.md."
        )
    )

    parser.add_argument(
        "version",
        help="Semantic version without the v prefix.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output file for the extracted notes.",
    )

    args = parser.parse_args()

    try:
        if not CHANGELOG_FILE.exists():
            raise ValueError(
                f"CHANGELOG.md is missing: {CHANGELOG_FILE}"
            )

        changelog = CHANGELOG_FILE.read_text(
            encoding="utf-8",
        )

        notes = extract_release_notes(
            changelog,
            args.version,
        )

        if args.output:
            write_output(
                args.output,
                notes,
            )

            print(
                f"Release notes written to: "
                f"{args.output.resolve()}"
            )
        else:
            print(
                notes,
                end="",
            )

        return 0

    except (OSError, ValueError) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
