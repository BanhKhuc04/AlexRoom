# IMPLEMENTATION PLAN — ALEX NEXUS OS MARK III

## Strategy

Do not rebuild the whole application in one task.

High visual quality requires focused phases with a quality gate after each phase.

---

## Phase 0 — Repository audit

Deliver:
- `docs/AUDIT.md`
- detected stack
- current build/test commands
- current routes and components
- reusable backend/API/MQTT code
- dead code and known breakage
- visual gap analysis against `docs/PRODUCT_SPEC.md`
- risk list
- implementation order

No large rewrite in this phase.

---

## Phase 1 — Foundation and state machine

Deliver:
- normalized design tokens
- shared app state
- ALEX visual state machine
- command lifecycle model
- quality-mode model
- reduced-motion support
- app shell for Presence and Command Center
- reliable mode switching without reload

Quality gate:
- typecheck
- lint
- tests for state transitions
- desktop/mobile smoke screenshots

---

## Phase 2 — Presence visual fidelity

Deliver:
- production ALEX Core
- layered optical rendering
- state-specific timelines
- integrated waveform
- wake/listen/think/act/speak/success/error sequences
- collapsed command surface
- micro response
- context panel
- workspace opening transition

Quality gate:
- no critical console errors
- no animation leak after repeated state changes
- actual desktop/mobile screenshots
- short real screen recording
- reduced-motion demonstration

---

## Phase 3 — Original sound system

Deliver:
- centralized audio engine
- original generated/synthesized cues
- gain groups
- mute/quiet/night modes
- TTS ducking
- no-overlap policy
- browser autoplay handling

Quality gate:
- one audio context
- no overlapping duplicate cue
- graceful failure without audio permission

---

## Phase 4 — Command Center visual rebuild

Deliver:
- compact navigation
- contextual right assistant
- bottom system strip
- real workspaces
- responsive desktop/tablet/mobile layout
- consistent motion language

Quality gate:
- every nav item works
- no placeholder route
- responsive screenshots
- keyboard navigation

---

## Phase 5 — Spatial Home

Deliver:
- configurable room layout matching the user's actual room
- real device markers
- zones
- state-driven light/sensor visuals
- offline/degraded presentation
- mobile fallback

Quality gate:
- no fictitious mansion data
- device click opens real device context
- degraded mode remains usable

---

## Phase 6 — Commands, scenes, missions, and automations

Deliver:
- command acknowledgment
- scene execution steps
- mission progress
- automation explain view
- rule blocked reasons
- timeout/retry/cancel

Quality gate:
- simulator tests
- no optimistic false success
- clear failure reason

---

## Phase 7 — Backend and hardware integration

Deliver:
- FastAPI contract alignment
- MQTT topics and ACK handling
- ESP heartbeat
- Wake-on-LAN
- SQLite event store
- Tailscale-safe deployment
- systemd examples

Quality gate:
- simulator first
- then explicitly labeled real-hardware test
- no claim of physical verification without evidence

---

## Phase 8 — Security, safety, and reliability

Deliver:
- auth/session approach
- rate limits
- audit log
- restricted action flow
- backup/restore
- reconnect logic
- bounded logs
- safe defaults

---

## Phase 9 — Final quality gate

Run:
- lint
- typecheck
- unit
- component
- API contract
- E2E
- desktop/mobile browser smoke
- offline/reconnect
- soak test
- memory/WebGL leak inspection
- accessibility
- reduced motion
- backup/restore

Produce:
- release notes
- known limitations
- deployment guide
- actual preview images
- real screen recording
