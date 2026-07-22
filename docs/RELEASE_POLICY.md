# ALEX Release Policy

## 1. Canonical version

The canonical ALEX Core version is stored in the root `VERSION` file.

The following versions are independent and must not be changed by the
ALEX Core release process:

- ESP firmware version
- PROTOCOL_VERSION
- SCHEMA_VERSION

## 2. Current release baseline

Canonical version `0.3.0` was established at commit:

`35d358d feat: add canonical application version foundation`

Until the first stable `v0.3.0` tag is approved and created, release
dry-runs must inspect commits strictly after commit `35d358d`.

The old prerelease tag `v0.2.0-rc.1` must not be used to recalculate
changes already included in version `0.3.0`.

After a stable tag exists, the latest stable tag matching
`vMAJOR.MINOR.PATCH` becomes the release baseline.

Prerelease tags such as `v0.2.0-rc.1` are excluded from automatic
stable release baseline selection.

## 3. Version bump rules

The highest-impact qualifying commit determines the next version:

- `fix:` -> PATCH
- `feat:` -> MINOR
- `type!:` -> MAJOR
- Commit body containing `BREAKING CHANGE:` -> MAJOR

Priority:

MAJOR > MINOR > PATCH

Commits beginning with the following types do not cause a version bump:

- `chore:`
- `docs:`
- `style:`
- `refactor:`
- `perf:` unless explicitly classified later
- `test:`
- `build:`
- `ci:`
- `wip:`

If there are no qualifying commits, no release is created.

Merge commits are ignored.

## 4. Initial release trigger

During Phase 8.3 development:

- Normal pushes run validation only.
- Version calculation starts in dry-run mode.
- No tag or GitHub Release is created by dry-run.
- Release execution is initially manual through `workflow_dispatch`.
- Only one GitHub Actions workflow may create release commits, tags,
  changelogs, or GitHub Releases.

## 5. Release commit protection

A future automated release commit should use this format:

`chore(release): vX.Y.Z [skip ci]`

The release workflow must prevent recursive workflow loops.

## 6. Safety boundaries

The release system must not:

- Publish MQTT commands.
- Trigger ESP OTA.
- Modify ESP firmware versions.
- Modify PROTOCOL_VERSION.
- Modify SCHEMA_VERSION.
- Disable MQTT authentication.
- Change production hardware safety policy.
