# BÁO CÁO TIẾN ĐỘ VÀ LỘ TRÌNH PHÁT TRIỂN

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


## ALEX NEXUS OS MARK III / AlexRoom

- Chủ sở hữu: **Khúc Việt Anh**
- Ngày tổng hợp: **21/07/2026**
- Phiên bản phần mềm hiện tại: **0.2.0-hardware-rc**
- Trạng thái tổng thể: **Release candidate ở mức phần mềm; chưa hardware-ready**

---

## 1. Tóm tắt điều hành

ALEX NEXUS OS MARK III đã có một nền tảng phần mềm hoàn chỉnh để tiếp tục tích hợp nhà thông minh theo hướng local-first. Giao diện Presence, Command Center, Spatial Home, hệ thống âm thanh, state machine, FastAPI, SQLite, MQTT, SSE realtime và simulator đều đã hoạt động.

Luồng phần cứng V1 cho `esp01/test_led` đã hoàn thành ở mức tích hợp phần mềm. Hệ thống không hiển thị thành công ngay khi gửi lệnh; nó chỉ chuyển sang `confirmed` sau khi nhận ACK và `reported state` phù hợp. Đây là nền tảng quan trọng để tránh trạng thái thiết bị giả.

Tuy nhiên, dự án **chưa được xác minh trên ESP8266 và tải vật lý thật**. Firmware chưa được compile/flash trong môi trường hiện tại vì chưa có PlatformIO, ESP8266 và cổng COM. Vì vậy, bản hiện tại chỉ là release candidate cho phần mềm, không phải bản triển khai phần cứng hoàn chỉnh.

---

## 2. Kiến trúc hiện tại

### Frontend

- Static ES modules với JSDoc strict.
- Canvas 2D nhiều lớp cho ALEX Core.
- CSS design tokens dùng chung.
- Presence và Command Center dùng chung application state.
- PWA, responsive desktop/mobile và hỗ trợ offline cơ bản.
- Web Audio engine tập trung.
- SSE nhận trạng thái realtime từ backend.

### Backend

- FastAPI.
- Paho MQTT.
- SQLite schema v2.
- API v1 bổ sung nhưng vẫn giữ tương thích route v0.3.
- Command service, device registry, audit log và event store.
- Simulator chỉ chạy khi được bật rõ ràng.
- Wake-on-LAN đã có phần chuẩn bị ở mức phần mềm.

### Device layer

- Firmware ESP8266/NodeMCU trong `firmware/esp01/`.
- Target V1 duy nhất được mở: `esp01/test_led`.
- MQTT Protocol V1 có command ID, ACK, reported state, heartbeat, telemetry và LWT/status.
- Các relay cũ và thiết bị nguy hiểm vẫn bị khóa.

---

## 3. Kết quả theo từng phase

| Phase | Trạng thái thực tế | Kết quả chính |
|---|---|---|
| Phase 0 — Audit | **Hoàn thành** | Xác định stack, routes, data flow, API/MQTT/PWA, phần cần bảo tồn và khoảng cách thị giác |
| Phase 1 — Foundation | **Hoàn thành** | Design tokens, shared state, visual state machine, command lifecycle, quality modes và reduced motion |
| Phase 2 — Presence | **Accepted** | ALEX Core Canvas nhiều lớp, 10 trạng thái, waveform, panels, responsive và cleanup |
| Phase 3 — Sound | **Hoàn thành phần mềm** | Web Audio engine, cue nguyên bản, gain groups, quiet/night/silent và TTS ducking |
| Phase 4 — Command Center | **Hoàn thành phần mềm** | 12/12 workspace mở được, responsive và dùng chung state |
| Phase 5 — Spatial Home | **Hoàn thành phần mềm** | Bản đồ một phòng 2D/isometric, marker thiết bị và trạng thái degraded/offline |
| Phase 6 — Domain execution | **Một phần** | Có lifecycle, automation/mission foundation và simulator; còn cần hoàn thiện contract và E2E domain |
| Phase 7 — Backend/hardware | **Basic physical validation PASS; full phase ongoing** | ESP01/test LED đã xác nhận giao tiếp cơ bản; toàn node và relay chưa hardware-verified |
| Phase 8 — Safety/reliability | **Một phần** | API key, rate limit, audit, restricted gate và backup cơ bản; chưa có interlock vật lý/restore hoàn chỉnh |
| Phase 9 — Hardening | **Một phần** | Build/test/browser/soak hiện tại PASS; chưa có full hardware/offline/deployment soak |
| Phase 10 — Release | **Release candidate** | Có ZIP và tài liệu triển khai; chưa đủ điều kiện phát hành hardware-ready |

