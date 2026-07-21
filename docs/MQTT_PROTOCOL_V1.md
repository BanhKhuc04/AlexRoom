# MQTT Protocol V1 — ALEX / ESP01

## Mục tiêu

Contract V1 chạy song song với topic ESPHome cũ. Vertical slice đầu tiên chỉ cho phép `esp01/test_led/set`; không cho phép relay 220V, UV, khóa cửa, motor hoặc pump.

Root topic: `alex/v1/nodes/esp01`.

| Topic | QoS | Retain | Producer |
|---|---:|---:|---|
| `/command` | 1 | không | ALEX Core |
| `/ack` | 1 | không | ESP01 |
| `/reported` | 1 | có | ESP01 |
| `/heartbeat` | 0 | không | ESP01 |
| `/telemetry` | 0 | không | ESP01 |
| `/status` | 1 | có | ESP01/LWT |

## Command

```json
{"protocolVersion":1,"commandId":"cmd_<uuid>","target":"test_led","action":"set","value":true,"timestamp":0,"source":"local_software"}
```

Publish thành công chỉ chuyển command sang `waiting_ack`; không phải bằng chứng thiết bị đã đổi.

## ACK

```json
{"protocolVersion":1,"commandId":"cmd_<uuid>","nodeId":"esp01","status":"accepted","timestamp":0}
```

`status`: `accepted`, `duplicate` hoặc `rejected`. ACK sai `commandId`, `nodeId` hoặc protocol bị bỏ qua.

## Reported state

```json
{"protocolVersion":1,"nodeId":"esp01","target":"test_led","state":{"on":true},"commandId":"cmd_<uuid>","timestamp":0}
```

Chỉ reported state có cùng command ID và khớp desired state mới tạo `confirmed`. Giá trị khác tạo `reported_state_mismatch`.

## Heartbeat/status

```json
{"protocolVersion":1,"nodeId":"esp01","online":true,"uptime":120,"rssi":-50,"firmware":"1.0.0","ip":"192.168.0.x","timestamp":0}
```

Backend suy ra offline sau 45 giây không có heartbeat. MQTT disconnect chuyển node đang online sang degraded; hết heartbeat timeout mới thành offline.

## Duplicate delivery

Firmware giữ 8 command gần nhất. Command ID trùng không thực thi GPIO lần hai; firmware trả ACK `duplicate` và phát lại reported state đã lưu.

## Lifecycle

`queued → sending → waiting_ack → accepted → waiting_reported_state → confirmed`

Nhánh lỗi: `retrying` tối đa hai lần, sau đó `timed_out`; publish lỗi hoặc mismatch thành `failed`. Mỗi transition được lưu trong `command_events`.
