# ALEX Current Project Status

Canonical Core version: `0.6.0`

<!-- ALEX:CURRENT-STATUS:START -->
## Current verified project status

> This block is managed by `scripts/sync_project_docs.py`.

- ALEX Core version: `0.6.0`
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
- Current production release: `v0.6.0`

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

<!-- ALEX:CURRENT-STATUS:END -->