---

## 4. Những gì đã làm được

### 4.1 ALEX Presence

- ALEX Core được render thật bằng Canvas 2D, không dùng concept art làm bằng chứng.
- Có 10 trạng thái thị giác:
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
- Idle giữ nhịp chuyển động nhẹ, không chạy hiệu ứng cường độ cao liên tục.
- Command surface ẩn mặc định và chỉ hiện khi wake/listen.
- Có waveform, micro response và context panel.
- Có desktop/mobile layout.
- Có ba chất lượng `performance`, `balanced`, `cinematic`.
- Hỗ trợ `prefers-reduced-motion`.
- Renderer, microphone và polling tạm dừng khi không cần thiết; tài nguyên được cleanup.

### 4.2 ALEX Command Center

- Chuyển Presence ↔ Command Center ngay lập tức, không reload trang.
- 12 workspace đều mở được:
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
- Các khu vực chưa có dữ liệu thật được ghi rõ `NOT VERIFIED`, `PENDING` hoặc bị khóa; không tạo thành công giả.
- Spatial Home mô tả một phòng, không dùng dữ liệu biệt thự hoặc thiết bị không tồn tại.
- Digital twin hiển thị connection, desired/reported state, firmware, RSSI, last seen, command và retry.

### 4.3 Âm thanh

- Chỉ dùng một Web Audio engine.
- Cue được tổng hợp nguyên bản, không dùng âm thanh Iron Man/JARVIS hoặc tài sản có bản quyền.
- Có normal/quiet/night/silent.
- Có master gain, gain theo nhóm, chống cue trùng và ưu tiên cảnh báo.
- Có TTS ducking và xử lý browser autoplay.
- AudioContext chỉ được tạo sau tương tác hợp lệ và được cleanup.

### 4.4 Backend, dữ liệu và realtime

- Giữ backend FastAPI hiện tại, không chuyển framework và không viết lại không cần thiết.
- SQLite schema v2 lưu:
  - command history
  - command transition events
  - desired/reported state
  - device registry
  - heartbeat và timestamps
  - retry, origin và failure reason
- SSE đẩy command lifecycle và node state tới frontend.
- Client tự reconnect có backoff giới hạn và rehydrate bằng REST.
- MQTT client ID đã được sửa thành duy nhất theo process, loại bỏ lỗi hai preview đá kết nối của nhau.
- API v1 được bổ sung theo hướng additive, không phá client v0.3.

### 4.5 Hardware Integration V1

- Luồng lệnh:

  `queued → sending → waiting_ack → accepted → waiting_reported_state → confirmed`

- Có các nhánh `retrying`, `failed`, `timed_out`, `cancelled`.
- Retry tối đa hai lần.
- ACK sai, thiếu ACK, reported state sai hoặc timeout đều không tạo success.
- Simulator hỗ trợ:
  - normal
  - delayed ACK
  - missing ACK
  - wrong state
  - offline
  - high latency
  - duplicate message
- Mọi dữ liệu simulator đều mang `source=simulated` và `hardware_verified=false`.
- Firmware có safe boot `OFF`, reconnect backoff, LWT, heartbeat và cache chống command trùng.

### 4.6 An toàn

- Chỉ LED thử nghiệm điện áp thấp được mở ở V1.
- Relay 1–4 giữ trạng thái `RESTRICTED / NOT VERIFIED`.
- Restricted API trả HTTP `423`.
- Target không hỗ trợ trả HTTP `400`.
- Wake-on-LAN chưa cấu hình trả HTTP `409`.
- Không cho phép vận hành thật UV, tải 220V, bơm, motor hoặc khóa cửa.
- Production không tự fallback sang simulated success.

