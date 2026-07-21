# ALEXROOM — PRODUCT & EXPERIENCE SPECIFICATION

## 1. Product name

**ALEX NEXUS OS — MARK III**
Repository/project name: **AlexRoom**

MARK III is the visual-fidelity and product-quality generation after MARK II.

The central promise:

> ALEX is present when needed and invisible when not needed.

---

## 2. Product goals

1. Feel premium and cinematic without becoming a game HUD.
2. Remain practical for daily smart-room control.
3. Provide two synchronized interfaces:
   - Presence Mode
   - Command Center
4. Work locally when Internet is unavailable.
5. Keep basic control available while ALEX Brain is off.
6. Use real acknowledgments and honest device state.
7. Run efficiently when served by an Orange Pi One.
8. Produce actual implementation screenshots that closely match the approved design.

---

## 3. Experience principles

### Calm by default

Idle should be almost silent and visually calm.

### Reveal on demand

Information appears only when requested or when a meaningful event occurs.

### Motion explains action

Every significant movement must correspond to:
- listening
- understanding
- processing
- acting
- succeeding
- warning
- failing

### Honest state

Never display “ON” as confirmed until the system has evidence.

### Local-first

Internet loss must not disable:
- local dashboard
- local device control
- local scenes
- local automation
- local system health

### Safe by construction

High-risk operations must not be reachable through a decorative UI shortcut alone.

---

## 4. Presence Mode detailed flow

### 4.1 Idle

Visible:
- ALEX Core
- current time
- online/offline
- current mode
- optional single-line greeting

Hidden:
- command input
- cards
- navigation
- charts
- debug data

Motion:
- slow breathing
- subtle refraction
- sparse particles
- low frame/low power mode after inactivity

### 4.2 Wake

Triggers:
- user clicks/taps Core
- keyboard shortcut
- wake-word event
- important notification

Sequence:
1. original wake cue
2. rings align
3. core brightens
4. command surface appears
5. state becomes `listening`

### 4.3 Listening

- live audio waveform where available
- microphone permission state
- partial recognized text
- cancel action
- timeout state

### 4.4 Thinking

- recognized text freezes
- parsed intent can be shown in a small technical line
- data lines move toward core
- long processing must show elapsed time and allow cancel

### 4.5 Acting

- action plan panel
- each step has pending/running/confirmed/failed
- if targeting a device, spatial path points to it

### 4.6 Speaking

- waveform driven by TTS output
- subtitles always available
- UI sounds ducked

### 4.7 Completion

- compact confirmation
- evidence source
- automatic return to idle after a configurable delay

---

## 5. Command Center detailed layout

### Top bar
- ALEX logo/name
- active mode
- connectivity
- time
- notification center
- exit to Presence

### Left navigation
- Overview
- Devices
- Automations
- Scenes
- Missions
- Security
- Cameras
- Energy
- Brain
- Logs
- System
- Settings

### Center workspace
- changes by route
- spatial overview is default
- no empty decorative panel

### Right contextual assistant
- compact Core
- current conversation
- selected device/scene/action context
- quick actions relevant to the current route

### Bottom status strip
- Orange Pi health
- MQTT
- ESP online count
- ALEX Brain
- current power
- last critical event

---

## 6. Required domain models

The front-end should model at least:

