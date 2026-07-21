# ALEXROOM — Repository Audit

Ngày kiểm kê: 2026-07-21  
Phạm vi: Phase 0, trước khi triển khai nền tảng MARK III Phase 1.

## 1. Kết luận điều hành

Ứng dụng đang chạy thực tế nằm ở thư mục gốc `D:\AlexRoom`, không phải trong các thư mục đóng gói MARK II. Stack hiện tại là FastAPI + Paho MQTT ở backend và HTML/CSS/JavaScript thuần ở frontend. Orange Pi chỉ phục vụ static assets và API; trình duyệt chịu trách nhiệm render.

Không có Git metadata trong `D:\AlexRoom`, không có package manifest ở baseline, và không có bộ test chính thức cho entry point gốc. Hai thư mục `ALEX_NEXUS_OS_MARK_II_v2.0*` là hai bản sao giống nhau theo SHA-256 của các file ứng dụng chính; bản `v2.0.1_FIXED` khác chủ yếu ở script preview Windows. Chúng là gói tham khảo/demo, không được backend gốc mount hoặc import.

Quyết định Phase 1: giữ stack static nhẹ, giữ nguyên backend/API/MQTT gốc, tách frontend thành ES modules có JSDoc type checking, bổ sung state machine và shell MARK III. Không đưa React, Vite, Three.js hoặc dữ liệu demo MARK II vào Phase 1.

## 2. Architecture map

```text
Browser / PWA
├── GET /                           -> static/index.html
├── /static/styles.css + modules    -> Presence + Command Center shell
├── Service Worker /sw.js           -> cache app shell, bỏ qua API
└── HTTP polling (2.5 s baseline)
    ├── /health
    ├── /api/config
    ├── /api/devices/esp01
    ├── /api/system
    └── /api/events
             │
             ▼
FastAPI app.py (Alex Core / Orange Pi)
├── API-key guard cho mutation
├── config.json ghi atomic
├── in-memory device state + event deque
├── Linux system metrics + Tailscale lookup
└── Paho MQTT client
             │
             ▼
MQTT broker 127.0.0.1:1883
└── alex/device/esp01
    ├── availability
    └── switch/relay_1..4/{command,state}
             │
             ▼
ESPHome ESP8266
├── esp01: 4 relay, restore ALWAYS_OFF
└── esp02: cảm biến độ ẩm số (chưa được backend gốc subscribe)
```

## 3. Stack được phát hiện

| Lớp | Stack thật | Trạng thái |
|---|---|---|
| Backend | Python, FastAPI, Pydantic | Entry point chính: `app.py` |
| MQTT | Paho MQTT, topic ESPHome | ESP01 được nối; cần broker/credential thật |
| Frontend baseline | HTML/CSS/JS thuần, một file mỗi loại | Chạy trực tiếp, không bundler |
| PWA | Web manifest + service worker cache-first fallback | Có app shell offline; API không cache |
| Persistence | `config.json`, memory state/event deque, sessionStorage | Chưa có SQLite/IndexedDB |
| Telemetry | HTTP polling | Chưa có WebSocket/SSE |
| Firmware | ESPHome YAML | ESP01 relay + ESP02 soil dry |
| Tests baseline | Không có test cho thư mục gốc | Chỉ bản MARK II đóng gói có smoke scripts |
| Source control | Không có `.git` ở `D:\AlexRoom` | Không thể dùng diff/history để phục hồi |

## 4. Entry points, routes và components hiện tại

### Backend routes được bảo tồn

| Method | Route | Mục đích | Auth |
|---|---|---|---|
| GET | `/` | Serve dashboard | Không |
| GET | `/manifest.webmanifest`, `/sw.js` | PWA assets | Không |
| GET | `/api/info` | Tên/version backend | Không |
| GET | `/health` | API/MQTT/ESP01/last-seen | Không |
| GET | `/api/auth/verify` | Kiểm tra API key | Có |
| GET/PUT | `/api/config` | Tên phòng và relay | PUT có auth |
| GET | `/api/devices/esp01` | Reported relay/mode state | Không |
| GET | `/api/system` | RAM/disk/load/temp/uptime/Tailscale | Không |
| GET | `/api/events` | Event deque gần nhất | Không |
| POST | `/api/devices/esp01/relays/{id}/{action}` | Publish relay command | Có |
| POST | `/api/devices/esp01/relays-all/{action}` | Publish 4 relay commands | Có |
| POST | `/api/modes` | Đổi home/away/sleep/study | Có |

### Frontend baseline

Không có client-side router hoặc component framework. `static/index.html` chứa một dashboard với sidebar và các anchor section: overview, devices, modes, system, activity. `static/app.js` trực tiếp query DOM, poll năm endpoint, render bốn relay, metrics và event log. Login overlay che toàn bộ ứng dụng khi chưa có key.