---

## 5. Kết quả kiểm thử hiện tại

| Hạng mục | Kết quả |
|---|---|
| Typecheck | **PASS** |
| ESLint | **PASS** |
| Frontend tests | **PASS — 21/21** |
| Backend tests | **PASS — 14/14** |
| Production build | **PASS** |
| Python compile | **PASS** |
| State-transition soak | **PASS — 500 vòng** |
| Phase 2 browser acceptance soak | **PASS — 20/20 vòng** |
| API smoke qua Uvicorn | **PASS** |
| MQTT integration qua Mosquitto local | **PASS** |
| Desktop browser smoke | **PASS** |
| Mobile 390×844 | **PASS — không tràn ngang** |
| Presence ↔ Command Center không reload | **PASS** |
| Reduced motion | **PASS** |
| Performance/balanced/cinematic | **PASS** |
| Console sau stable reload | **PASS — 0 warning/error** |
| Restricted action/rate limit | **PASS ở mức phần mềm** |
| Giao tiếp cơ bản ESP8266/test LED | **BASIC PHYSICAL VALIDATION PASS** |
| Full Phase 7 hardware checklist | **ĐANG TIẾP TỤC** |
| Relay/cảm biến/tải thật | **CHƯA KIỂM THỬ** |

---

## 6. Bằng chứng thực tế

Tất cả ảnh và recording dưới đây được tạo từ ứng dụng localhost đang chạy, không phải concept art hoặc ảnh AI tạo sinh.

### Phase 2

- `docs/screenshots/phase-2/acceptance-presence-desktop.png`
- `docs/screenshots/phase-2/acceptance-presence-mobile.png`
- `docs/recordings/phase-2/presence-acceptance-sequence.gif`

### Phase 3

- `docs/screenshots/phase-3/sound-settings-desktop.png`
- `docs/screenshots/phase-3/sound-settings-mobile.png`

### Phase 4–5

- `docs/screenshots/phase-4-5/command-center-spatial-desktop.png`
- `docs/screenshots/phase-4-5/command-center-spatial-mobile.png`

### Hardware V1

- `docs/screenshots/hardware-v1/presence-test-led-confirmed.png`
- `docs/screenshots/hardware-v1/digital-twin-desktop.png`
- `docs/screenshots/hardware-v1/digital-twin-mobile.png`

---

## 7. Phần nào là thật, mô phỏng và chưa xác minh

### Đang chạy thật

- Frontend Presence, Command Center và Spatial Home.
- Canvas renderer và Web Audio engine.
- FastAPI, SQLite, MQTT broker local và SSE.
- Command lifecycle, retry, timeout, event history và digital twin.
- Browser desktop/mobile và PWA shell.

### Chế độ mô phỏng

- Simulator vẫn cung cấp ACK, heartbeat, telemetry và reported state cho các kịch bản lỗi.
- Dữ liệu simulator không nâng mức xác minh của node/capability.
- Một số dữ liệu demo trong workspace khi backend domain tương ứng chưa có nguồn thật.

### Cần quyền microphone

- Waveform lấy dữ liệu microphone thật.
- Nhận dạng giọng nói/STT thực tế.
- Khi không có quyền, UI dùng semantic waveform/fallback và phải ghi rõ trạng thái.

### Cần tiếp tục xác minh với MQTT và phần cứng

- Relay và sensor thật.
- Heartbeat/RSSI/telemetry, ACK/reported state qua power-cycle, reconnect và soak dài hạn.
- Wake-on-LAN cần PC, MAC address và mạng thật.

### Chưa được phép tuyên bố

- Chưa có hạng mục nào được gắn nhãn `hardware verified`.
- Chưa được vận hành tải nguy hiểm.
- Chưa xác minh hệ thống hoạt động dài hạn trên Orange Pi One.

---

## 8. Hạn chế và rủi ro còn lại

