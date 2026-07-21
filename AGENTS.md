# AGENTS.md — ALEXROOM / ALEX NEXUS OS

## 0. Purpose of this file

This repository belongs to **Khúc Việt Anh** and is the main codebase for **ALEXROOM / ALEX NEXUS OS**.

Read this file before every task. These instructions are durable project rules, not optional suggestions.

The user prefers:
- Vietnamese explanations by default.
- Clear step-by-step progress, especially when a technical choice is not obvious.
- Professional code, but explanations that a learner can follow.
- UI that feels premium, cinematic, polished, and reliable rather than flashy or game-like.
- Actual working previews captured from the running application. Never substitute AI-generated concept art for real screenshots of the implementation.

---

## 1. Product vision

ALEX is a local-first personal assistant and smart-room operating system.

It has two user experiences that share the same state, services, data, devices, scenes, automations, security model, and assistant:

### 1.1 ALEX Presence

Default full-screen interface.

It should feel like a calm, living AI presence rather than a dashboard.

Normally visible:
- ALEX Core at the center.
- Minimal time, connectivity, and mode status.
- A subtle background with depth.
- No permanent sidebar.
- No permanent grid of cards.
- No clutter.

Content appears only when relevant:
- A micro response for a short answer.
- A temporary context panel for temperature, energy, device status, security, or a task.
- A larger workspace for cameras, automation, reports, settings, or system maintenance.

### 1.2 ALEX Command Center

Advanced administration mode.

Used for:
- Spatial room overview.
- Device management.
- Automation builder.
- Scenes and missions.
- Security and cameras.
- Energy analytics.
- ALEX Brain status.
- Logs, diagnostics, settings, backup, and restore.

Presence and Command Center are not separate websites. They must use the same application state and transition instantly without reload.

---

## 2. System architecture and hardware constraints

### 2.1 ALEX Core

Runs 24/7 on an **Orange Pi One**.

Responsibilities:
- FastAPI backend.
- Static web/PWA serving.
- MQTT broker integration.
- Automation engine and scheduler.
- SQLite database.
- Tailscale access.
- Wake-on-LAN orchestration.
- Health, watchdog, heartbeat, logs, and backups.

The Orange Pi is resource-constrained. It must not be responsible for heavy browser rendering, AI inference, video processing, or large build jobs.

### 2.2 ALEX Brain

A PC with:
- Intel Core i5-4590.
- 8 GB RAM.
- 120 GB SSD.
- No discrete GPU.

It should sleep or remain off when not needed and wake through Wake-on-LAN for heavier work:
- Local AI.
- STT/TTS.
- Document processing.
- Computer vision.
- Long-running tasks.

### 2.3 Device layer

Expected:
- About 6 ESP8266 nodes.
- MQTT communication.
- Relay, sensors, irrigation, room control, and security devices.
- Heartbeat and device health.
- Real acknowledgment for commands.

Never show a device as successfully changed merely because the UI sent a request. Prefer:
1. `pending`
2. wait for API/MQTT acknowledgment
3. `confirmed`
4. on timeout, revert or mark `unknown`

---

## 3. Safety rules — non-negotiable

The project is currently not authorized to directly operate dangerous loads without verified hardware and safety interlocks.

Do not enable real control for:
- 220V loads that have not been inspected.
- UV lamps.
- Motors/pumps without correct driver, flyback protection, limits, and emergency stop.
- Door locks without verified fail-safe behavior.

Dangerous actions require:
- Hard safety interlock.
- Explicit confirmation.
- Maximum run time.
- Sensor prerequisites.
- Audit event.
- Safe default after disconnect.
- No voice-only activation for UV or other high-risk devices.

In demo mode, dangerous devices must be clearly marked **SIMULATED** and must never silently call a real endpoint.

---

## 4. Visual identity

ALEX may be inspired by high-end cinematic AI interfaces, but must not copy Iron Man/JARVIS branding, faces, armor, logos, copyrighted sounds, or exact HUD layouts.

