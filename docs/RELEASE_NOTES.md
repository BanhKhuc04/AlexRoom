# ALEX NEXUS OS MARK III — Release notes

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
