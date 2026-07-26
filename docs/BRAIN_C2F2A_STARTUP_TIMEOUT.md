# C2F.2a — Brain startup and timeout hardening

## Runtime policy

The production model for the measured two-CPU, CPU-only Brain VM is
`qwen3.5:2b`. Model selection remains environment-owned through
`ALEX_BRAIN_MODEL`; application logic does not hard-code it.

At FastAPI startup, the Ollama-native provider sends one bounded canonical
prefix chat request. It contains:

- the configured model;
- the canonical `SYSTEM_INSTRUCTION`;
- the full legacy catalog returned by
  `brain_tool_schemas_for_provider(None)`;
- one empty, neutral user message;
- `think=false` and `stream=false`;
- `num_predict=1`;
- `keep_alive=-1`.

Ollama documents empty `/api/chat` requests as a preload operation and a
negative `keep_alive` value as keeping the model resident:
<https://docs.ollama.com/faq#how-can-i-preload-a-model-into-ollama-to-get-faster-response-times>.

No assistant answer is stored or passed through the Brain contract. The warmup
cannot execute tools, Core operations, MQTT, or hardware.
No real-looking user command is sent. Provider output, including tool-call-like
metadata, is discarded after checking only that upstream completed with
`done=true`; it never enters `BrainChatResponse` validation or execution.

Normal inference has a 25-second maximum provider timeout. The separate
startup-only warmup budget defaults to 60 seconds because the measured cold
load is approximately 46.66 seconds. The Core timeout remains 30 seconds.

Warmup failure is fail-safe and bounded. Ollama unavailable, a missing model,
timeout, or malformed response leaves `/ready` degraded or not ready, but does
not crash the process or cause an unbounded restart loop. `/health` remains the
backward-compatible liveness/configuration endpoint. `/ready` is the additive
startup/readiness endpoint.

OpenAI-compatible providers have no portable preload operation. They report
`warmup=not_supported` and remain ready when otherwise configured. A disabled
or incomplete provider reports `warmup=not_configured` and `ready=false`.

Relevant Context remains disabled or enabled only by its existing Core-side
feature flag. This checkpoint does not activate or alter Relevant Context,
Tool Narrowing, allowed tools, trusted context, or Brain enforcement.

## Production rollout and acceptance

Run only during the later production-activation checkpoint:

```bash
cd /opt/alex/AlexRoom
git status --short
git rev-parse --short HEAD

sudo install -d -m 0750 /etc/alex
if sudo test -f /etc/alex/alex-brain.env; then
  sudo cp -a /etc/alex/alex-brain.env /etc/alex/alex-brain.env.pre-c2f2a
else
  sudo install -m 0600 deploy/alex-brain.env.example /etc/alex/alex-brain.env
fi
sudoedit /etc/alex/alex-brain.env

sudo install -m 0644 deploy/alex-brain.service /etc/systemd/system/alex-brain.service
sudo systemctl daemon-reload
sudo systemctl enable ollama.service alex-brain.service
sudo systemctl restart ollama.service
sudo systemctl restart alex-brain.service

sudo systemctl status alex-brain.service --no-pager
curl --fail --silent --show-error http://127.0.0.1:8090/health
curl --fail --silent --show-error http://127.0.0.1:8090/ready
ollama ps
```

Acceptance sequence:

1. Restart Ollama and Brain as above.
2. Confirm `ollama ps` lists `qwen3.5:2b` resident before user traffic.
3. Confirm `/ready` returns `ready=true`, `warmup=ready`.
4. Send the first authenticated external Brain request and record latency.
5. Send the enhanced zero-tool request again and record warm latency.
6. Send the corresponding request through Core and record its bounded result.
7. Confirm provider timeout is 25 seconds and Core timeout remains 30 seconds.
8. Confirm no Ollama request remains queued after the Core result.

Exact real-VM acceptance commands:

```bash
sudo systemctl restart ollama.service
sudo systemctl restart alex-brain.service

for attempt in $(seq 1 75); do
  ready="$(curl --silent --show-error http://127.0.0.1:8090/ready || true)"
  printf '%s\n' "$ready"
  printf '%s' "$ready" | grep -q '"ready":true' && break
  sleep 1
done

ollama ps

sudo /opt/alex/AlexRoom/.venv/bin/python - <<'PY'
import json
import time
import urllib.request
from pathlib import Path

settings = {}
for raw_line in Path("/etc/alex/alex-brain.env").read_text().splitlines():
    line = raw_line.strip()
    if line and not line.startswith("#") and "=" in line:
        name, value = line.split("=", 1)
        settings[name] = value

headers = {
    "Content-Type": "application/json",
    "X-ALEX-Brain-Key": settings["ALEX_BRAIN_API_KEY"],
}
requests = (
    {
        "request_id": "c2f2a1-first-legacy",
        "user_text": "Xin chào ALEX.",
    },
    {
        "request_id": "c2f2a1-enhanced-zero-tools",
        "user_text": "Xin chào ALEX.",
        "allowed_tools": [],
        "context": {
            "context_schema_version": 1,
            "knowledge_schema_version": 1,
            "snapshot_captured_at": "2026-07-24T00:00:00Z",
            "scope": "general",
            "reason": "no_relevant_knowledge",
            "incomplete": False,
            "sources": [],
            "sections": [],
        },
    },
)

for payload in requests:
    request = urllib.request.Request(
        "http://127.0.0.1:8090/v1/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()
        elapsed = time.monotonic() - started
        print(payload["request_id"], response.status, f"{elapsed:.3f}s")
        if response.status != 200 or elapsed >= 25:
            raise SystemExit("C2F.2a.1 acceptance failed")
PY

sudo journalctl -u ollama.service \
  --since "10 minutes ago" --no-pager | tail -n 200
```

The acceptance target is operational, not a flaky CI assertion: the first
legacy request must return HTTP 200 within the provider's 25-second budget
without paying the full canonical-prefix processing cost. The enhanced
zero-tools request must also return HTTP 200, while provider failure continues
to occur before Core timeout.

## Rollback

If startup readiness or latency regresses after the later deployment:

```bash
sudo systemctl stop alex-brain.service
cd /opt/alex/AlexRoom
git switch --detach 8b755a8
if sudo test -f /etc/alex/alex-brain.env.pre-c2f2a; then
  sudo cp -a /etc/alex/alex-brain.env.pre-c2f2a /etc/alex/alex-brain.env
fi
sudo systemctl daemon-reload
sudo systemctl start alex-brain.service
curl --fail --silent --show-error http://127.0.0.1:8090/health
```

This rollback does not enable Relevant Context, execute tools, or change Core,
MQTT, hardware, database schema, or VERSION.