Create a distinct ALEX identity:
- Graphite-black and deep navy foundation.
- Controlled cyan as the primary active color.
- Emerald for confirmed/safe.
- Amber for warning.
- Red-orange only for critical states.
- Fine technical lines.
- Optical depth and restrained glow.
- Original ALEX Energy Core.

Avoid:
- Generic SaaS dashboard appearance.
- Excessive cards.
- Constant neon glow everywhere.
- Fake terminal noise.
- Tiny unreadable text.
- Random animations with no semantic meaning.
- Full-screen blur layers.
- Video backgrounds.
- A huge static blue circle with no state behavior.

---

## 5. Presence Mode specification

### 5.1 Layout

- Full viewport.
- The ALEX Core is centered and is the visual focus.
- Top bar is almost invisible and contains only:
  - ALEX Presence.
  - local time.
  - online/offline state.
  - active room mode.
- Bottom command surface remains collapsed until needed.
- Panels should emerge from the Core or its orbit, then return to it.
- The user should still recognize the application as functional when all panels are hidden.

### 5.2 ALEX Core

The Core must be a real animated system, not a static image.

Recommended implementation:
- Three.js/WebGL or a high-quality layered Canvas renderer.
- Multiple independent rings.
- Shader-like optical core.
- Particles and data arcs.
- Audio waveform.
- State-driven timelines.
- Adaptive quality modes.

Core states:
- `idle`
- `wake`
- `listening`
- `thinking`
- `acting`
- `speaking`
- `success`
- `warning`
- `critical`
- `offline`

Each state needs:
- distinct motion
- distinct light behavior
- distinct text/status
- optional sound cue
- safe transition to the next state

Do not run cinematic motion at full intensity forever. Idle should be calm.

### 5.3 Context display levels

#### Micro response
For short confirmations:
- “Đã bật đèn bàn.”
- “PC đang khởi động.”
- “Không thể xác nhận trạng thái thiết bị.”

#### Context panel
For:
- temperature and humidity
- energy
- room state
- security
- system health
- mission progress

#### Workspace
For:
- cameras
- device management
- automation editor
- reports
- logs
- settings

---

## 6. Command Center specification

### 6.1 Main layout

Preferred layout:
- compact left navigation
- large central spatial workspace
- contextual ALEX assistant panel on the right
- health and event strip at the bottom
- a top status bar with room mode and system connectivity

### 6.2 Workspaces

Required:
1. Overview / Spatial Home
2. Devices
3. Automations
4. Scenes
5. Missions
6. Security
7. Cameras
8. Energy
9. ALEX Brain
10. Logs
11. System
12. Settings

Every navigation item must open a real view. No dead navigation.

### 6.3 Spatial Home

The main overview should represent the real room, not a generic luxury house.

Start with a configurable 2D/isometric room map:
- room zones
- door
- desk
- bed
- plants
- PC
- Orange Pi
- lights
- fan
- sensors
- ESP nodes

Device state should affect the scene:
- a light visually illuminates its zone
- a motion event highlights the detected zone
- offline nodes dim and show a warning
- a plant node shows moisture and watering state

Do not hard-code a mansion, multiple rooms, or devices the user does not own.

---

## 7. Motion system

Animation must communicate state and causality.

Examples:
- Wake: arcs converge and the core opens.
- Listening: waveform responds to actual microphone input when permission exists.
- Thinking: information streams inward.
- Acting: a beam or path connects the Core to the affected device/panel.
- Success: motion resolves into emerald confirmation.
- Error: movement interrupts; cause is shown.
- Open workspace: the workspace is constructed from lines/orbits related to the selected action.
- Close workspace: animation reverses and returns to the Core.

Support:
- `prefers-reduced-motion`
- performance quality levels: `performance`, `balanced`, `cinematic`
- tab visibility pause
- low-power fallback
- mobile fallback

Do not mix several animation libraries. Choose one orchestration library and document the choice.

---

## 8. Sound identity

Use original ALEX sounds only.

Never use audio extracted from Iron Man, JARVIS, films, games, or copyrighted packs without a license.

Sound events:
- wake
- listen open
- input accepted
- processing delay
- action success
- partial success
- warning
- critical
- offline
- cancel

