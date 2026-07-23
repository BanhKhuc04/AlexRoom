# ALEX Brain C5 — verified test LED mutation

Checkpoint C5 adds one mutation to the Core execution policy:

```text
system_status
list_devices
set_test_led
```

The C1 proposal registry still contains six tools. `set_room_mode`,
`run_safe_mission`, and `run_safe_automation` remain disabled in Core with
`tool_not_enabled_in_c5`.

## Fixed authority boundary

Brain supplies only a strict boolean:

```json
{"value": true}
```

Core owns the complete target mapping:

```text
node_id=esp01
capability=test_led
action=set
```

The C5 adapter calls the existing `CommandGateway`. It does not publish MQTT,
select topics, or create a parallel device implementation. The returned mutation
status follows the existing command phase:

- non-terminal command phase: `pending`;
- `confirmed`: `confirmed`;
- `failed`, `timed_out`, or `cancelled`: `failed`;
- safety denial or unavailable device before command creation: `rejected`.

The result includes the authoritative command phase, ACK/reported timestamps,
reported state, failure reason, and bounded safety decision. A successful publish
alone remains `waiting_ack`/`pending`.

C5 batch policy is atomic. Any valid C1 tool outside the C5 execution allowlist
rejects the complete batch before a read or mutation executes.

## Optional local real-AI simulator E2E

This procedure is local and simulator-only. Do not point these commands at the
Orange Pi production service.

Start the Brain service with native Ollama in terminal 1:

```powershell
$env:ALEX_BRAIN_API_KEY = "<development-shared-secret>"
$env:ALEX_BRAIN_PROVIDER = "ollama_native"
$env:ALEX_BRAIN_PROVIDER_URL = "http://127.0.0.1:11434"
$env:ALEX_BRAIN_MODEL = "qwen3.5:4b"
$env:ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS = "30"
python -m uvicorn brain_service.app:app --host 127.0.0.1 --port 8090
```

Start a local simulated Core in terminal 2:

```powershell
$env:MQTT_PASSWORD = "<local-development-password>"
$env:ALEX_API_KEY = "<local-core-api-key>"
$env:ALEX_DATABASE_PATH = "data/c5-local-simulator.db"
$env:ALEX_SIMULATOR = "1"
$env:ALEX_SIMULATOR_SCENARIO = "normal"
$env:ALEX_BRAIN_ENABLED = "true"
$env:ALEX_BRAIN_URL = "http://127.0.0.1:8090"
$env:ALEX_BRAIN_CLIENT_KEY = "<development-shared-secret>"
$env:ALEX_BRAIN_TIMEOUT_SECONDS = "10"
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Call Core, not Brain, from terminal 3:

```powershell
$headers = @{ "X-ALEX-Key" = "<local-core-api-key>" }
$prompts = @(
  "Bật đèn test.",
  "Cho tôi xem các thiết bị.",
  "Tắt đèn test.",
  "Cho tôi xem các thiết bị."
)
$index = 0
foreach ($prompt in $prompts) {
  $index += 1
  $body = @{
    request_id = "c5-local-$index"
    user_text = $prompt
  } | ConvertTo-Json
  Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/brain/chat" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body
  Start-Sleep -Milliseconds 150
}
```

Expected:

1. ON command enters the normal CommandGateway lifecycle and confirms only after
   simulated ACK plus matching reported state.
2. The first device read reports `reported_state.test_led.on=true`.
3. OFF follows the same lifecycle.
4. The second device read reports `reported_state.test_led.on=false`.

The immediate mutation HTTP response may be `pending`; this is correct when ACK
or reported evidence has not arrived yet.
