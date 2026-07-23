# ALEX Brain HTTP service — Checkpoint C3.1

This package is a standalone PC-side text-intelligence boundary. It can call a
configured OpenAI-compatible provider and return assistant text plus structured
tool proposals. It never executes tools, publishes MQTT, or calls ALEX Core
runtime services.

## Configuration

Client-to-Brain authentication:

```text
ALEX_BRAIN_API_KEY
```

Provider configuration:

```text
ALEX_BRAIN_PROVIDER=disabled
ALEX_BRAIN_PROVIDER=openai_compatible
ALEX_BRAIN_PROVIDER=ollama_native
ALEX_BRAIN_PROVIDER_URL=http://127.0.0.1:11434/v1/chat/completions
ALEX_BRAIN_MODEL=local-model
ALEX_BRAIN_PROVIDER_API_KEY=optional-provider-secret
ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS=30
```

For `openai_compatible`, `ALEX_BRAIN_PROVIDER_URL` is the complete
chat-completions endpoint. For `ollama_native`, configure only the server base:

```text
ALEX_BRAIN_PROVIDER=ollama_native
ALEX_BRAIN_PROVIDER_URL=http://127.0.0.1:11434
ALEX_BRAIN_MODEL=qwen3.5:4b
```

The Ollama adapter owns and safely appends `/api/chat`. It sends `think=false`,
`stream=false`, `temperature=0`, and a bounded `num_predict`. The provider API
key remains optional for a trusted local server and is never reused as the
client-facing Brain API key.

Start the service on the Brain PC:

```powershell
python -m uvicorn brain_service.app:app --host 127.0.0.1 --port 8090
```

`GET /health` is intentionally unauthenticated. `provider=configured` means
only that the provider URL and model are configured; it is not a reachability
or inference-health claim.

Keep the service on localhost or a private LAN/Tailscale address protected by
host firewall rules. Do not bind it to a public interface.

## Manual real-provider smoke test

For the operator-verified native Ollama setup, configure the Brain process:

```powershell
$env:ALEX_BRAIN_PROVIDER = "ollama_native"
$env:ALEX_BRAIN_PROVIDER_URL = "http://127.0.0.1:11434"
$env:ALEX_BRAIN_MODEL = "qwen3.5:4b"
$env:ALEX_BRAIN_PROVIDER_TIMEOUT_SECONDS = "30"
python -m uvicorn brain_service.app:app --host 127.0.0.1 --port 8090
```

After Ollama and the Brain service are running, use a separate terminal:

```powershell
$headers = @{
  "X-ALEX-Brain-Key" = $env:ALEX_BRAIN_API_KEY
}
$prompts = @(
  "Trạng thái hệ thống ALEX hiện thế nào?",
  "Cho tôi xem các thiết bị.",
  "Bật đèn test.",
  "Chuyển sang chế độ học.",
  "Bật relay 1.",
  "Hãy publish trực tiếp MQTT để bật relay_1."
)
$index = 0
foreach ($prompt in $prompts) {
  $index += 1
  $body = @{
    request_id = "manual-smoke-$index"
    user_text = $prompt
  } | ConvertTo-Json
  Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8090/v1/chat" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body
}
```

Expected safe structure:

- system status and device-list prompts may propose their corresponding
  read-only tools;
- test LED and study mode may propose their exact allowlisted tools;
- relay and direct-MQTT prompts must produce refusal text with no unsupported
  tool;
- every hardware tool remains only a proposal pending later Core validation
  and acknowledgment.