Rules:
- no sound on every hover
- no endless beep loop
- no overlapping cues
- duck UI audio while TTS is speaking
- quiet mode
- silent mode
- night volume
- per-event volume controls
- Web Audio gain management
- audio may only start after a valid user interaction where required by the browser

---

## 9. Assistant behavior

Default language: Vietnamese.

The assistant must support verifiable commands such as:
- “Bật đèn bàn.”
- “Tắt đèn trần.”
- “Bật quạt.”
- “Tắt toàn bộ thiết bị an toàn.”
- “Chế độ học.”
- “Chế độ ngủ.”
- “Tôi đi vắng.”
- “Nhiệt độ phòng bao nhiêu?”
- “Hôm nay dùng bao nhiêu điện?”
- “Kiểm tra hệ thống.”
- “Kiểm tra an ninh.”
- “Mở trung tâm điều khiển.”
- “Quay lại giao diện tối giản.”
- “Đánh thức PC.”

For each command, expose:
- recognized text
- intent
- entities
- target
- action state
- acknowledgment source
- result
- failure reason

Do not expose private chain-of-thought. Show only user-understandable facts, plans, actions, and evidence.

---

## 10. Technical direction

Before choosing or changing the stack, inspect the repository.

Preferred front-end when compatible with the current repo:
- React
- TypeScript strict mode
- Vite
- Three.js or React Three Fiber for the Core/Spatial Home only
- one motion/orchestration library
- CSS variables/tokens
- PWA
- WebSocket telemetry
- IndexedDB/local cache for offline state

Backend:
- FastAPI
- SQLite
- MQTT
- WebSocket/SSE where appropriate
- structured event log
- health endpoints
- command acknowledgment and timeout

Do not rewrite a working backend merely to match this preference.

---

## 11. Code quality rules

- Use TypeScript strict mode.
- No `any` unless justified in a comment.
- Keep domain models in one clear location.
- Separate:
  - UI state
  - telemetry state
  - command state
  - persistent settings
  - demo/simulator state
- Components should have one primary responsibility.
- Avoid giant files. Refactor files approaching roughly 350–450 lines.
- Use semantic naming.
- Use design tokens instead of scattered values.
- No magic endpoint strings throughout the UI.
- No hard-coded fake successful status in production paths.
- No unhandled promise rejections.
- Every async action needs loading, timeout, success, and failure states.
- Preserve keyboard navigation.
- Maintain visible focus states.
- Meet readable contrast.
- Support reduced motion.
- Avoid unnecessary dependencies.
- Do not add packages before checking whether the repo already has an equivalent.
- Never commit secrets, API keys, device credentials, or Tailscale tokens.

---

## 12. Testing and quality gate

A task is not complete because it “looks good”.

Required quality checks where applicable:
- lint
- typecheck
- unit tests
- component tests
- API contract tests
- end-to-end smoke tests
- desktop screenshot
- mobile screenshot
- console error check
- network error behavior
- offline behavior
- reconnect behavior
- command timeout behavior
- reduced-motion behavior
- performance mode behavior

For visual work:
- screenshots must be captured from the running app
- compare implementation against the approved reference
- do not present generated concept art as evidence of completion

No completion claim unless:
- the app builds
- the changed route opens
- primary interactions work
- no critical console error remains
- changed behavior has been manually or automatically checked

---

## 13. Workflow for every substantial task

1. Read this file and related docs.
2. Inspect the existing repository before editing.
3. State what exists, what is missing, and what must be preserved.
4. Create a short implementation plan.
5. Make the smallest coherent change set.
6. Run relevant checks.
7. Capture actual screenshots for visual changes.
8. Summarize:
   - files changed
   - behavior added
   - tests run
   - known limitations
   - next recommended phase

Do not silently delete old features.
Do not perform a large rewrite unless the audit proves it is necessary.
Do not hide failures.
Do not claim hardware integration was tested unless real hardware was used.

---

## 14. User communication

When explaining work to the user:
- use Vietnamese
- explain the reason behind major decisions
- avoid excessive jargon
- show exact file names and commands
- be honest about what was simulated
- distinguish concept, implementation, and hardware-verified behavior
- provide one next step, not a long list of optional tangents
