# ALEX NEXUS OS MARK III — Release notes

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


## Step 1.3 safety foundation — 2026-07-21

- `CapabilityRegistry` trở thành nguồn verification truth duy nhất cho status, device và command API.
- Ghi nhận đúng trạng thái hiện tại: ESP01/test LED đã basic physical validation; toàn node chưa hardware-verified; Phase 7 đầy đủ vẫn ongoing.
- Relay 1–4 được server công bố `restricted`, chưa hardware-verified và tiếp tục bị khóa trước MQTT transport.
- Presence, Spatial Home và Device workspace tách ONLINE khỏi verification status.
- SQLite schema v3 lưu structured safety denial audit.

## 0.2.0-hardware-rc — 2026-07-21

- MQTT Protocol V1 cho `esp01/test_led` với command ID, ACK, reported state, heartbeat và status/LWT.
- Command lifecycle có accepted, waiting reported, retry tối đa hai lần, timeout/mismatch và transition audit.
- SQLite schema v2 giữ digital twin, timestamps, retry, origin và command events; migration additive/idempotent.
- SSE realtime với reconnect bounded; Presence, Device workspace và Spatial Home dùng desired/reported state thật.
- Bốn relay cũ bị khóa `RESTRICTED/NOT VERIFIED`; chỉ LED điện áp thấp được mở.
- Simulator trực tiếp và MQTT-process simulator luôn gắn `source=simulated`.
- Automation safe triggers, mission step execution và Wake-on-LAN software preparation.
- Firmware PlatformIO ESP8266 an toàn: LED OFF lúc boot, unique client ID, reconnect backoff, heartbeat và cache duplicate hữu hạn.

Ghi chú lịch sử: tại thời điểm đóng gói RC này chưa có bằng chứng vật lý. Sau đó ESP01/test LED đã đạt basic physical validation; release vẫn không phải hardware-verified release và relay vẫn bị khóa.

## 0.1.0-mark3 — 2026-07-21

- Presence Canvas 2D đa lớp với 10 visual state, waveform, reduced motion và ba quality path.
- Command Center có 12 workspace, Spatial Home một phòng và trạng thái integration trung thực.
- Web Audio engine nguyên bản với quiet/night/silent, priority, ducking và cleanup.
- SQLite schema idempotent cho audit, command history và domain records.
- API v1 additive, không phá API v0.3; simulator phải bật rõ ràng và luôn gắn nhãn.
- Safety gate chặn restricted actions; mutation API có authentication và bounded rate limit.
- Windows preview, systemd example, hướng dẫn triển khai/phần cứng và release script.

### Chưa xác minh phần cứng

Tại thời điểm release 0.1.0, các hạng mục này chưa được xác minh. Trạng thái hiện tại đã có basic physical validation cho ESP01/test LED; relay, cảm biến, microphone, Wake-on-LAN và tải điện thật vẫn chưa được xác minh. Không dùng release này để vận hành tải nguy hiểm khi chưa có interlock vật lý.
