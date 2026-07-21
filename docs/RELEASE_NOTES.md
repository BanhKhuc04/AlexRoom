# ALEX NEXUS OS MARK III — Release notes

## 0.2.0-hardware-rc — 2026-07-21

- MQTT Protocol V1 cho `esp01/test_led` với command ID, ACK, reported state, heartbeat và status/LWT.
- Command lifecycle có accepted, waiting reported, retry tối đa hai lần, timeout/mismatch và transition audit.
- SQLite schema v2 giữ digital twin, timestamps, retry, origin và command events; migration additive/idempotent.
- SSE realtime với reconnect bounded; Presence, Device workspace và Spatial Home dùng desired/reported state thật.
- Bốn relay cũ bị khóa `RESTRICTED/NOT VERIFIED`; chỉ LED điện áp thấp được mở.
- Simulator trực tiếp và MQTT-process simulator luôn gắn `source=simulated`.
- Automation safe triggers, mission step execution và Wake-on-LAN software preparation.
- Firmware PlatformIO ESP8266 an toàn: LED OFF lúc boot, unique client ID, reconnect backoff, heartbeat và cache duplicate hữu hạn.

Firmware chưa được compile/flash vì môi trường chưa có PlatformIO/ESP8266/COM. Release này là software integration candidate, không phải hardware-verified release.

## 0.1.0-mark3 — 2026-07-21

- Presence Canvas 2D đa lớp với 10 visual state, waveform, reduced motion và ba quality path.
- Command Center có 12 workspace, Spatial Home một phòng và trạng thái integration trung thực.
- Web Audio engine nguyên bản với quiet/night/silent, priority, ducking và cleanup.
- SQLite schema idempotent cho audit, command history và domain records.
- API v1 additive, không phá API v0.3; simulator phải bật rõ ràng và luôn gắn nhãn.
- Safety gate chặn restricted actions; mutation API có authentication và bounded rate limit.
- Windows preview, systemd example, hướng dẫn triển khai/phần cứng và release script.

### Chưa xác minh phần cứng

ESP8266, relay, cảm biến, microphone, Wake-on-LAN và tải điện thật chưa được xác minh trong release này. Không dùng release này để vận hành tải nguy hiểm khi chưa có interlock vật lý.
