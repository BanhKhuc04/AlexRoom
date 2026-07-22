from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

from next_version import calculate_release


def render_release_notes(result: dict[str, object]) -> str:
    if not result["releaseRequired"]:
        return "No release required."

    next_version = result["nextVersion"]
    commits = list(reversed(result["commits"]))

    groups: dict[str, list[dict[str, object]]] = {
        "Breaking Changes": [],
        "Features": [],
        "Fixes": [],
        "Maintenance": [],
    }

    for commit in commits:
        classification = commit["classification"]

        if classification == "major":
            groups["Breaking Changes"].append(commit)
        elif classification == "minor":
            groups["Features"].append(commit)
        elif classification == "patch":
            groups["Fixes"].append(commit)
        else:
            groups["Maintenance"].append(commit)

    lines = [
        f"# ALEX v{next_version}",
        "",
        f"Previous version: {result['currentVersion']}",
        f"Commits included: {result['commitsInspected']}",
        "",
    ]

    for heading, items in groups.items():
        if not items:
            continue

        lines.append(f"## {heading}")
        lines.append("")

        for commit in items:
            lines.append(
                f"- {commit['subject']} (`{commit['hash']}`)"
            )

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview ALEX release notes without modifying files."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Optional preview output path. The canonical changelog "
            "is not modified."
        ),
    )
    args = parser.parse_args()

    try:
        result = calculate_release()
        notes = render_release_notes(result)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(notes, end="")

    if args.output:
        output_path = args.output.resolve()

        if output_path == (REPO_ROOT / "CHANGELOG.md").resolve():
            print(
                "ERROR: dry-run cannot overwrite CHANGELOG.md",
                file=sys.stderr,
            )
            return 1

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            notes,
            encoding="utf-8",
            newline="\n",
        )

        print(f"\nPreview written: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