1. Full Phase 7 chưa hoàn tất dù giao tiếp cơ bản ESP01/test LED đã được xác nhận.
2. Chưa có soak dài hạn, power-cycle và reconnect matrix đầy đủ trên thiết bị vật lý.
3. Chưa có interlock cứng cho tải nguy hiểm.
4. Restore database chưa đạt mức transaction/rollback production đầy đủ.
5. Auth hiện phù hợp local-first cơ bản, chưa phải mô hình nhiều người dùng hoàn chỉnh.
6. Cần soak dài hạn trên Orange Pi, broker và mạng Wi-Fi thật.
7. Microphone, STT/TTS và system-audio recording chưa được nghiệm thu trên thiết bị đích.
8. Camera, energy meter, security sensor và ALEX Brain chưa có integration vật lý hoàn chỉnh.
9. Cần đo CPU, RAM, FPS, reconnect và dung lượng log trong vận hành 24/7.
10. Không có metadata Git trong repository hiện tại nên chưa có lịch sử commit/release theo chuẩn Git.

---

## 9. Lộ trình phát triển các phase tiếp theo

### Phase 6 Completion — Domain execution hoàn chỉnh

Mục tiêu là biến nền tảng command hiện tại thành hệ thống scene, mission và automation có thể kiểm chứng end-to-end.

Việc cần hoàn thành:

- Chuẩn hóa toàn bộ device registry và capabilities.
- Hoàn thiện scene builder và scene execution theo từng step.
- Hoàn thiện mission sequential/partial/failure semantics.
- Hoàn thiện automation evaluation, condition, blocked reason và history.
- Thêm cancel, timeout và retry policy theo từng loại action.
- Thêm idempotency và duplicate-message test ở mọi tầng.
- Mỗi kết quả phải có command ID, nguồn ACK và failure reason.

Điều kiện PASS:

- Simulator E2E cho ACK đúng, ACK trễ, timeout, disconnect, reconnect và duplicate.
- Không có optimistic false success.
- UI trình bày rõ step nào thành công, thất bại hoặc chưa xác minh.

### Phase 7 Completion — Tích hợp phần cứng thật

Mục tiêu là chuyển `esp01/test_led` từ software verified sang hardware verified trước khi mở thêm thiết bị.

Việc cần hoàn thành:

- Cài PlatformIO và compile firmware.
- Kết nối ESP8266 qua USB, xác định COM và flash firmware.
- Xác minh safe boot OFF, Wi-Fi reconnect, MQTT reconnect và LWT.
- Chạy command ID → ACK → reported state trên LED thật.
- Kiểm tra duplicate command, broker restart, Wi-Fi mất/kết nối lại và power cycle.
- Đo heartbeat, RSSI, latency và timeout trên mạng thật.
- Triển khai thử FastAPI/MQTT/SQLite trên Orange Pi One.
- Kiểm thử Wake-on-LAN với ALEX Brain thật.

Điều kiện PASS:

- Có log và video/ảnh từ thiết bị thật.
- `hardware_verified=true` chỉ được đặt sau checklist vật lý PASS.
- Không mở relay 220V ở phase này nếu chưa có kiểm tra điện và interlock.

### Phase 8 Completion — Security, safety và reliability

Mục tiêu là làm hệ thống đủ an toàn để chạy lâu dài trong mạng gia đình.

Việc cần hoàn thành:

- Hoàn thiện session/auth local-first và quản lý secret bằng environment.
- Áp dụng validation/rate limit cho toàn bộ mutation route.
- Hoàn thiện audit log và log rotation.
- Backup/restore có kiểm tra schema, transaction và rollback.
- Heartbeat watchdog và safe default sau disconnect.
- Safety interlock model, maximum runtime và sensor prerequisite.
- Explicit confirmation cho controlled action.
- Chặn tuyệt đối voice-only activation với UV và thiết bị nguy hiểm.
- Kiểm tra Tailscale-safe deployment.

Điều kiện PASS:

- Restricted action không thể chạy bằng UI shortcut, voice hoặc gọi API thiếu điều kiện.
- Restore lỗi không làm hỏng database đang hoạt động.
- Log và reconnect không tăng vô hạn.

