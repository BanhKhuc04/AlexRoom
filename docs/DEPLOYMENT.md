# Triển khai ALEXROOM

## Local Windows

1. Tạo `.venv`, cài `requirements.txt` và chạy `npm ci`.
2. Đặt `MQTT_PASSWORD` và `ALEX_API_KEY` trong process environment; không ghi secret vào repository.
   Tùy chọn: `ALEX_SIMULATOR=1` chỉ cho local verification; production phải để `0`.
3. Chạy `npm run check`, Python tests, rồi `powershell -ExecutionPolicy Bypass -File scripts/preview.ps1`.
4. Mở `http://127.0.0.1:5173`.

## Orange Pi

- Build static assets trên máy phát triển bằng `npm run build`; Orange Pi không chạy build nặng.
- Copy source Python, `static/`, `dist/static/`, requirements và service example vào `/opt/alexroom`.
- Tạo `/etc/alexroom/alex.env` mode `0600`, database/backups writable, rồi enable `deploy/alex-core.service`.
- Chỉ expose qua LAN/Tailscale; reverse proxy TLS nếu vượt khỏi mạng tin cậy.

Rollback bằng cách dừng service, phục hồi archive/source và bản SQLite backup tương ứng, rồi khởi động lại. Không restore DB khi service đang ghi.

## Hardware V1 environment

- `MQTT_CLIENT_ID`: override khi cần; mặc định là ID riêng theo process.
- `ALEX_DATABASE_PATH`: đường dẫn SQLite writable.
- `ALEX_MUTATION_RATE_LIMIT`: mặc định 30 mutation/phút.
- `ALEX_BRAIN_MAC`, `ALEX_BRAIN_HOST`, `ALEX_BRAIN_PORT`: chỉ cấu hình sau khi xác nhận PC thật.
- Dùng `scripts/mqtt_simulator.py` để test broker; mọi message được gắn `source=simulated`.
