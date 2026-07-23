# Changelog

# ALEX NEXUS OS v0.8.0 — Brain Text Intelligence

Previous version: 0.7.0
Commits included: 2

## Summary

- Added a standalone ALEX Brain text service with Ollama-native
  `qwen3.5:4b` provider support.
- Brain proposes only strict structured tools; ALEX Core remains the final
  execution authority and validates the complete response before execution.
- Added separate server-to-server Brain authentication and bounded provider,
  client, request, response, and tool-call validation.
- Added authoritative Core reads for system status and the device/capability
  registry.
- Added verified `test_led` mutation through the immutable
  `esp01/test_led/set` mapping, `CommandGateway`, and `SafetyPolicy`.
- Added stored safe mission execution with exact `brain_allowed` checks,
  enabled-state checks, and whole-mission safety preflight.
- Added stored safe automation execution with authoritative action resolution
  and whole-automation safety preflight.
- Added logical-only room modes: `home`, `away`, `sleep`, and `study`.
- Added refusal hardening, exact duplicate-call replay rejection, bounded
  identifiers, and log-injection protection.
- Core remains functional when Brain is disabled, unavailable, or offline.
- `relay_1` through `relay_4` remain restricted and unavailable to Brain.

## Security boundaries

This release does not include:

- STT, TTS, or wake-word support.
- Relay enablement.
- Generic MQTT publish, GPIO, shell, or arbitrary hardware tools.
- Direct Brain authority over MQTT, hardware, missions, automations, or room
  state.

## Validation evidence

- C8 full security, architecture, diff, and acceptance audit: PASS.
- C9A local real-AI six-tool acceptance with Ollama `qwen3.5:4b`: PASS.
- Frontend tests: 110 PASS.
- Backend tests: 518 PASS, 3 skipped, 259 subtests PASS.
- Focused safety, orchestration, and app-safety tests: 31 PASS.
- Ten-case authoritative simulator matrix: PASS, including pre-execution
  rejection of unsafe relay mission and automation records.
- Phase 0.8 Python module compilation and `git diff --check`: PASS.

No Orange Pi production deployment or production acceptance is claimed for
this release candidate.

## Commits

- feat(brain): add structured Brain text intelligence (`1ded367`)
- test(brain): add Phase 0.8 safety and integration coverage (`5b9ff20`)

# ALEX v0.7.0

Previous version: 0.6.0
Commits included: 38

## Features

- feat: add managed project documentation sync (`c79b0ca`)
- feat: add production backup and restore hardening (`3c234a6`)
- feat: add scheduled verified database backups (`5b88a34`)
- feat: add periodic system health monitoring (`c596fec`)
- feat: add log retention and rotation policies (`9a59ea9`)
- feat: add controlled database recovery workflow (`741a959`)
- feat: expand health monitoring with system metrics (`52f4ccb`)
- feat: add OTA state to system health (`09180df`)
- feat: monitor MQTT device and heartbeat health (`db4dd86`)
- feat: expose aggregated system health API (`ccc8315`)
- feat: show production health in system dashboard (`103b0b6`)
- feat: add bounded core auto recovery (`8c805e8`)
- feat: add local API hang watchdog (`a23037c`)
- feat: add post boot production acceptance (`37ebd0f`)
- feat: complete production hardening and acceptance gate (`87d04fe`)
- feat: add persistent audit logs workspace (`cc412e8`)
- feat: connect Brain compute workspace (`9f1639b`)
- feat: add safe automations workspace (`21ec945`)
- feat: add safe missions workspace (`a1a7728`)
- feat: add backup workspace (`0660ff9`)
- feat: reconcile scenes workspace (`d7f076b`)

## Fixes

- fix: handle transient ESP MQTT disconnects safely (`b739335`)
- fix: harden backup recovery permissions and timezone (`44ba7cb`)
- fix: force recover hung core through systemd (`c559fd1`)
- fix: harden CI and bootstrap OTA rollback state (`c8e5506`)
- fix: finalize LKG bootstrap acceptance safeguards (`f0738e0`)
- fix: run OTA updater directly from deployed repository (`140e159`)
- fix: allow backend tests without local venv (`e877045`)
- fix: install pytest in prepare release workflow (`4e6d528`)
- fix: restore prepare release workflow indentation (`809f4bb`)
- fix: preserve scene metadata round-trip (`fbb0f1f`)
- fix: install pytest in release workflow (`ce4408f`)

## Maintenance

- docs: synchronize project status with v0.6.0 (`4c45759`)
- test: add dirty shutdown recovery probe (`50f37a3`)
- chore(release): v0.7.0 (`a0fc703`)
- chore: reset unpublished v0.7.0 preparation (`022bb1a`)
- chore(release): v0.7.0 (`8d7b2cb`)
- chore: reset unpublished v0.7.0 after release workflow fix (`efc39ca`)

# ALEX v0.6.0

Previous version: 0.5.0
Commits included: 1

## Features

- feat: add one-click release preparation (`87a471b`)

# ALEX v0.5.0

Previous version: 0.4.0
Commits included: 2

## Features

- feat: add release notes extraction (`9ffe888`)
- feat: add manual release workflow (`e4150a3`)

# ALEX v0.4.0

Previous version: 0.3.0
Commits included: 9

## Features

- feat: add automatic version bump dry-run (`4cab533`)
- feat: add release notes preview (`87e24fc`)
- feat: add release file preparation script (`ba7cde3`)

## Fixes

- fix: align release package with canonical version (`9ddadff`)

## Maintenance

- docs: add ALEX release policy (`d08b098`)
- ci: add release version dry-run (`98fe218`)
- test: isolate update history from production path (`8a7d809`)
- ci: separate frontend and backend checks (`4a88f91`)
- test: cover release file preparation (`f67a3dd`)
