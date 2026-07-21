# Hardware Integration

Hiện chỉ **local software verified**. MQTT broker local đã được kiểm tra; ESP01, relay, tải điện, cảm biến và ALEX Brain chưa được xác minh vật lý.

## Vertical slice V1

- Target duy nhất được mở: `esp01/test_led`, LED tích hợp điện áp thấp.
- Contract: `docs/MQTT_PROTOCOL_V1.md`.
- Firmware PlatformIO: `firmware/esp01/`; safe boot luôn OFF, reconnect/backoff không chặn, LWT, heartbeat và cache 8 command.
- Backend chỉ xác nhận sau ACK và reported state khớp. Retry tối đa hai lần.
- SQLite schema v2 lưu desired/reported, timestamps, retry, origin, phase và transition timeline.
- Simulator explicit hỗ trợ normal, delayed/missing ACK, wrong state, offline, high latency và duplicate.
- SSE đẩy lifecycle/node state; frontend rehydrate từ REST sau reconnect.

- ESP01 topics hiện hữu: `alex/device/esp01/availability` và `alex/device/esp01/switch/relay_1..4/{command,state}`.
- HTTP `accepted` chỉ chứng minh publish; UI chờ reported state trước `confirmed`.
- `ALEX_SIMULATOR=1` là opt-in và mọi response mang `source=simulated`, `hardware_verified=false`.
- UV, relay 220V chưa kiểm tra, pump/motor và khóa cửa là restricted: cần interlock cứng, maximum runtime, sensor prerequisite, xác nhận và audit.
- Trước kiểm thử thật: xác nhận driver/flyback/fuse/grounding, safe disconnect, emergency stop và map relay-to-load đã duyệt.