### Gói MARK II tham khảo

`ALEX_NEXUS_OS_MARK_II_v2.0.1_FIXED/ALEX_NEXUS_MARK_II` có Presence/Command Center demo, Canvas 2D Core, 9 workspace và FastAPI mở rộng. Nó không phải entry point chính và không được merge vì:

- hard-code 8 thiết bị và dữ liệu phòng không được xác minh;
- thiếu Missions, Cameras và System workspace theo spec mới;
- nhiều thao tác demo đổi state thành công ngay, không chờ ACK;
- energy, security, ALEX Brain, scene và automation chủ yếu là LocalStorage/demo;
- plant pump xuất hiện như thiết bị điều khiển dù chưa có safety interlock;
- backend mở rộng chưa có SQLite, ACK correlation hoặc hardware verification.

Các ý tưởng có thể tái sử dụng sau audit: hai-mode shell, Canvas lifecycle pause, API base setting, test structure, PWA packaging. Dữ liệu và success semantics không được tái sử dụng nguyên trạng.

## 5. Data flow và command semantics

### Read path

Frontend baseline gọi song song `/health`, `/api/config`, `/api/devices/esp01`, `/api/system`, `/api/events` mỗi 2.5 giây. Backend giữ reported state trong memory; callback MQTT cập nhật `availability`, `last_seen` và relay state.

### Write path

Frontend gửi `X-Alex-Key`. Backend kiểm tra MQTT connected, publish QoS 0, rồi trả `{accepted: true}`. Đây chỉ là xác nhận API đã chấp nhận publish, không phải xác nhận relay vật lý đã đổi. Baseline UI hiện thông báo thành công ngay sau phản hồi HTTP, sau đó poll lại sau 250–350 ms. Đây là sai lệch quan trọng so với yêu cầu honest state.

Phase 1 bổ sung lifecycle phía client: `queued -> sending -> waiting_ack -> confirmed|failed|timed_out|cancelled`. `confirmed` chỉ xuất hiện khi `/api/devices/esp01` trả reported state mong muốn. Backend contract không đổi.

## 6. API/MQTT integration status

### Đang hoạt động ở mức mã nguồn

- API-key guard cho mutation.
- Atomic config save bằng temp file + replace.
- MQTT reconnect delay.
- Subscribe availability và state của bốn relay ESP01.
- ESPHome relay dùng `restore_mode: ALWAYS_OFF`.
- Away/Sleep gửi OFF cho cả bốn relay.
- Service worker không cache API/health.
- MQTT client ID mặc định được tạo ngắn, duy nhất theo host/process; có thể khóa bằng `MQTT_CLIENT_ID`. Cách này ngăn hai preview local dùng chung `alex-core-api` liên tục đá nhau khỏi broker.

### Chưa được xác minh phần cứng

- Broker Mosquitto trên Orange Pi.
- Credential MQTT/API key thật.
- Bốn relay và tải điện thật.
- ESP02 heartbeat/soil sensor trong backend.
- ACK correlation, retry, retained-state freshness và command timeout ở server.
- Wake-on-LAN, SQLite, Tailscale deployment, watchdog và backup.

### Rủi ro an toàn

- `esphome/secrets.yaml` tồn tại trong workspace; không được đọc, log hoặc đưa vào gói phát hành.
- Fallback AP passwords đang được ghi trực tiếp trong YAML ESPHome.
- Không có model risk level/interlock phía backend.
- Relay chỉ là số 1–4; chưa có metadata chứng minh tải nào an toàn.
- QoS 0 và `{accepted:true}` không chứng minh tác động vật lý.

## 7. Build, test và preview commands

### Baseline được phát hiện

- Static preview cũ: `python -m http.server 5173` trong thư mục gói UI.
- Backend MARK II đóng gói: `uvicorn app:app --host 0.0.0.0 --port 5173` sau khi cài `requirements.txt`.
- Entry point gốc không có `requirements.txt`, start script, build, lint, typecheck hoặc test command.
- Syntax baseline đã kiểm tra: `python -m py_compile app.py` và `node --check static/app.js` đều PASS.
- MARK II `tests/static_checks.py` PASS; backend smoke không chạy trong runtime ban đầu vì thiếu FastAPI package.

### Tooling chuẩn hóa trong Phase 1

Sau Phase 1, các lệnh chuẩn ở thư mục gốc là:

```powershell
npm install
npm run build
npm run typecheck
npm run lint
npm test
```

Preview production-like vẫn dùng FastAPI để kiểm tra đúng route/API/PWA:

