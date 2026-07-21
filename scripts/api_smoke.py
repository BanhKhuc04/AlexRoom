from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5173"
KEY = sys.argv[2] if len(sys.argv) > 2 else "local-preview-only"


def request(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if method != "GET":
        headers["X-Alex-Key"] = KEY
    call = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(call, timeout=4) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


for route in (
    "/health", "/api/info", "/api/devices/esp01", "/api/v1/status",
    "/api/v1/devices", "/api/v1/safety/capabilities",
):
    status, _ = request(route)
    assert status == 200, (route, status)

status, created = request("/api/v1/commands", "POST", {
    "node_id": "esp01", "target": "test_led", "action": "set",
    "payload": {"value": True}, "risk_level": "safe", "origin": "api_smoke",
})
assert status == 200 and created["phase"] != "confirmed", created
deadline = time.monotonic() + 2
final = created
while time.monotonic() < deadline:
    status, final = request(f"/api/v1/commands/{created['command_id']}")
    if final.get("phase") == "confirmed":
        break
    time.sleep(0.03)
assert status == 200 and final["phase"] == "confirmed", final
assert final["desired_state"] == final["reported_state"]
assert final["verification"]["node"]["hardware_verified"] is False
assert final["verification"]["capability"]["verification_status"] == "basic_physical_validated"

restricted_status, _ = request("/api/v1/commands", "POST", {
    "target": "uv", "action": "set", "payload": {"value": True}, "risk_level": "restricted",
})
assert restricted_status == 423

relay_status, relay_denied = request("/api/v1/commands", "POST", {
    "target": "relay_1", "action": "on", "payload": {"value": True}, "risk_level": "safe",
})
assert relay_status == 423
assert relay_denied["detail"]["risk_level"] == "restricted"

print(f"API smoke PASS: {created['command_id']} -> confirmed; restricted=423; relay-safe-claim=423")
