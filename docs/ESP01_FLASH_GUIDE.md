# Hướng dẫn build/flash ESP01 an toàn

## Phạm vi

Firmware này chỉ điều khiển LED tích hợp `LED_BUILTIN` dưới tên `test_led`. Không nối relay hoặc tải 220V.

## Chuẩn bị

1. Cài VS Code + PlatformIO hoặc PlatformIO Core.
2. Dùng board NodeMCU ESP8266 có USB/serial ổn định.
3. Copy `firmware/esp01/include/config.example.h` thành `config.h` và điền Wi-Fi/MQTT local. `config.h` đã bị ignore.
4. Không sửa hoặc đưa credential vào source/documentation.

## Build và upload

```powershell
cd firmware/esp01
pio run
pio device list
pio run --target upload --upload-port COMx
pio device monitor --port COMx --baud 115200
```

Môi trường hiện tại chưa có PlatformIO và chưa có board/COM được chọn, nên firmware chưa được compile/flash thực tế.

## Log mong đợi

- `[ALEX] esp01 firmware 1.0.0; safe test_led OFF`
- `[WIFI] Reconnect...`
- `[MQTT] Online`
- `[CMD] cmd_... test_led=ON|OFF`
- Với duplicate: `no second execution`

## MQTT verification

Subscribe các topic trong `MQTT_PROTOCOL_V1.md`; heartbeat phải có firmware/RSSI/IP, command phải tạo ACK rồi reported state cùng `commandId`.

## Rollback

Rút USB, giữ firmware cũ hoặc flash lại artifact đã biết tốt. Safe default của bản này luôn đặt LED OFF sau boot. Không rollback/flash khi board đang nối vào mạch tải chưa kiểm tra.
