# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Source of truth

Current project status, roadmap and architectural debt live in:

`docs/ALEX_CURRENT_PROJECT_STATUS_REPORT_2026-07-26.md`

Read that report when a task involves architecture, current status, roadmap, acceptance state, or architectural debt. Do **not** preload or import it for unrelated tasks.

`AGENTS.md` holds durable product/UX/safety rules and takes precedence where it overlaps this file. Explain work to the user in **Vietnamese**.

Evidence priority when documents disagree — **live runtime wins**:

1. live runtime evidence
2. deployed Git HEAD + service state
3. current source/tests
4. current phase reports
5. old audits, old roadmap/spec

## Invariants

- ALEX Core on Orange Pi is the final authority: auth, IntelligenceRouter, SafetyPolicy, CapabilityRegistry, command lifecycle, SQLite state/audit, MQTT, hardware verification.
- Brain computes and proposes only. No MQTT, no GPIO, no hardware authority, no bypassing Core, no self-confirming hardware success.
- Never fake success or fake physical verification. HTTP 200 is not `SUCCESS`. Distinguish `requested / queued / sent / waiting_ack / acknowledged / reported / verified / physically_verified / failed / timed_out / cancelled`.
- `SOFTWARE PASS` != `RUNTIME PASS` != `PHYSICAL PASS`. Never merge the three.
- Diagnostic tasks: collect trace/evidence before changing any code.
- Architectural problems outside the current blocker: record as architectural debt/correction. Fix only what directly blocks the current runtime; do not refactor broadly.
- Execute only the assigned checkpoint. Do not advance the NEXT ACTION PLAN to the next Step on your own.
- No commit, push, release, or deploy unless the prompt asks explicitly.

## Model & Subagent Policy

Main conversation (Sonnet) owns: reasoning, architecture, safety analysis, root-cause decisions, production code, new test-case design, failure review, and the SOFTWARE/RUNTIME/PHYSICAL verdict.

Do not use a "code with Sonnet, test with Haiku" split. The rule is by task nature:

- reasoning / architecture / safety / new logic → main Sonnet
- mechanical / repetitive / verbose execution → dedicated Haiku subagent (`test-runner`, `runtime-checker`)

## Commands

```bash
npm run check          # typecheck + lint + node tests + static build (frontend gate)
npm run check:all      # check + pytest + py_compile of core modules (full gate)
npm run typecheck      # tsc against static/**/*.js (checkJs, strict)
npm run lint           # eslint static tests scripts eslint.config.js
npm test               # node --test tests/*.test.mjs
npm run test:backend   # pytest via .venv (scripts/run-pytest.mjs)
npm run build          # validates required static assets, copies static/ -> dist/static

python -m pytest -q                                   # all backend tests
python -m pytest tests/test_voice_orchestration.py -q # single file
python -m pytest tests/test_safety.py::test_name -q   # single test
node --test tests/realtime.test.mjs                   # single frontend test

npm run preview:windows          # uvicorn app:app on 127.0.0.1:5173 (needs MQTT_PASSWORD, ALEX_API_KEY, .venv)
python -m uvicorn app:app --host 127.0.0.1 --port 8000
python -m uvicorn brain_service.app:app --host 127.0.0.1 --port 8090   # Brain PC service
```

Env templates: `.env.example` (Core), `deploy/alex-brain.env.example` (Brain).

## Architecture

**ALEX Core** (`app.py` + flat `alex_*.py`, Orange Pi One, ARMv7, ~512 MB) — FastAPI :8000, serves the static PWA. No ML inference here. `requirements-orangepi.txt` omits `uvicorn[standard]` because uvloop/httptools get OOM-killed compiling on-device.

**ALEX Brain** (`brain_service/`, PC, no GPU) — FastAPI :8090. LLM chat via Ollama/OpenAI-compatible provider, STT (`faster-whisper`), TTS (`piper`). Must never import paho-mqtt. `alex_local_stt.py` / `alex_local_tts.py` load lazily inside `brain_service/app.py` getters.