### Phase 9 — Final hardening và acceptance matrix

Mục tiêu là kiểm tra toàn hệ thống như một sản phẩm chạy dài hạn.

Việc cần hoàn thành:

- Unit, API contract, integration và simulator E2E.
- Hardware E2E cho các thiết bị đã được duyệt.
- Offline/reconnect/timeout/broker restart/power-cycle tests.
- Soak dài hạn cho browser, backend, MQTT và firmware.
- Memory, RAF, Canvas, audio, listener và connection cleanup.
- Keyboard, focus, screen-reader label và contrast.
- Desktop, tablet, mobile và ultrawide.
- Reduced motion và ba quality mode.
- PWA offline/update behavior.
- Backup/restore acceptance.
- Console và network phải không còn lỗi critical/high.

Điều kiện PASS:

- Acceptance matrix có bằng chứng rõ ràng.
- Mọi lỗi critical/high được sửa.
- Lỗi medium/low được ghi trong known limitations.

### Phase 10 — Production release và triển khai

Mục tiêu là tạo bản phát hành có thể cài đặt lại và vận hành ổn định.

Việc cần hoàn thành:

- Hoàn thiện `FINAL_REPORT`, `DEPLOYMENT` và `HARDWARE_INTEGRATION`.
- Tạo `.env.example` không chứa secret.
- Hoàn thiện Windows scripts và systemd service cho Orange Pi.
- Tài liệu cài đặt, nâng cấp, rollback, backup và restore bằng tiếng Việt.
- Release notes và known limitations.
- Clean-install test từ ZIP mới.
- Chụp screenshot và quay video cuối từ ứng dụng thật.
- Tạo release package mới trong `dist-release/`.

Điều kiện phát hành:

- Cài sạch PASS.
- Backend/service restart PASS.
- PWA offline PASS.
- Thiết bị được công bố hỗ trợ phải hardware-verified.
- Không chứa `.env`, database, secrets hoặc token trong ZIP.

---

## 10. Thứ tự ưu tiên đề xuất

Ưu tiên tiếp theo không phải thêm giao diện mới. Việc có giá trị nhất là hoàn tất **Phase 7 hardware validation cho `esp01/test_led`**, vì đây là bằng chứng đầu tiên rằng toàn bộ chuỗi UI → API → MQTT → firmware → thiết bị → reported state hoạt động ngoài simulator.

Sau khi LED thật PASS, mới tiếp tục mở từng thiết bị an toàn theo cùng contract. Relay/tải điện áp cao chỉ được đưa vào khi có sơ đồ đấu dây, driver phù hợp, fuse/interlock, safe default và kiểm tra vật lý được ghi lại.

---

## 11. Tài liệu liên quan

- `docs/AUDIT.md`
- `docs/PRODUCT_SPEC.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/MQTT_PROTOCOL_V1.md`
- `docs/REALTIME_PROTOCOL.md`
- `docs/ESP01_FLASH_GUIDE.md`
- `docs/ESP01_TEST_PLAN.md`
- `docs/HARDWARE_INTEGRATION.md`
- `docs/FINAL_REPORT.md`
- `docs/DEPLOYMENT.md`
- `docs/RELEASE_NOTES.md`
- `docs/HARDWARE_V1_SUMMARY.md`

---

## 12. Kết luận cuối

ALEX NEXUS OS MARK III đã vượt qua giai đoạn concept và hiện là một ứng dụng local-first chạy được với giao diện, backend, data store, realtime transport, simulator và một hardware protocol có kiểm chứng ở mức phần mềm.

Phần còn thiếu quan trọng nhất không phải hiệu ứng giao diện mà là bằng chứng trên phần cứng thật, interlock an toàn và kiểm thử vận hành dài hạn. Khi `esp01/test_led` vượt qua Phase 7 trên thiết bị vật lý, dự án sẽ có nền tảng đáng tin cậy để mở rộng sang sensor, đèn, quạt, scene, automation và ALEX Brain mà không đánh đổi tính trung thực hoặc an toàn.
