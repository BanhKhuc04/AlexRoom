# ALEX STEP 2.1 — Orange Pi Production Deployment Audit

**Thời điểm audit:** 2026-07-21  
**Môi trường thực tế:** Orange Pi One · Armbian/Debian · user `vanhkhuc`  
**Repository:** D:\AlexRoom (commit fa5c02b, working tree clean)

---

## A. Kiến trúc triển khai hiện tại

### Cách chạy thủ công hiện tại (đang hoạt động)

```
/opt/alex/AlexRoom-0.2.0-hardware-rc/
├── app.py, alex_*.py
├── static/
├── .venv/
├── data/          (không dùng — DB ở /var/lib/alex/)
└── backups/       (vẫn nằm bên trong project dir)

/etc/alex/alex.env       (secrets, mode 0600)
/var/lib/alex/alex.db    (SQLite production)
```

Khởi động thủ công:
```bash
cd /opt/alex/AlexRoom-0.2.0-hardware-rc
source .venv/bin/activate
set -a; source /etc/alex/alex.env; set +a
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

Mosquitto chạy độc lập như system service.

### Tệp service trong repository

`deploy/alex-core.service` — 22 dòng — được kiểm tra bên dưới.

---

## B. Các vấn đề trong `deploy/alex-core.service`

Đây là nội dung **hiện tại** trong file:

```ini
[Unit]
Description=ALEX NEXUS OS local control plane
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
User=alex                                           ← VẤN ĐỀ 1
Group=alex                                          ← VẤN ĐỀ 2
WorkingDirectory=/opt/alexroom                      ← VẤN ĐỀ 3
EnvironmentFile=/etc/alexroom/alex.env              ← VẤN ĐỀ 4
ExecStart=/opt/alexroom/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 5173   ← VẤN ĐỀ 5 và 6
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/alexroom/data /opt/alexroom/backups /opt/alexroom/config.json   ← VẤN ĐỀ 7