```powershell
$env:MQTT_PASSWORD="<local-preview>"
$env:ALEX_API_KEY="<local-preview>"
python -m uvicorn app:app --host 127.0.0.1 --port 5173
```

## 8. Visual gap analysis

| Hướng MARK III | UI gốc hiện tại | Nguyên nhân khoảng cách |
|---|---|---|
| Presence calm, Core ở trung tâm | Sidebar + dashboard card luôn hiện | Information architecture sai ngay từ shell |
| Nội dung reveal-on-demand | Mọi metric/relay/log cùng hiển thị | Không có context levels |
| Core state-driven | Logo chữ A tĩnh | Không có visual state model |
| Motion có causal meaning | Hover/transition chung | Không có state timeline/orchestration |
| Command Center chuyên sâu | 5 anchor section trên một trang | Không có synchronized mode/workspace state |
| Premium graphite/navy/cyan | Gradient tím-xanh SaaS phổ biến | Token không theo ALEX identity |
| Honest device state | HTTP accepted được gọi là success | Thiếu lifecycle/ACK model |
| Responsive Presence mobile | Sidebar đổi thành horizontal nav | Mobile vẫn là dashboard |
| Adaptive quality/reduced motion | Chỉ CSS transition cơ bản | Không có quality model hoặc media handling |

Ngoài ra, MARK II demo cố đưa quá nhiều workspace và dữ liệu mô phỏng vào một file JS ~84 KB và CSS minified ~52 KB. Điều này làm giao diện dày, khó kiểm soát fidelity, khó test từng trạng thái và dễ tạo cảm giác concept hơn là sản phẩm thật.

## 9. Technical debt

- Frontend baseline là một global script, không có module boundary hoặc domain model.
- Backend gốc gần 500 dòng, state/persistence/MQTT/API cùng một file.
- Không có SQLite, migration, event durability hoặc bounded log trên disk.
- Không có WebSocket/SSE; polling tải năm endpoint liên tục.
- Không có API contract schema phía frontend.
- Không có abort/timeout cho fetch baseline.
- Không có command correlation ID.
- Không có route state/history cho Command Center.
- Không có test gốc, CI hoặc source history.
- PWA icon chỉ SVG; mức hỗ trợ install phụ thuộc trình duyệt.
- Service worker baseline không xử lý navigation fallback/version notification.
- ESP build artifacts và `.venv` nằm trong workspace, làm audit/search nặng.

## 10. Risks và mitigation order

1. **False success / safety:** ưu tiên lifecycle + reported-state confirmation trước mở rộng control.
2. **Không có Git history:** giữ change set nhỏ, không đụng backend trong Phase 1.
3. **Demo data lẫn production:** không nhập DEFAULT_STATE của MARK II.
4. **Low-power client:** CSS shell nhẹ ở Phase 1; Three/WebGL chỉ đánh giá ở Phase 2.
5. **Service-worker stale cache:** bump cache version khi đổi assets và kiểm tra reload.
6. **Secrets:** không đưa `esphome/secrets.yaml` vào docs/log/build output.
7. **Hardware ambiguity:** ghi rõ mọi preview hiện tại là local/simulated nếu không có broker và ESP thật.

## 11. Files safe to refactor trong Phase 1

- `static/index.html`
- `static/styles.css` và các stylesheet mới dưới `static/styles/`
- `static/app.js` và modules mới dưới `static/core/`, `static/ui/`
- `static/sw.js`
- `static/manifest.webmanifest`
- tài liệu và test/tooling mới ở `docs/`, `tests/`, `scripts/`

## 12. Files phải bảo tồn

- `app.py`: giữ nguyên route contract, auth, config và MQTT behavior trong Phase 1. Chỉ thêm fallback `load_average` cho Windows preview; Orange Pi/Linux vẫn dùng `os.getloadavg()` thật.
- `esphome/esp01.yaml`, `esphome/esp02.yaml`: hardware config; không sửa khi chưa kiểm tra thiết bị.
- `esphome/secrets.yaml`: không đọc/ghi/đưa vào output.
- Các thư mục `ALEX_NEXUS_UI_v0.4` và `ALEX_NEXUS_OS_MARK_II_v2.0*`: nguồn tham khảo/lịch sử; không xóa hoặc deploy đè.
- `static/icon.svg`: giữ asset nhận diện hiện tại cho đến phase branding/icon riêng.

## 13. Implementation order sau audit

1. Phase 1: tokens, state machines, quality/reduced motion, synchronized shells, test/tooling.
2. Phase 2: Core production và Presence interaction fidelity.
3. Phase 3: sound engine nguyên bản.
4. Phase 4 trở đi: Command Center workspaces, Spatial Home thật, command/backend/hardware integration.
