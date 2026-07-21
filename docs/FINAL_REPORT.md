# ALEX NEXUS OS MARK III — Final Report

Tài liệu này được cập nhật tại final quality gate. Nguồn sự thật chi tiết theo phase nằm trong `IMPLEMENTATION_STATUS.md`.

Ngày kiểm tra: 2026-07-21. Presence, sound engine, Command Center và Spatial Home đạt quality gate phần mềm. Backend v1 additive, SQLite, simulator explicit, safety gate và release packaging hoạt động. Bản này **chưa hardware-ready** vì ACK firmware, interlock, telemetry streaming và automation execution còn thiếu.

## Final verification

- `npm run check:all`: PASS — 17 frontend tests và 2 backend tests.
- Browser: 12/12 workspace, desktop/mobile, ba quality mode và mode switching PASS.
- Console kể từ stable reload: 0 warning/error.
- API v0.3 compatibility PASS; SQLite online schema 1; MQTT local connected.
- Safety: production command 503 khi hardware chưa tích hợp; restricted action 423; mutation thứ 31 trong 60 giây trả 429.

## Actual proof

- `docs/screenshots/final-presence-desktop.png`
- `docs/screenshots/final-command-center-desktop.png`
- `docs/screenshots/final-presence-mobile.png`
- `docs/recordings/phase-2/presence-acceptance-sequence.gif`

Tất cả bằng chứng lấy từ localhost chạy thật, không dùng concept art.

## Production blockers

1. Firmware ACK có `commandId` và reported-state confirmation.
2. Interlock vật lý cho mọi restricted action.
3. Telemetry streaming, backend timeout/retry và automation/mission executor.
4. Kiểm thử ESP/relay/sensor/microphone/Wake-on-LAN trên phần cứng thật.
5. Recording có system audio trên capture surface được phép.

## Integration labels

- `real`: UI/Canvas/Web Audio/FastAPI/SQLite chạy trong local application.
- `simulated`: chỉ khi `ALEX_SIMULATOR=1`, có nhãn và audit source tương ứng.
- `hardware verified`: hiện chưa có hạng mục nào được phép mang nhãn này.

## Known environment limits

- Browser automation không capture system audio của Codex webview.
- Windows automation không được phép điều khiển Codex app để quay màn hình.
- Không có Git metadata, nên không tạo phase commits.

## Hardware V1 addendum

Software vertical slice `esp01/test_led` đã hoàn tất qua simulator nội bộ và MQTT simulator process riêng. Sau báo cáo ban đầu, giao tiếp phần cứng cơ bản với ESP01/test LED cũng đã được xác nhận. Registry hiện ghi capability này là `basic_physical_validated`; toàn node vẫn `hardware_verified=false`, Phase 7 đầy đủ còn ongoing và relay 1–4 chưa được xác minh.

Release candidate mới: `dist-release/AlexRoom-0.2.0-hardware-rc.zip`.
