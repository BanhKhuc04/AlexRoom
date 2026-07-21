# Realtime protocol

Endpoint SSE: `GET /api/v1/realtime`.

Envelope:

```json
{"id":"evt_<uuid>","type":"command_ack","timestamp":"ISO-8601","source":"mqtt|simulated|local_software","data":{}}
```

Event chính: `node_online`, `node_degraded`, `node_offline`, `heartbeat`, `command_created`, `command_sending`, `command_sent`, `command_ack`, `command_waiting_reported`, `reported_state`, `command_confirmed`, `command_retry`, `command_timeout`, `state_mismatch`, `telemetry`, `automation_evaluated`, `mission_completed`, `brain_waking`, `brain_online`, `brain_wake_timeout`.

Frontend đóng EventSource khi tab ẩn, mở lại khi visible và reconnect theo 1, 2, 4, 8, 16, 30 giây. SSE chỉ là thông báo; sau reconnect frontend rehydrate digital twin từ REST/SQLite.