**Browser** — I/O endpoint only: UI, microphone capture, audio playback, Presence state, Command Center, voice WebSocket client.

**Devices** — ESP8266 over the V1 MQTT contract in `docs/MQTT_PROTOCOL_V1.md`. Only `esp01/test_led` is allowed; relays, UV, locks, motors are restricted pending hardware interlocks.

### Command lifecycle

`queued → sending → waiting_ack → accepted → waiting_reported_state → confirmed`, with `retrying` / `timed_out` / `failed` branches. A successful MQTT publish is not proof a device changed. Only a reported state matching both the command ID and the desired value produces `confirmed`.

### Core module map

- Storage/state: `alex_store.py` (SQLite, domain records), `alex_hardware.py` (MQTT command service, ACK/reported tracking)
- Safety: `alex_safety.py` — capability registry, `verification_status` (`unknown` → `simulated` → `software_verified` → `basic_physical_validated` → `hardware_verified`, or `restricted`) gates `command_allowed` per room mode
- Intelligence: `alex_intelligence_router.py` routes between the deterministic fast path (`alex_intelligence_fast_path.py`, `alex_intent_planner.py`) and Brain (`alex_brain_client.py` → `alex_brain_integration.py`). `alex_brain_tools.py` is the tool contract; `alex_brain_orchestration_boundary.py` turns validated proposals into Core-owned execution.
- Voice: `alex_voice.py` (session state machine), `alex_voice_transport.py` (WebSocket `/api/v1/voice/stream`), `alex_stt.py` / `alex_tts.py` (Protocol + deterministic test providers), `alex_wake_word.py`
- Ops: `alex_health*.py`, `alex_watchdog.py`, `alex_backup.py` / `alex_restore.py`, `alex_recovery.py`, `alex_ota.py`, `alex_powerloss_*.py` — each has a matching systemd unit in `deploy/`

Feature flags are env-driven, read once at `app.py` import (`ALEX_SIMULATOR`, `ALEX_INTELLIGENCE_*`, `ALEX_BRAIN_*`).

### Frontend

Plain ES modules, no bundler, no framework. `static/app.js` is the entry; `static/core/` holds engine modules, `static/ui/` holds views. Type safety is `checkJs` + JSDoc against `static/core/domain.d.ts` — there is no TypeScript source. `scripts/build.mjs` hard-fails on a missing/empty required asset or a shell missing `#presenceMode`, `#commandCenter`, `#alexCore`, `#commandNav`. Presence and Command Center share one app state and switch without reload. Telemetry is SSE (`/api/v1/realtime`); voice is a separate WebSocket.

## Versioning and releases

`VERSION` is canonical; `alex_version.py` validates it at import and `package.json` mirrors it. `scripts/sync_project_docs.py` regenerates the `<!-- ALEX:CURRENT-STATUS -->` blocks in `README.md` and several `docs/*.md` from `docs/CURRENT_PROJECT_STATUS.md` — edit the source, not the generated blocks. Commit messages must follow conventional-commit format; `scripts/next_version.py` derives the version bump from them. Release is two-stage: `scripts/prepare_release.py` (version calc, changelog, release commit, no tag), then a manual publish requiring `mode=publish` and typing `RELEASE`.

## Other references

- `docs/ARCHITECTURE_CORRECTIONS.md` — debt register, classified `FIX_NOW` / `DEFER_NEXT_PHASE` / `KEEP`. Check before "fixing" something deliberately deferred.
- `docs/MQTT_PROTOCOL_V1.md` — wire contract, lifecycle, duplicate handling, offline inference
- `brain_service/README.md` — provider config and manual smoke test

Ignore `ALEX_NEXUS_*` and `ALEX_NEXUS_UI_*` directories: archived snapshots, excluded from lint, not part of the running system.
