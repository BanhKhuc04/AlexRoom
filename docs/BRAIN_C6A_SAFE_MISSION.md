# ALEX Brain C6A — existing safe mission execution

Checkpoint C6A expands only the Core execution policy:

```text
system_status
list_devices
set_test_led
run_safe_mission
```

The C1 proposal registry remains the same six-tool registry. `set_room_mode` and
`run_safe_automation` are still disabled at the Core boundary.

## Authority and execution path

Brain may supply only:

```json
{"mission_id": "existing-mission-id"}
```

Core validates the complete Brain response, applies the atomic C6A batch policy,
and looks up that ID in the authoritative `missions` store. The stored record
must have `brain_allowed` equal to the exact boolean `true`. Missing, false,
numeric, or string values are rejected. Explicit disabled/inactive state is also
rejected; Brain cannot reactivate a mission.

The stored record remains untrusted for hardware authority. Before step 1, Core
builds a complete mission request list and calls the existing
`CommandGateway.authorize_batch`. One denied or malformed step rejects the whole
mission with zero step execution. A permitted mission then follows:

```text
StoredSafeMissionExecutor
→ existing MissionExecutor
→ CommandGateway for every physical step
→ SafetyPolicy
→ CommandService
→ existing transport
→ ACK/reported lifecycle
```

There is no Brain-side MQTT publish and no second mission executor. A mission
containing `test_led` followed by `relay_1` is rejected during preflight before
the LED step. `brain_allowed=true` never overrides relay restrictions.

Mission results preserve the executor's authoritative lifecycle. Lookup,
authorization, or preflight does not imply completion, and assistant text cannot
override a failed or running result.

## Optional local real-AI simulator acceptance

These commands are local-only. Do not point them at the Orange Pi or a production
database. Run each service manually in its own terminal only when ready.

Start the Brain service with native Ollama in terminal 1:

```powershell
$env:ALEX_BRAIN_API_KEY = "<development-shared-secret>"
$env:ALEX_BRAIN_PROVIDER = "ollama_native"
$env:ALEX_BRAIN_PROVIDER_URL = "http://127.0.0.1:11434"
$env:ALEX_BRAIN_MODEL = "qwen3.5:4b"
$env:ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS = "30"
.\.venv\Scripts\python.exe -m uvicorn brain_service.app:app --host 127.0.0.1 --port 8090
```

Start a local simulated Core using a disposable database in terminal 2:

```powershell
$env:MQTT_PASSWORD = "<local-development-password>"
$env:ALEX_API_KEY = "<local-core-api-key>"
$env:ALEX_DATABASE_PATH = "data/c6a-local-simulator.db"
$env:ALEX_SIMULATOR = "1"
$env:ALEX_SIMULATOR_SCENARIO = "normal"
$env:ALEX_BRAIN_ENABLED = "true"
$env:ALEX_BRAIN_URL = "http://127.0.0.1:8090"
$env:ALEX_BRAIN_CLIENT_KEY = "<development-shared-secret>"
$env:ALEX_BRAIN_TIMEOUT_SECONDS = "30"
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Create two records only in that disposable local Core from terminal 3:

```powershell
$headers = @{ "X-ALEX-Key" = "<local-core-api-key>" }
$safeMission = @{
  body = @{
    name = "C6A local safe LED mission"
    source = "local_software"
    brain_allowed = $true
    steps = @(
      @{ node_id = "esp01"; target = "test_led"; action = "set"; value = $true },
      @{ node_id = "esp01"; target = "test_led"; action = "set"; value = $false }
    )
  }
} | ConvertTo-Json -Depth 8
Invoke-RestMethod `
  -Method Put `
  -Uri "http://127.0.0.1:8000/api/v1/missions/c6a-local-safe-led" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $safeMission

$unsafeMission = @{
  body = @{
    name = "C6A local unsafe relay preflight"
    source = "local_software"
    brain_allowed = $true
    steps = @(
      @{ node_id = "esp01"; target = "test_led"; action = "set"; value = $true },
      @{ node_id = "esp01"; target = "relay_1"; action = "on" }
    )
  }
} | ConvertTo-Json -Depth 8
Invoke-RestMethod `
  -Method Put `
  -Uri "http://127.0.0.1:8000/api/v1/missions/c6a-local-unsafe-relay" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $unsafeMission
```

Ask Core to run the safe stored mission through real Brain:

```powershell
$body = @{
  request_id = "c6a-local-safe-1"
  user_text = "Chạy mission test đèn an toàn c6a-local-safe-led."
} | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/brain/chat" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Expected proposal: `run_safe_mission` with only
`{"mission_id":"c6a-local-safe-led"}`. Core retrieves and executes the stored
steps; the final simulated LED state is off.

Then test the unsafe stored record:

```powershell
$body = @{
  request_id = "c6a-local-unsafe-1"
  user_text = "Chạy mission c6a-local-unsafe-relay."
} | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/brain/chat" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Expected Core result: `rejected` with `mission_preflight_failed`, denied
capability `relay_1`, zero `CommandGateway.request` calls, and no LED or relay
side effect.
