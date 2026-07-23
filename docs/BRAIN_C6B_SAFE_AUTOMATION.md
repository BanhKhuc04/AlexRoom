# ALEX Brain C6B — existing safe automation execution

Checkpoint C6B expands only the Core execution policy:

```text
system_status
list_devices
set_test_led
run_safe_mission
run_safe_automation
```

The C1 six-tool registry is unchanged. `set_room_mode` remains disabled.

## Authority and existing automation semantics

Brain may supply only:

```json
{"automation_id": "existing-automation-id"}
```

Core looks up that ID in the authoritative `automations` store. The record must
have `brain_allowed` equal to the exact boolean `true` and `enabled` equal to the
exact boolean `true`. Missing, false, numeric, and string substitutes are
rejected. Explicit inactive or disabled state is also rejected.

The current repository automation format stores an inline `actions` list. It
does not reference a stored mission by `mission_id`. The existing
`AutomationExecutor` resolves those actions into a transient mission and invokes
the existing `MissionExecutor`. C6B preserves that model:

```text
StoredSafeAutomationExecutor
→ full stored actions preflight
→ existing AutomationExecutor.evaluate(manual trigger)
→ existing MissionExecutor
→ CommandGateway for each physical action
→ SafetyPolicy
→ CommandService
→ existing transport
→ ACK/reported lifecycle
```

Because there is no nested stored mission in the current schema, there is no
nested mission `brain_allowed` decision. The automation itself must be
Brain-authorized, while all resolved actions must independently pass the shared
C6A safety preflight. If a future schema introduces stored mission references,
that resolution needs its own checkpoint review before it may execute.

Preflight occurs before `AutomationExecutor.evaluate`. An automation containing
`test_led` followed by `relay_1` is rejected with zero evaluation, mission runs,
gateway requests, or hardware effects. `brain_allowed=true` is never hardware
authority.

The stored trigger and conditions are not modified. C6B requests an immediate
manual evaluation through the existing semantics. Trigger mismatch or unmet
conditions are authoritative failures, not fake completion.

## Optional local real-AI simulator acceptance

These commands are local-only. Use a disposable database and never point them at
the Orange Pi or production records. Start each service manually only when ready.

Start native Ollama Brain in terminal 1:

```powershell
$env:ALEX_BRAIN_API_KEY = "<development-shared-secret>"
$env:ALEX_BRAIN_PROVIDER = "ollama_native"
$env:ALEX_BRAIN_PROVIDER_URL = "http://127.0.0.1:11434"
$env:ALEX_BRAIN_MODEL = "qwen3.5:4b"
$env:ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS = "30"
.\.venv\Scripts\python.exe -m uvicorn brain_service.app:app --host 127.0.0.1 --port 8090
```

Start local simulated Core in terminal 2:

```powershell
$env:MQTT_PASSWORD = "<local-development-password>"
$env:ALEX_API_KEY = "<local-core-api-key>"
$env:ALEX_DATABASE_PATH = "data/c6b-local-simulator.db"
$env:ALEX_SIMULATOR = "1"
$env:ALEX_SIMULATOR_SCENARIO = "normal"
$env:ALEX_BRAIN_ENABLED = "true"
$env:ALEX_BRAIN_URL = "http://127.0.0.1:8090"
$env:ALEX_BRAIN_CLIENT_KEY = "<development-shared-secret>"
$env:ALEX_BRAIN_TIMEOUT_SECONDS = "30"
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Create safe and unsafe records only in that disposable Core from terminal 3:

```powershell
$headers = @{ "X-ALEX-Key" = "<local-core-api-key>" }
$safeAutomation = @{
  body = @{
    name = "C6B local safe LED automation"
    source = "local_software"
    brain_allowed = $true
    enabled = $true
    trigger = @{ type = "manual" }
    conditions = @()
    actions = @(
      @{ node_id = "esp01"; target = "test_led"; action = "set"; value = $true },
      @{ node_id = "esp01"; target = "test_led"; action = "set"; value = $false }
    )
  }
} | ConvertTo-Json -Depth 8
Invoke-RestMethod `
  -Method Put `
  -Uri "http://127.0.0.1:8000/api/v1/automations/c6b-local-safe-automation" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $safeAutomation

$unsafeAutomation = @{
  body = @{
    name = "C6B local unsafe relay automation"
    source = "local_software"
    brain_allowed = $true
    enabled = $true
    trigger = @{ type = "manual" }
    conditions = @()
    actions = @(
      @{ node_id = "esp01"; target = "test_led"; action = "set"; value = $true },
      @{ node_id = "esp01"; target = "relay_1"; action = "on" }
    )
  }
} | ConvertTo-Json -Depth 8
Invoke-RestMethod `
  -Method Put `
  -Uri "http://127.0.0.1:8000/api/v1/automations/c6b-local-unsafe-automation" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $unsafeAutomation
```

Ask Core to evaluate the safe stored automation:

```powershell
$body = @{
  request_id = "c6b-local-safe-1"
  user_text = "Chạy automation c6b-local-safe-automation."
} | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/brain/chat" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Expected Brain proposal:

```json
{
  "name": "run_safe_automation",
  "arguments": {
    "automation_id": "c6b-local-safe-automation"
  }
}
```

Core executes the stored actions through the existing automation/mission stack,
and the final simulated LED state is off.

Then request the unsafe record:

```powershell
$body = @{
  request_id = "c6b-local-unsafe-1"
  user_text = "Chạy automation c6b-local-unsafe-automation."
} | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/brain/chat" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Expected Core result: `rejected` with `automation_preflight_failed`, denied
capability `relay_1`, zero mission runs, zero gateway execution, and unchanged
LED/relay state.
