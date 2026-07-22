from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from alex_version import SEMVER_REGEX

VERSION_FILE = REPO_ROOT / "VERSION"

# Canonical 0.3.0 was established at this commit.
FALLBACK_BASELINE_COMMIT = "35d358d"

STABLE_TAG_REGEX = re.compile(
    r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)

CONVENTIONAL_COMMIT_REGEX = re.compile(
    r"^(?P<type>[A-Za-z][A-Za-z0-9_-]*)"
    r"(?:\([^)]+\))?"
    r"(?P<breaking>!)?:\s+.+$"
)

BREAKING_CHANGE_REGEX = re.compile(
    r"(?mi)^BREAKING(?: |-)?CHANGE:\s+"
)


def run_git(arguments: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Git command failed: git {' '.join(arguments)}\n{error}"
        )

    return result.stdout


def load_current_version() -> str:
    if not VERSION_FILE.exists():
        raise RuntimeError(f"Cannot find VERSION file: {VERSION_FILE}")

    version = VERSION_FILE.read_text("utf-8").strip()

    if not SEMVER_REGEX.fullmatch(version):
        raise ValueError(f"Invalid semantic version in VERSION: {version!r}")

    return version


def parse_version(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)",
        version,
    )

    if not match:
        raise ValueError(
            f"Automatic stable bump requires MAJOR.MINOR.PATCH: {version!r}"
        )

    return tuple(int(part) for part in match.groups())


def find_latest_stable_tag() -> str | None:
    tags = run_git(["tag", "--merged", "HEAD", "--list"]).splitlines()

    stable_tags = [
        tag.strip()
        for tag in tags
        if STABLE_TAG_REGEX.fullmatch(tag.strip())
    ]

    if not stable_tags:
        return None

    return max(
        stable_tags,
        key=lambda tag: parse_version(tag.removeprefix("v")),
    )


def resolve_baseline() -> tuple[str, str]:
    stable_tag = find_latest_stable_tag()

    if stable_tag:
        return stable_tag, "stable-tag"

    run_git(["cat-file", "-e", f"{FALLBACK_BASELINE_COMMIT}^{{commit}}"])
    return FALLBACK_BASELINE_COMMIT, "canonical-0.3.0-commit"


def read_commits(baseline: str) -> list[dict[str, str]]:
    output = run_git(
        [
            "log",
            "--no-merges",
            "--format=%H%x1f%s%x1f%b%x1e",
            f"{baseline}..HEAD",
        ]
    )

    commits: list[dict[str, str]] = []

    for record in output.split("\x1e"):
        record = record.strip("\r\n")

        if not record:
            continue

        parts = record.split("\x1f", 2)

        if len(parts) != 3:
            raise RuntimeError("Unable to parse git log output")

        commit_hash, subject, body = parts

        commits.append(
            {
                "hash": commit_hash.strip(),
                "subject": subject.strip(),
                "body": body.strip(),
            }
        )

    return commits


def classify_commit(subject: str, body: str) -> str | None:
    match = CONVENTIONAL_COMMIT_REGEX.fullmatch(subject)

    if BREAKING_CHANGE_REGEX.search(body):
        return "major"

    if not match:
        return None

    if match.group("breaking"):
        return "major"

    commit_type = match.group("type").lower()

    if commit_type == "feat":
        return "minor"

    if commit_type == "fix":
        return "patch"

    return None


def highest_bump(commits: Sequence[dict[str, str]]) -> str | None:
    priority = {
        None: 0,
        "patch": 1,
        "minor": 2,
        "major": 3,
    }

    result: str | None = None

    for commit in commits:
        bump = classify_commit(commit["subject"], commit["body"])

        if priority[bump] > priority[result]:
            result = bump

    return result


def bump_version(current_version: str, bump: str | None) -> str:
    major, minor, patch = parse_version(current_version)

    if bump == "major":
        return f"{major + 1}.0.0"

    if bump == "minor":
        return f"{major}.{minor + 1}.0"

    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"

    return current_version


def calculate_release() -> dict[str, object]:
    current_version = load_current_version()
    baseline, baseline_type = resolve_baseline()
    commits = read_commits(baseline)
    bump = highest_bump(commits)
    next_version = bump_version(current_version, bump)

    return {
        "mode": "dry-run",
        "currentVersion": current_version,
        "baseline": baseline,
        "baselineType": baseline_type,
        "commitsInspected": len(commits),
        "bump": bump,
        "nextVersion": next_version,
        "releaseRequired": bump is not None,
        "commits": [
            {
                "hash": commit["hash"][:7],
                "subject": commit["subject"],
                "classification": classify_commit(
                    commit["subject"],
                    commit["body"],
                ),
            }
            for commit in commits
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calculate the next ALEX Core version without modifying files."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the dry-run result as JSON.",
    )
    args = parser.parse_args()

    try:
        result = calculate_release()
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print("ALEX RELEASE VERSION DRY-RUN")
    print(f"Current version : {result['currentVersion']}")
    print(f"Baseline        : {result['baseline']} ({result['baselineType']})")
    print(f"Commits checked : {result['commitsInspected']}")
    print(f"Required bump   : {result['bump'] or 'none'}")
    print(f"Next version    : {result['nextVersion']}")
    print(
        "Release needed  : "
        + ("yes" if result["releaseRequired"] else "no")
    )

    for commit in result["commits"]:
        classification = commit["classification"] or "ignored"
        print(
            f"- {commit['hash']} [{classification}] "
            f"{commit['subject']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


