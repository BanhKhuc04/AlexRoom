# Hardware Integration

Trạng thái hiện tại: giao tiếp phần cứng cơ bản với `esp01` và LED thử nghiệm điện áp thấp đã được xác nhận. Registry ghi `esp01/test_led` là `basic_physical_validated`, nhưng toàn node vẫn `hardware_verified=false` vì Phase 7 đầy đủ chưa hoàn tất. Relay, tải điện, cảm biến và ALEX Brain chưa được xác minh vật lý.

## Vertical slice V1

- Target duy nhất được mở: `esp01/test_led`, LED tích hợp điện áp thấp.
- Contract: `docs/MQTT_PROTOCOL_V1.md`.
- Firmware PlatformIO: `firmware/esp01/`; safe boot luôn OFF, reconnect/backoff không chặn, LWT, heartbeat và cache 8 command.
- Backend chỉ xác nhận sau ACK và reported state khớp. Retry tối đa hai lần.
- SQLite schema v3 lưu desired/reported, timestamps, retry, origin, phase, transition timeline và structured safety audit.
- Simulator explicit hỗ trợ normal, delayed/missing ACK, wrong state, offline, high latency và duplicate.
- SSE đẩy lifecycle/node state; frontend rehydrate từ REST sau reconnect.

- ESP01 topics hiện hữu: `alex/device/esp01/availability` và `alex/device/esp01/switch/relay_1..4/{command,state}`.
- HTTP `accepted` chỉ chứng minh publish; UI chờ reported state trước `confirmed`.
- `ALEX_SIMULATOR=1` là opt-in và dữ liệu thực thi mang `source=simulated`; mức xác minh node/capability vẫn được công bố riêng từ `CapabilityRegistry`, không suy ra từ connectivity hay source.
- UV, relay 220V chưa kiểm tra, pump/motor và khóa cửa là restricted: cần interlock cứng, maximum runtime, sensor prerequisite, xác nhận và audit.
- Trước kiểm thử thật: xác nhận driver/flyback/fuse/grounding, safe disconnect, emergency stop và map relay-to-load đã duyệt.
