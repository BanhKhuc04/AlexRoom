# ESP01 test plan

## Software/simulator matrix

1. ACK + reported đúng → `confirmed`.
2. ACK nhưng thiếu reported → `timed_out`.
3. Thiếu ACK → retry 1, retry 2, `timed_out`.
4. Reported khác desired → `failed/reported_state_mismatch`.
5. Offline → HTTP 409, không publish.
6. Duplicate command → GPIO execution count không tăng, ACK `duplicate`.
7. Backend restart khi pending → `failed/backend_restarted`.
8. Frontend reconnect → GET devices/commands rehydrate digital twin.

## Hardware gate

1. Chỉ nối ESP8266 qua USB; không gắn relay/tải.
2. Xác nhận đúng board và COM.
3. Flash, mở serial monitor và chờ heartbeat.
4. Gửi ON/OFF cho `test_led`, quan sát LED, ACK, reported state và SQLite.
5. Gửi lại cùng command ID để xác nhận không thực thi lần hai.
6. Ngắt Wi-Fi/MQTT, xác nhận degraded/offline và retry hữu hạn.
7. Ghi latency thực từ created → ACK → confirmed.

Chỉ sau khi toàn bộ bước trên PASS mới thảo luận mapping một output điện áp thấp khác. Không chuyển sang 220V trong test plan này.