```ts
type ConnectionState = "online" | "degraded" | "offline" | "unknown";

type CommandPhase =
  | "idle"
  | "queued"
  | "sending"
  | "waiting_ack"
  | "confirmed"
  | "failed"
  | "timed_out"
  | "cancelled";

type AlexVisualState =
  | "idle"
  | "wake"
  | "listening"
  | "thinking"
  | "acting"
  | "speaking"
  | "success"
  | "warning"
  | "critical"
  | "offline";

interface Device {
  id: string;
  name: string;
  type: string;
  roomZone: string;
  connection: ConnectionState;
  reportedState: Record<string, unknown>;
  desiredState?: Record<string, unknown>;
  lastSeenAt?: string;
  capabilities: string[];
  riskLevel: "safe" | "controlled" | "restricted";
}

interface DeviceCommand {
  id: string;
  deviceId: string;
  action: string;
  payload: Record<string, unknown>;
  phase: CommandPhase;
  requestedAt: string;
  acknowledgedAt?: string;
  failureReason?: string;
}

interface Scene {
  id: string;
  name: string;
  icon?: string;
  steps: SceneStep[];
  safetyLevel: "safe" | "confirm" | "restricted";
}

interface AutomationRule {
  id: string;
  name: string;
  enabled: boolean;
  trigger: unknown;
  conditions: unknown[];
  actions: unknown[];
  lastEvaluation?: RuleEvaluation;
}

interface Mission {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "partial" | "failed";
  steps: MissionStep[];
}

interface SystemHealth {
  orangePi: ConnectionState;
  mqtt: ConnectionState;
  database: ConnectionState;
  tailscale: ConnectionState;
  alexBrain: "awake" | "sleeping" | "offline" | "starting";
  espOnline: number;
  espTotal: number;
}
```

Adapt names to the current codebase rather than duplicating equivalent models.

---

## 7. Suggested front-end folders

Only apply after repository audit.

```text
src/
  app/
    App.tsx
    routes.tsx
    providers/
  core/
    alex-state/
    commands/
    telemetry/
    audio/
    motion/
    persistence/
  components/
    alex-core/
    context-panels/
    command-surface/
    status/
    ui/
  features/
    presence/
    command-center/
    devices/
    automations/
    scenes/
    missions/
    security/
    cameras/
    energy/
    brain/
    logs/
    system/
    settings/
  three/
    core-scene/
    spatial-home/
    quality/
  styles/
    tokens.css
    globals.css
    motion.css
  test/
```

---

## 8. Design tokens

Use variables rather than hard-coded values:

```css
:root {
  --alex-bg-0: #03070a;
  --alex-bg-1: #061018;
  --alex-surface-0: rgba(8, 19, 27, 0.72);
  --alex-surface-1: rgba(10, 26, 36, 0.82);

  --alex-cyan: #39ddff;
  --alex-cyan-soft: #8beeff;
  --alex-emerald: #4ee3a2;
  --alex-amber: #ffbd59;
  --alex-critical: #ff5f57;

  --alex-text-primary: #eafaff;
  --alex-text-secondary: #8da8b3;
  --alex-line: rgba(85, 210, 240, 0.18);
  --alex-line-strong: rgba(85, 210, 240, 0.42);

  --alex-radius-sm: 10px;
  --alex-radius-md: 16px;
  --alex-radius-lg: 24px;

  --alex-shadow-core: 0 0 80px rgba(57, 221, 255, 0.16);
  --alex-duration-fast: 140ms;
  --alex-duration-normal: 280ms;
  --alex-duration-cinematic: 700ms;
}
```

Do not blindly replace an existing token system. Merge carefully.

---

## 9. Performance budgets

Targets for a modern laptop in balanced mode:
- stable 60 FPS during common interactions
- no continuous main-thread long tasks
- no uncontrolled particle count growth
- no animation while the tab is hidden
- no repeated creation of audio contexts
- no WebGL resource leaks after route changes

Fallback:
- Canvas 2D or CSS core for devices without WebGL
- reduced particles on mobile
- static spatial map in performance mode

Orange Pi serves assets and APIs; client devices render the UI.

---

## 10. Definition of done for MARK III visual phase

Presence Mode:
- actual running UI looks recognizably close to approved visual direction
- Core has depth, multiple layers, meaningful state transitions
- command surface feels integrated, not like a generic input
- context panels emerge and retract cleanly
- desktop and mobile verified

Command Center:
- spatial room map represents the user's real one-room environment
- device state is visible and interactive
- assistant remains present
- route content is functional
- no dead buttons
- no misleading fake state

Proof:
- build result
- test commands and outputs
- actual desktop screenshot
- actual mobile screenshot
- short screen recording showing state transitions
- list of simulated vs real integrations
