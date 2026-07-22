from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

from next_version import calculate_release
from prepare_release import render_release_notes

VERSION_FILE = REPO_ROOT / "VERSION"
PACKAGE_FILE = REPO_ROOT / "package.json"
PACKAGE_LOCK_FILE = REPO_ROOT / "package-lock.json"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"


def run_git(arguments: list[str]) -> str:
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

    return result.stdout.strip()


def ensure_clean_working_tree() -> None:
    status = run_git(["status", "--porcelain"])

    if status:
        raise RuntimeError(
            "Working tree is not clean. Commit or discard changes first."
        )


def ensure_target_tag_missing(version: str) -> None:
    tag = f"v{version}"
    existing = run_git(["tag", "--list", tag])

    if existing:
        raise RuntimeError(f"Release tag already exists: {tag}")


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RuntimeError(f"Required JSON file is missing: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def render_json(data: dict[str, object]) -> str:
    return json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def build_release_files(
    result: dict[str, object],
) -> dict[Path, str]:
    next_version = str(result["nextVersion"])

    package = load_json(PACKAGE_FILE)
    package_lock = load_json(PACKAGE_LOCK_FILE)

    package["version"] = next_version
    package_lock["version"] = next_version

    packages = package_lock.get("packages")

    if not isinstance(packages, dict):
        raise RuntimeError(
            "package-lock.json does not contain a packages object"
        )

    lock_root = packages.get("")

    if not isinstance(lock_root, dict):
        raise RuntimeError(
            "package-lock.json does not contain the root package"
        )

    lock_root["version"] = next_version

    release_notes = render_release_notes(result)

    if CHANGELOG_FILE.exists():
        existing_changelog = CHANGELOG_FILE.read_text(
            encoding="utf-8"
        ).lstrip("\ufeff").lstrip()

        header = "# Changelog"

        if existing_changelog.startswith(header):
            existing_body = existing_changelog[
                len(header):
            ].lstrip()
        else:
            existing_body = existing_changelog

        changelog = (
            header
            + "\n\n"
            + release_notes.rstrip()
        )

        if existing_body:
            changelog += (
                "\n\n"
                + existing_body
            )
    else:
        changelog = (
            "# Changelog\n\n"
            + release_notes.rstrip()
        )

    return {
        VERSION_FILE: next_version + "\n",
        PACKAGE_FILE: render_json(package),
        PACKAGE_LOCK_FILE: render_json(package_lock),
        CHANGELOG_FILE: changelog.rstrip() + "\n",
    }


def write_release_files(files: dict[Path, str]) -> None:
    for path, content in files.items():
        path.write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare canonical ALEX release files. "
            "No commit, tag, or GitHub Release is created."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write release changes to the working tree.",
    )
    args = parser.parse_args()

    try:
        ensure_clean_working_tree()

        result = calculate_release()

        if not result["releaseRequired"]:
            print("No release required.")
            return 0

        next_version = str(result["nextVersion"])

        ensure_target_tag_missing(next_version)

        files = build_release_files(result)

        print("ALEX RELEASE FILE PREPARATION")
        print(f"Current version : {result['currentVersion']}")
        print(f"Next version    : {next_version}")
        print(f"Required bump   : {result['bump']}")
        print(f"Apply changes   : {'yes' if args.apply else 'no'}")
        print("Files:")

        for path in files:
            print(f"- {path.relative_to(REPO_ROOT)}")

        if not args.apply:
            print(
                "Dry-run only. Re-run with --apply after review."
            )
            return 0

        write_release_files(files)

        print("Release files prepared successfully.")
        print("No commit, tag, or GitHub Release was created.")
        return 0

    except (
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