[Install]
WantedBy=multi-user.target
```

### Bảng vấn đề chi tiết

| # | Trường | Giá trị hiện tại | Giá trị đúng | Mức độ |
|---|---|---|---|---|
| **P1** | `User` | `alex` | `vanhkhuc` | 🔴 CRITICAL — user không tồn tại |
| **P2** | `Group` | `alex` | `vanhkhuc` | 🔴 CRITICAL — group không tồn tại |
| **P3** | `WorkingDirectory` | `/opt/alexroom` | `/opt/alex/AlexRoom-0.2.0-hardware-rc` | 🔴 CRITICAL — path sai |
| **P4** | `EnvironmentFile` | `/etc/alexroom/alex.env` | `/etc/alex/alex.env` | 🔴 CRITICAL — path sai, secrets không load |
| **P5** | `ExecStart` (binary) | `/opt/alexroom/.venv/bin/python -m uvicorn` | `/opt/alex/AlexRoom-0.2.0-hardware-rc/.venv/bin/uvicorn` | 🔴 CRITICAL — path sai |
| **P6** | `ExecStart` (port) | `--port 5173` | `--port 8000` | 🔴 CRITICAL — port sai (app chạy ở 8000) |
| **P7** | `ReadWritePaths` | `/opt/alexroom/data /opt/alexroom/backups /opt/alexroom/config.json` | Cần cập nhật paths, thêm `/var/lib/alex` | 🔴 CRITICAL — ProtectSystem=strict sẽ chặn ghi DB |

### Vấn đề bổ sung trong service

| # | Trường | Giá trị hiện tại | Đề xuất | Mức độ |
|---|---|---|---|---|
| **P8** | `ExecStart` (`--workers`) | không có | `--workers 1` | 🟡 Nhỏ — uvicorn mặc định 1 worker; nên ghi rõ ràng |
| **P9** | `After` | `mosquitto.service` | Đã đúng | ✅ |
| **P10** | `ProtectSystem=strict` | có | Phù hợp, nhưng phải đảm bảo ReadWritePaths đầy đủ | ⚠️ Xem P7 |
| **P11** | `StandardOutput`/`StandardError` | không khai báo | Để mặc định journald — đây là hành vi đúng | ✅ |

---

## C. Vấn đề dependency cho Orange Pi

### `requirements.txt` hiện tại

```
fastapi>=0.115,<1.0
uvicorn[standard]>=0.34,<1.0    ← VẤN ĐỀ NGHIÊM TRỌNG
paho-mqtt>=2.1,<3.0
pydantic>=2.10,<3.0
```

### Vấn đề

`uvicorn[standard]` kéo theo:
- `uvloop` — C extension, cần biên dịch từ source trên ARMv7
- `httptools` — C extension, tương tự
- `websockets` hoặc `wsproto` — không cần cho app này

**Trên Orange Pi One (RAM ~512MB):** quá trình pip compile `uvloop` từ source đã bị **OOM-killed** theo mô tả từ người dùng. Đây là lỗi đã được xác nhận.

### `requirements-orangepi.txt`

**Không tồn tại** trong repository. Chưa có file dependency riêng cho production ARMv7.

### Dependency cần cho Orange Pi

```
fastapi>=0.115,<1.0
uvicorn>=0.34,<1.0           ← KHÔNG có [standard]
paho-mqtt>=2.1,<3.0
pydantic>=2.10,<3.0
```

> `uvicorn` (không có extra) dùng asyncio event loop mặc định của Python — hoàn toàn đủ cho app này và không cần biên dịch C extension.

### Không có uvloop trong app

Đã kiểm tra toàn bộ repository: **không có reference nào đến `uvloop`** trong `app.py`, `alex_*.py`, hoặc bất kỳ file Python nào. App không yêu cầu uvloop để hoạt động.

---

## D. Tương thích biến môi trường

### Bảng đối chiếu: `.env.example` ↔ `app.py` ↔ `/etc/alex/alex.env`

| Biến trong `app.py` | Biến trong `.env.example` | Khớp? |
|---|---|---|
| `ALEX_DATABASE_PATH` | `ALEX_DATABASE_PATH` | ✅ |
| `MQTT_HOST` | `MQTT_HOST` | ✅ |
| `MQTT_PORT` | `MQTT_PORT` | ✅ |
| `MQTT_USERNAME` | `MQTT_USERNAME` | ✅ |
| `MQTT_PASSWORD` | `MQTT_PASSWORD` | ✅ |
| `MQTT_CLIENT_ID` | `MQTT_CLIENT_ID` (commented) | ✅ (optional) |
| `ALEX_API_KEY` | `ALEX_API_KEY` | ✅ |
| `ALEX_SIMULATOR` | `ALEX_SIMULATOR` | ✅ |
| `ALEX_MUTATION_RATE_LIMIT` | `ALEX_MUTATION_RATE_LIMIT` | ✅ |
| `ALEX_BRAIN_MAC` | `ALEX_BRAIN_MAC` | ✅ |
| `ALEX_BRAIN_HOST` | `ALEX_BRAIN_HOST` | ✅ |
| `ALEX_BRAIN_PORT` | `ALEX_BRAIN_PORT` | ✅ |
| `ALEX_SIMULATOR_SCENARIO` | — (không có trong example) | ⚠️ Minor — chỉ dùng cho dev |

**Tất cả biến quan trọng khớp giữa `app.py` và `.env.example`.**

### Cơ chế guard trong `app.py`

```python
if not MQTT_PASSWORD:
    raise RuntimeError("Thiếu biến môi trường MQTT_PASSWORD")

if not ALEX_API_KEY:
    raise RuntimeError("Thiếu biến môi trường ALEX_API_KEY")
