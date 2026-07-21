# Tóm tắt kết quả ALEX Hardware Integration V1

## Kết luận

Phần mềm cho lát cắt phần cứng V1 `esp01/test_led` đã hoàn thành và vượt qua các kiểm tra build, lint, typecheck, unit test, API smoke, MQTT integration và browser smoke. Luồng lệnh không hiển thị thành công giả: trạng thái chỉ chuyển sang `confirmed` sau khi backend nhận được `reported state` phù hợp.

Sau báo cáo RC ban đầu, giao tiếp phần cứng cơ bản với ESP01 và LED thử nghiệm đã được xác nhận. Trạng thái chính thức hiện tại là `basic_physical_validated` cho `test_led`; đây không phải xác minh toàn node và không hoàn tất Phase 7. Relay 1–4 vẫn `restricted`, chưa được xác minh và không được phép gửi lệnh.

## Kiến trúc và luồng lệnh

- Backend: FastAPI, Paho MQTT, SQLite và SSE realtime.
- Frontend: static ES modules, JSDoc strict và Canvas 2D.
- Firmware: ESP8266/NodeMCU, chỉ điều khiển LED thử nghiệm an toàn.
- MQTT V1: `alex/v1/nodes/esp01/{command,ack,reported,heartbeat,telemetry,status}`.
- Vòng đời lệnh chính:

  `queued → sending → waiting_ack → accepted → waiting_reported_state → confirmed`

- Các trạng thái lỗi được hỗ trợ: `retrying`, `failed`, `timed_out`, `cancelled`.
- Kết quả chỉ được xác nhận khi `reported state` trùng với trạng thái mong muốn.

## Những phần đã hoàn thành

- Thêm command service, realtime hub, retry có giới hạn, heartbeat và digital twin.
- Thêm SQLite schema v3 cho command history, command events, device registry và structured safety audit.
- Thêm simulator nội bộ và simulator MQTT chạy như một tiến trình riêng.
- Thêm firmware ESP01 với trạng thái boot an toàn `OFF`, reconnect backoff, LWT, heartbeat, ACK, reported state và chống xử lý trùng lệnh.
- Presence hiểu lệnh “Alex, bật/tắt đèn thử.”
- Command Center hiển thị connection, desired state, reported state, firmware, RSSI, last seen, command và số lần retry.
- Spatial Home có marker Test LED phản ánh `reported state`.
- Bốn relay cũ bị khóa theo registry với trạng thái `restricted` và `hardware_verified=false`.
- SSE tự reconnect theo backoff, tạm dừng khi tab bị ẩn và dọn tài nguyên khi unmount.
- Giữ tương thích các route API v0.3 hiện có.

## Kết quả kiểm thử

| Hạng mục | Kết quả |
|---|---|
| Typecheck | PASS |
| ESLint | PASS |
| Frontend unit tests | PASS — 21/21 |
| State-transition soak | PASS — 500 vòng |
| Production build | PASS |
| Backend tests | PASS — 14/14 |
| Python compile | PASS |
| API smoke qua Uvicorn | PASS |
| MQTT integration qua Mosquitto local | PASS |
| Desktop browser smoke | PASS |
| Mobile 390×844 | PASS — không tràn ngang |
| Console ổn định | PASS — 0 warning/error |
| Giao tiếp phần cứng cơ bản ESP01 | PASS trước Step 1.3 |
| LED thử nghiệm vật lý | BASIC PHYSICAL VALIDATION |
| Phase 7 đầy đủ | ĐANG TIẾP TỤC |
| Relay 1–4 | RESTRICTED / CHƯA XÁC MINH |

Các safety gate đã được xác minh ở mức phần mềm:

- Thiết bị restricted trả HTTP `423`.
- Relay không được hỗ trợ trả HTTP `400`.
- Wake-on-LAN chưa cấu hình trả HTTP `409`.
- Không bật điều khiển thật cho tải 220V, UV, khóa cửa, bơm hoặc động cơ.

## Phần thật, phần mô phỏng và giới hạn

### Đã chạy thật trong ứng dụng

- FastAPI, SQLite, MQTT broker local và SSE realtime.
- UI Presence, Command Center và Spatial Home.
- Luồng command/ACK/reported state qua broker Mosquitto thật.
- Retry, timeout, reconnect, command history và digital twin.

### Chế độ mô phỏng vẫn được hỗ trợ

- Simulator có thể tạo ACK, heartbeat, telemetry và reported state cho kiểm thử lỗi.
- Các kết quả mô phỏng mang nguồn `simulated`; production không fallback ngầm sang thành công giả.
- Simulator không thay đổi mức xác minh chính thức trong `CapabilityRegistry`.

### Chưa được xác minh

- Toàn bộ checklist Phase 7, bao gồm power-cycle, reconnect, duplicate, timeout và soak dài hạn.
- Xác minh toàn node ESP01 ở mức `hardware_verified`.
- Độ ổn định dài hạn của thiết bị và broker trên Orange Pi.
- Mọi thiết bị điện áp cao hoặc thiết bị nguy hiểm.

## Bằng chứng từ ứng dụng đang chạy

- `docs/screenshots/hardware-v1/presence-test-led-confirmed.png`
- `docs/screenshots/hardware-v1/digital-twin-desktop.png`
- `docs/screenshots/hardware-v1/digital-twin-mobile.png`

Các ảnh trên được chụp từ ứng dụng localhost đang chạy, không phải concept art hoặc ảnh AI tạo sinh.

## Tài liệu và gói phát hành

- Giao thức MQTT: `docs/MQTT_PROTOCOL_V1.md`
- Giao thức realtime: `docs/REALTIME_PROTOCOL.md`
- Hướng dẫn flash: `docs/ESP01_FLASH_GUIDE.md`
- Kế hoạch kiểm thử ESP01: `docs/ESP01_TEST_PLAN.md`
- Tích hợp phần cứng: `docs/HARDWARE_INTEGRATION.md`
- Trạng thái triển khai: `docs/IMPLEMENTATION_STATUS.md`
- Báo cáo cuối: `docs/FINAL_REPORT.md`
- Gói release: `dist-release/AlexRoom-0.2.0-hardware-rc.zip`

Gói ZIP đã được kiểm tra và không chứa `.env`, database hoặc file secrets.

## Bước tiếp theo duy nhất

Tiếp tục checklist Phase 7 trong `docs/ESP01_TEST_PLAN.md`, đặc biệt power-cycle, reconnect, duplicate command, timeout và soak. Chỉ sau khi toàn bộ checklist PASS mới được đổi trạng thái node từ `basic_physical_validated` sang `hardware_verified`; relay vẫn cần quy trình xác minh và interlock riêng.
