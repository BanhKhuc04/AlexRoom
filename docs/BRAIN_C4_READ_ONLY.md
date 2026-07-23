# ALEX Brain C4 — Core read-only integration

Checkpoint C4 connects ALEX Core to the standalone Brain HTTP service without
enabling any mutation. Brain remains a proposal-only service; Core authenticates
the user, authenticates its own request to Brain, validates the complete C1
response again, applies a separate C4 execution policy, and reads authoritative
Core state.

## Configuration

Core-side variables:

```text
ALEX_BRAIN_ENABLED=false
ALEX_BRAIN_URL=http://127.0.0.1:8090
ALEX_BRAIN_CLIENT_KEY=<same secret as the Brain service ALEX_BRAIN_API_KEY>
ALEX_BRAIN_TIMEOUT_SECONDS=5
```

`ALEX_BRAIN_ENABLED` defaults to disabled. Missing URL/key, an offline Brain,
an offline provider, or a timeout affects only `POST /api/v1/brain/chat`; Core
startup and existing APIs do not connect to or depend on Brain.

The client key is server-to-server configuration. It is sent only as
`X-ALEX-Brain-Key` to Brain and is never accepted as user authentication,
returned to the browser, or included in audit records.

## C4 execution policy

The exact C4 execution allowlist is:

```text
system_status
list_devices
```

This is intentionally separate from the six-tool C1 proposal registry. The four
valid mutation proposals remain in the C1 registry but receive
`tool_not_enabled_in_c4` and are not executed.

C4 applies atomic batch policy. If one structurally valid proposal in a batch is
outside the C4 execution allowlist, no proposal in that batch executes. An
otherwise allowed read in that batch receives `batch_rejected_in_c4`.
Unknown/malformed tools fail whole-response C1 validation as
`invalid_brain_response` before policy or execution.

`system_status` calls the same underlying Core implementation as
`GET /api/v1/status`. `list_devices` calls the same underlying Core registry
implementation as `GET /api/v1/devices`. Neither tool calls a Core HTTP endpoint
over loopback.

## Optional local real E2E

These commands are for a development machine only. They do not target the Orange
Pi production process.

Start Brain with native Ollama in terminal 1:

```powershell
$env:ALEX_BRAIN_API_KEY = "<development-shared-secret>"
$env:ALEX_BRAIN_PROVIDER = "ollama_native"
$env:ALEX_BRAIN_PROVIDER_URL = "http://127.0.0.1:11434"
$env:ALEX_BRAIN_MODEL = "qwen3.5:4b"
$env:ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS = "30"
python -m uvicorn brain_service.app:app --host 127.0.0.1 --port 8090
```

Start a development Core in terminal 2, in addition to its existing required
development variables such as `MQTT_PASSWORD` and `ALEX_API_KEY`:

```powershell
$env:ALEX_BRAIN_ENABLED = "true"
$env:ALEX_BRAIN_URL = "http://127.0.0.1:8090"
$env:ALEX_BRAIN_CLIENT_KEY = "<development-shared-secret>"
$env:ALEX_BRAIN_TIMEOUT_SECONDS = "10"
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Call the authenticated Core endpoint from terminal 3:

```powershell
$headers = @{ "X-ALEX-Key" = $env:ALEX_API_KEY }
$prompts = @(
  "Trạng thái hệ thống ALEX hiện thế nào?",
  "Cho tôi xem các thiết bị.",
  "Bật đèn test."
)
$index = 0
foreach ($prompt in $prompts) {
  $index += 1
  $body = @{
    request_id = "c4-local-$index"
    user_text = $prompt
  } | ConvertTo-Json
  Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/brain/chat" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body
}
```

Expected:

- status returns a Core-authoritative `system_status` result;
- devices returns a Core-authoritative `list_devices` result;
- test LED returns `tool_not_enabled_in_c4`, with no command, MQTT publish, or
  hardware action.