```

Nếu `EnvironmentFile` không load được (do P4), service sẽ crash ngay khi khởi động với `RuntimeError`. Điều này tốt cho bảo mật (không bao giờ chạy không có credentials) nhưng cần path đúng.

### Kiểm tra secret bị commit

- `.gitignore` bảo vệ: `data/*.db*`, `backups/*.db`, `esphome/secrets.yaml`
- `.env` file **không có trong `.gitignore`** nhưng không có `.env` file thật trong repo — chỉ có `.env.example`
- `release.ps1` lọc ra `secrets.yaml`, `.db` và `.env` trước khi tạo ZIP

> **Không có secret nào bị commit.** Tuy nhiên, nên thêm `.env` vào `.gitignore` như một biện pháp phòng ngừa.

### systemd EnvironmentFile loading

Systemd sẽ đọc `EnvironmentFile=/etc/alex/alex.env` và set tất cả biến trước khi exec. Cú pháp `KEY=value` trong file alex.env tương thích với systemd (không dùng `export`, không có `set -a`). Các dấu nháy có thể cần chú ý — nếu value có dấu nháy đơn thì cần kiểm tra.

---

## E. SQLite — path, permission, và migration

### Đường dẫn production thực tế

```
ALEX_DATABASE_PATH=/var/lib/alex/alex.db
```

### Cách `app.py` xử lý path

```python
DATABASE_PATH = Path(os.getenv("ALEX_DATABASE_PATH", str(BASE_DIR / "data" / "alex.db")))
```

Nếu biến môi trường được set đúng, database sẽ dùng `/var/lib/alex/alex.db`. ✅

### Migration tự động khi khởi động

```python
# trong lifespan():
store.migrate()
```

```python
# trong AlexStore.migrate():
self.path.parent.mkdir(parents=True, exist_ok=True)
```

`mkdir(parents=True, exist_ok=True)` sẽ cố tạo `/var/lib/alex/` nếu chưa có. **Điều này chỉ thành công nếu user `vanhkhuc` có quyền ghi lên `/var/lib/alex/` hoặc thư mục đã tồn tại với ownership đúng.**

### Vấn đề permission tiềm năng

| Điều kiện | Hành vi |
|---|---|
| `/var/lib/alex/` chưa tồn tại, user không có quyền tạo | App crash khi `migrate()` gọi `mkdir()` |
| `/var/lib/alex/` tồn tại, owned by root, user không có quyền ghi | App crash khi mở SQLite |
| `/var/lib/alex/` tồn tại, owned by `vanhkhuc` | ✅ Hoạt động bình thường |

**Cần đảm bảo** trước khi enable service:
```bash
sudo mkdir -p /var/lib/alex
sudo chown vanhkhuc:vanhkhuc /var/lib/alex
sudo chmod 750 /var/lib/alex
```

### `ReadWritePaths` và `ProtectSystem=strict`

Hiện tại `ReadWritePaths` chỉ liệt kê paths bên trong `/opt/alexroom` (path cũ). Cần thêm:
- `/var/lib/alex` (SQLite production)
- `/opt/alex/AlexRoom-0.2.0-hardware-rc/backups` (backup files)
- `/opt/alex/AlexRoom-0.2.0-hardware-rc/config.json` (config updates)

### Backup path

```python
# trong app.py:
destination = BASE_DIR / "backups" / f"alex-{stamp}.db"
```

`BASE_DIR` = thư mục của `app.py` = `/opt/alex/AlexRoom-0.2.0-hardware-rc`. Backup sẽ được ghi vào:
```
/opt/alex/AlexRoom-0.2.0-hardware-rc/backups/
```

Đây cần có trong `ReadWritePaths`.

---

## F. MQTT — startup và reconnect

### Cơ chế hiện tại

```python
# Khởi tạo ngoài lifespan — chạy ngay khi module load:
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

# Trong lifespan:
mqtt_client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
mqtt_client.loop_start()
```

### Phân tích kịch bản khởi động

| Kịch bản | Hành vi |
|---|---|
| **Orange Pi boot, Mosquitto đã chạy** | `connect_async()` kết nối nhanh. `on_connect` set `mqtt_connected`, subscribe topics. Bình thường. |
| **ALEX khởi động trước Mosquitto** | `connect_async()` thất bại. Paho **tự động retry** với backoff (1→30s) qua `loop_start()` thread. Không crash. Khi Mosquitto sẵn sàng, kết nối tự phục hồi. |
| **Mosquitto crash và restart** | `on_disconnect` gọi, `mqtt_connected.clear()`. Paho tự reconnect qua backoff. |
| **ALEX crash** | systemd `Restart=on-failure` khởi động lại. `command_service.start()` gọi `store.fail_pending_commands("backend_restarted")`. |
| **SIGTERM từ systemd** | FastAPI lifespan `yield` hoàn thành: stop simulator → stop scheduler → stop command_service → disconnect MQTT → loop_stop. Shutdown sạch. |

### Dependency `After=mosquitto.service`

Service unit đã có `After=mosquitto.service`. Điều này đảm bảo systemd khởi động ALEX **sau** Mosquitto. Tuy nhiên, "after" không đồng nghĩa Mosquitto đã accept connections — Paho's built-in reconnect xử lý gap này.

### `Wants` vs `Requires`

Hiện có `Wants=network-online.target`. Đây là cấu hình đúng — ALEX có thể chạy offline (phục vụ UI local) và reconnect khi network có.

### Đánh giá tổng

MQTT startup/reconnect **đã được xử lý đúng ở mức code**. Không cần thay đổi logic. Vấn đề duy nhất là path trong service file (P3, P4) ngăn service chạy được.

---

## G. Logging và restart policy

### Logging hiện tại

App dùng `print()` cho MQTT events và FastAPI/uvicorn tự log qua stderr. Khi chạy dưới systemd, tất cả stdout/stderr tự động vào **journald**.

```bash
# Xem logs:
journalctl -u alex-core -f
journalctl -u alex-core --since "1 hour ago"
```

Đây là cấu hình đơn giản và đúng cho production đầu tiên. **Không cần thêm logging infrastructure**.

### Audit events

App có thêm `store.add_audit()` ghi structured events vào SQLite. Đây là audit trail riêng, bổ sung (không thay thế) journald.

### Restart policy

```ini
Restart=on-failure
RestartSec=5
```

**Đánh giá:** Đây là policy phù hợp.
- `on-failure`: restart khi exit code != 0 hoặc bị signal không mong muốn
- Không restart nếu `systemctl stop` hoặc SIGTERM (shutdown sạch từ systemd)
- `RestartSec=5`: buffer 5 giây trước khi restart, tránh vòng crash nhanh

**Không cần thay đổi restart policy.**

### Giới hạn restart

Nên thêm `StartLimitIntervalSec` và `StartLimitBurst` để tránh systemd restart vô tận nếu app liên tục crash (ví dụ thiếu biến môi trường):

```ini
StartLimitIntervalSec=60
StartLimitBurst=5
```

Đây là khuyến nghị, không bắt buộc ngay cho Step 2.2.

---

## H. Danh sách file cần thay đổi trong Step 2.2

> **Nguyên tắc:** Chỉ thay đổi những gì cần thiết để service hoạt động đúng. Không refactor code.

### Bắt buộc

| File | Thay đổi |
|---|---|
| `deploy/alex-core.service` | Sửa User, Group, WorkingDirectory, EnvironmentFile, ExecStart (path + port), ReadWritePaths |
| `requirements.txt` **HOẶC** tạo `requirements-orangepi.txt` mới | Loại bỏ `uvicorn[standard]`, dùng `uvicorn` thuần |

### Khuyến nghị

| File | Thay đổi |
|---|---|
| `docs/DEPLOYMENT.md` | Cập nhật paths từ `/opt/alexroom` → `/opt/alex/AlexRoom-0.2.0-hardware-rc`, port 5173 → 8000, user alex → vanhkhuc |
| `.gitignore` | Thêm `.env` để phòng ngừa accident |

### Không cần thay đổi

- `app.py` — code đúng, chỉ cần env vars đúng
- `alex_store.py` — migration logic đúng
- `alex_hardware.py` — MQTT logic đúng
- Tất cả backend/frontend logic

---

## I. Thiết kế triển khai production tối giản (đề xuất)

### `deploy/alex-core.service` sau khi sửa

```ini
[Unit]
Description=ALEX NEXUS OS local control plane
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
User=vanhkhuc
Group=vanhkhuc
WorkingDirectory=/opt/alex/AlexRoom-0.2.0-hardware-rc
EnvironmentFile=/etc/alex/alex.env
ExecStart=/opt/alex/AlexRoom-0.2.0-hardware-rc/.venv/bin/uvicorn \
    app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/alex/AlexRoom-0.2.0-hardware-rc/backups \
    /opt/alex/AlexRoom-0.2.0-hardware-rc/config.json \
    /var/lib/alex

[Install]
WantedBy=multi-user.target
```

### `requirements-orangepi.txt` (file mới, không thay đổi `requirements.txt`)

```
fastapi>=0.115,<1.0
uvicorn>=0.34,<1.0
paho-mqtt>=2.1,<3.0
pydantic>=2.10,<3.0
```

> `requirements.txt` giữ nguyên cho môi trường dev Windows (uvicorn[standard] không gây OOM ở đây).

### Thứ tự setup trên Orange Pi (trước khi enable service)

```bash
# 1. Đảm bảo thư mục DB tồn tại và có ownership đúng
sudo mkdir -p /var/lib/alex
sudo chown vanhkhuc:vanhkhuc /var/lib/alex
sudo chmod 750 /var/lib/alex

# 2. Đảm bảo /etc/alex/ tồn tại với permission đúng (đã có nếu alex.env đang dùng)
sudo chmod 0600 /etc/alex/alex.env
sudo chown root:vanhkhuc /etc/alex/alex.env

# 3. Cài dependencies ARMv7-safe vào .venv
cd /opt/alex/AlexRoom-0.2.0-hardware-rc
.venv/bin/pip install -r requirements-orangepi.txt

# 4. Copy service file
sudo cp deploy/alex-core.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable alex-core
sudo systemctl start alex-core

# 5. Kiểm tra
sudo systemctl status alex-core
journalctl -u alex-core -f
```

---

## J. Rủi ro trước khi cài đặt

| Rủi ro | Mức | Biện pháp |
|---|---|---|
| `User=alex` không tồn tại → service không start | 🔴 Critical | Sửa service file (Step 2.2) |
| Path `/opt/alexroom` không tồn tại → service crash | 🔴 Critical | Sửa service file (Step 2.2) |
| `EnvironmentFile` path sai → secrets không load → app crash với RuntimeError | 🔴 Critical | Sửa service file (Step 2.2) |
| Port 5173 thay vì 8000 → UI không truy cập được | 🔴 Critical | Sửa service file (Step 2.2) |
| `uvicorn[standard]` → pip OOM khi cài lại | 🔴 Critical | Tạo requirements-orangepi.txt (Step 2.2) |
| `/var/lib/alex` chưa tồn tại → migration crash | 🔴 Critical | Cần tạo thủ công trước khi enable service |
| `ProtectSystem=strict` + ReadWritePaths cũ → SQLite write blocked | 🔴 Critical | Sửa ReadWritePaths (Step 2.2) |
| `backup` endpoint ghi vào `BASE_DIR/backups` → cần nằm trong ReadWritePaths | 🟡 Trung bình | Đã tính vào thiết kế I |
| `config.json` update qua `/api/config` → cần ReadWritePaths | 🟡 Trung bình | Đã tính vào thiết kế I |
| Paho MQTT client ID mặc định = `sha256(hostname:pid)[:10]` — stable qua restart | ✅ OK | Mỗi lần restart PID thay đổi nhưng logic đã handle |
| `MQTT_CLIENT_ID` production nên được set cố định | 🟡 Khuyến nghị | Set trong `/etc/alex/alex.env` |

### Rủi ro KHÔNG liên quan đến Step 2.2

- Relay hardware: vẫn RESTRICTED, không bị ảnh hưởng bởi deployment
- CapabilityRegistry: không thay đổi, relay vẫn bị chặn sau deploy
- MQTT auth: Mosquitto đã có auth, không cần thay đổi
- Phase 7: vẫn ongoing, deployment không thay đổi verification status

---

## Tóm tắt điều hành

**`deploy/alex-core.service` hiện tại không thể hoạt động** trong môi trường production thực tế — có 7 lỗi critical (User, Group, WorkingDirectory, EnvironmentFile, ExecStart path, ExecStart port, ReadWritePaths). Tất cả cần được sửa trong Step 2.2.

**`requirements.txt` có `uvicorn[standard]`** sẽ gây OOM khi pip cài trên ARMv7. Cần `requirements-orangepi.txt` riêng.

**App code** (`app.py`, `alex_store.py`, tất cả `alex_*.py`) **không cần thay đổi** — logic đúng và sẽ hoạt động bình thường khi environment vars được set đúng.

**Không có secret nào bị commit.**
