# Triển khai ALEX NEXUS OS — Orange Pi One Production

## Tổng quan môi trường

| Mục | Giá trị |
|---|---|
| Thiết bị | Orange Pi One (ARMv7, ~512 MB RAM) |
| Hostname | orangepione |
| OS | Armbian / Debian stable |
| Linux user | `vanhkhuc` |
| Linux group | `vanhkhuc` |
| Project path | `/opt/alex/AlexRoom-0.2.0-hardware-rc` |
| Virtual environment | `/opt/alex/AlexRoom-0.2.0-hardware-rc/.venv` |
| Environment secrets | `/etc/alex/alex.env` |
| SQLite database | `/var/lib/alex/alex.db` |
| HTTP port | `8000` |
| MQTT broker | Mosquitto system service (chạy độc lập) |
| UI URL | `http://192.168.0.174:8000` |

---

## 1. Chuẩn bị môi trường (chạy một lần trước lần đầu enable service)

### 1.1 Tạo thư mục SQLite

App tự tạo database khi migration chạy, nhưng **thư mục cha phải tồn tại trước**
và được owned bởi user service:

```bash
sudo mkdir -p /var/lib/alex
sudo chown vanhkhuc:vanhkhuc /var/lib/alex
sudo chmod 750 /var/lib/alex
```

### 1.2 Tạo thư mục backup (nếu chưa có)

Endpoint `POST /api/v1/backup` ghi vào thư mục `backups/` bên trong project:

```bash
mkdir -p /opt/alex/AlexRoom-0.2.0-hardware-rc/backups
```

Thư mục này phải writable bởi `vanhkhuc`. Nếu project được copy bởi root,
đặt lại ownership:

```bash
sudo chown -R vanhkhuc:vanhkhuc /opt/alex/AlexRoom-0.2.0-hardware-rc
```

### 1.3 Tạo environment file secrets

Tạo `/etc/alex/alex.env` với nội dung theo `.env.example`.
**Không commit file này vào Git.**

```bash
sudo mkdir -p /etc/alex
sudo touch /etc/alex/alex.env
sudo chown root:vanhkhuc /etc/alex/alex.env
sudo chmod 640 /etc/alex/alex.env
```

> **Lý do `640` thay vì `600`:** Service chạy với user `vanhkhuc`.
> Nếu file thuộc về `root:vanhkhuc` với mode `640`, user `vanhkhuc` đọc được
> qua group permission. Mode `600` với owner `root` sẽ khiến `vanhkhuc` không
> đọc được và service không start.

Chỉnh sửa file bằng `sudo`:

```bash
sudo nano /etc/alex/alex.env
```

Nội dung mẫu (thay thế giá trị thật):

```
ALEX_API_KEY=replace-with-a-long-random-key
MQTT_HOST=127.0.0.1
MQTT_PORT=1883
MQTT_USERNAME=alex_core
MQTT_PASSWORD=replace-with-broker-password
MQTT_CLIENT_ID=alex-core-orange-pi
ALEX_SIMULATOR=0
ALEX_MUTATION_RATE_LIMIT=30
ALEX_DATABASE_PATH=/var/lib/alex/alex.db
ALEX_BRAIN_MAC=
ALEX_BRAIN_HOST=
ALEX_BRAIN_PORT=22
```

> `MQTT_CLIENT_ID` nên được set cố định trong production để client ID ổn định
> qua các lần restart (tránh MQTT session accumulation).

---

## 2. Cài đặt Python dependencies trên Orange Pi

**QUAN TRỌNG:** Không dùng `requirements.txt` (chứa `uvicorn[standard]`) trên Orange Pi.
`uvicorn[standard]` kéo `uvloop` và `httptools` cần biên dịch C — gây OOM-killed
trên Orange Pi One với RAM hạn chế.

Dùng `requirements-orangepi.txt`:

```bash
cd /opt/alex/AlexRoom-0.2.0-hardware-rc
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-orangepi.txt
```

`requirements-orangepi.txt` chứa `uvicorn` thuần (không có extra), dùng
Python asyncio event loop mặc định — đủ cho ứng dụng single-worker này.

---

## 3. Cài đặt systemd service

```bash
# Copy service file vào systemd
sudo cp /opt/alex/AlexRoom-0.2.0-hardware-rc/deploy/alex-core.service \
    /etc/systemd/system/alex-core.service

# Reload systemd để nhận service mới
sudo systemctl daemon-reload

# Enable service — tự start khi boot
sudo systemctl enable alex-core

# Start service ngay lập tức
sudo systemctl start alex-core
```

---

## 4. Kiểm tra service

```bash
# Xem trạng thái service
sudo systemctl status alex-core

# Xem logs realtime
journalctl -u alex-core -f

# Xem logs từ 1 giờ trước
journalctl -u alex-core --since "1 hour ago"

# Xem logs từ lần boot hiện tại
journalctl -u alex-core -b
```

---

## 5. Quản lý service

```bash
# Dừng service
sudo systemctl stop alex-core

# Restart service (dùng sau khi update code)
sudo systemctl restart alex-core

# Disable service (không start khi boot)
sudo systemctl disable alex-core

# Xem giới hạn restart
systemctl show alex-core | grep StartLimit
```

---

## 6. Rollback

```bash
# 1. Dừng service trước khi thao tác với database
sudo systemctl stop alex-core

# 2. Restore database từ backup (KHÔNG thực hiện khi service đang chạy)
cp /opt/alex/AlexRoom-0.2.0-hardware-rc/backups/alex-<timestamp>.db \
   /var/lib/alex/alex.db

# 3. Nếu rollback code: copy lại source từ archive/git, giữ nguyên .venv
# 4. Restart service
sudo systemctl start alex-core
```

---

## 7. Triển khai trên Windows (dev)

1. Tạo `.venv`, cài `requirements.txt` và chạy `npm ci`.
2. Set `MQTT_PASSWORD` và `ALEX_API_KEY` trong process environment.
   Tùy chọn: `ALEX_SIMULATOR=1` cho local testing (không dùng ở production).
3. Chạy `npm run check:all` để kiểm tra toàn bộ quality gate.
4. Chạy preview: `powershell -ExecutionPolicy Bypass -File scripts/preview.ps1`.
5. Mở `http://127.0.0.1:5173`.

---

## 8. Build static assets

Build static assets trên máy dev Windows **trước** khi deploy lên Orange Pi.
Orange Pi không chạy build nặng (npm, node).

```powershell
# Trên Windows dev
npm run build
```

File output nằm ở `dist/static/`. Đây cũng là output của release script.

---

## 9. Cấu hình MQTT Client ID cho production

MQTT Client ID mặc định của app là `sha256(hostname:pid)[:10]`. Khi service
restart, PID thay đổi nên Client ID cũng thay đổi — điều này gây ra MQTT
clean session mới mỗi lần restart.

Để có Client ID ổn định, set trong `/etc/alex/alex.env`:

```
MQTT_CLIENT_ID=alex-core-orange-pi
```

Giá trị này phải unique trong MQTT namespace. Không dùng cùng ID cho nhiều
instance.

---

## 10. Bảo mật

- Chỉ expose qua LAN / Tailscale.
- Nếu truy cập ngoài mạng tin cậy: thêm reverse proxy với TLS (nginx + Let's Encrypt).
- Không bao giờ commit `/etc/alex/alex.env` vào Git.
- API key: dùng chuỗi random đủ dài (≥32 ký tự).
- MQTT password: xem cấu hình Mosquitto hiện có.
- Relay và thiết bị 220V: vẫn `RESTRICTED` ở mức phần mềm; không bật trong production cho đến khi hoàn tất Phase 7 và safety interlock vật lý.

---

## Cấu hình biến môi trường

| Biến | Bắt buộc | Mô tả |
|---|---|---|
| `ALEX_API_KEY` | ✅ | Key cho tất cả mutation API |
| `MQTT_PASSWORD` | ✅ | Password cho Mosquitto auth |
| `MQTT_HOST` | ✅ | IP/hostname của broker (thường `127.0.0.1`) |
| `MQTT_PORT` | - | Port broker, mặc định `1883` |
| `MQTT_USERNAME` | - | Username Mosquitto, mặc định `alex_core` |
| `MQTT_CLIENT_ID` | - | Set cố định cho production |
| `ALEX_DATABASE_PATH` | - | Path SQLite, mặc định `./data/alex.db` |
| `ALEX_SIMULATOR` | - | `0` cho production, `1` chỉ cho dev/test |
| `ALEX_MUTATION_RATE_LIMIT` | - | Max mutations/60s, mặc định `30` |
| `ALEX_BRAIN_MAC` | - | MAC address PC Brain để Wake-on-LAN |
| `ALEX_BRAIN_HOST` | - | IP PC Brain để probe sau WoL |
| `ALEX_BRAIN_PORT` | - | Port SSH PC Brain, mặc định `22` |
