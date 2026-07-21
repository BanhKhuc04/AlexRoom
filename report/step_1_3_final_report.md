# ALEX STEP 1.3 — FINAL REPORT
## Hardware Truth Registry + Status Consistency

---

## 1. Existing Step 1.3 Work Reviewed

The commit `fa5c02b` (wip: step 1.3 hardware truth registry) was already committed and the
working tree is **clean**. The previous agent fully implemented Step 1.3 across 26 files.
No work was discarded or regressed.

Key changes in that commit reviewed and confirmed correct:
- `alex_safety.py` — CapabilityRegistry, SafetyPolicy, CommandGateway fully implemented
- `alex_hardware.py` — LEGACY_VERIFICATION_FIELDS stripped on restart; no hardware truth in device state
- `alex_store.py` — structured safety audit, command events
- `app.py` — all device/status routes derive from CapabilityRegistry; `_with_command_verification()` helper
- `static/core/domain.d.ts` — full type coverage: VerificationStatus, CapabilityStatus, NodeVerification
- `static/ui/presence-commands.js` — "Kiểm tra hệ thống" uses `v1Device?.connection` (V1 truth)
- `static/ui/presence-view.js` — `renderSnapshot` separates connection from verification
- `static/ui/workspaces.js` — renders registry fields, not hardcoded strings
- `tests/frontend-safety.test.mjs` — 4 new tests covering the V1 consistency fix
- `tests/test_app_safety.py` — 10 new tests covering API truth source
- `tests/test_safety.py` — 7 tests covering CapabilityRegistry and policy behavior
- `docs/HARDWARE_V1_SUMMARY.md` — correct documentation of current state

---

## 2. Additional Files Changed By This Agent

**None.** The implementation was already complete and correct. No changes were needed.

---

## 3. Hard-Coded Verification Truth Remaining

| Location | String | Assessment |
|---|---|---|
| `static/ui/workspaces.js:160` | `HARDWARE` / `NOT VERIFIED` | ✅ Label in **integration status DL** for unimplemented workspace stubs (camera/energy/brain). Not an ESP01 capability truth. Not in a `<button disabled>NOT VERIFIED` pattern. Test passes. |
| `alex_brain.py:40` | `"hardware_verified": False` | ✅ BrainService WoL confirmation state for the **i5-4590 PC** — completely separate domain from ESP01 CapabilityRegistry. Not in scope of the test guard (app.py + alex_hardware.py only). |

**No hard-coded ESP01 verification truth exists** in any runtime source file.

---

## 4. Final CapabilityRegistry States

From `alex_safety.py` `_default_nodes()`:

| Capability | verification_status | command_allowed | risk_level |
|---|---|---|---|
| `esp01` (node) | `basic_physical_validated` | N/A | N/A |
| `esp01/test_led` | `basic_physical_validated` | `True` | `safe` |
| `esp01/relay_1` | `restricted` | `False` | `restricted` |
| `esp01/relay_2` | `restricted` | `False` | `restricted` |
| `esp01/relay_3` | `restricted` | `False` | `restricted` |
| `esp01/relay_4` | `restricted` | `False` | `restricted` |

**`esp01.hardware_verified = False`** — node verification_status is `basic_physical_validated`,
not `hardware_verified`, so the `hardware_verified` property returns `False`.

---

## 5. APIs Using Registry Truth

All status/device routes derive from `capability_registry.get_node_status()`:

| Endpoint | Source |
|---|---|
| `GET /api/v1/status` | `capability_registry.get_node_status(DEVICE_ID)` |
| `GET /api/v1/safety/capabilities` | `capability_registry.public_snapshot()` |
| `GET /api/v1/devices` | `capability_registry.get_node_status(DEVICE_ID)` merged with command_service |
| `GET /api/devices/esp01` | `capability_registry.get_node_status(DEVICE_ID)` |
| `POST /api/v1/commands` | `_with_command_verification()` → `capability_registry` |

No route duplicates hardware truth. The test `test_status_and_device_apis_derive_truth_from_registry_fixture`
confirms that patching the registry fixture changes all four API outputs without editing any route code.

---

## 6. Presence / Spatial Home / Devices Behavior

### Presence
- `presence-view.js:renderSnapshot()` reads `v1Device?.connection` (connectivity) and
  `v1Device?.verification_status` (verification) **separately**.
- ESP01 ONLINE ≠ hardware verified. Test `online connectivity is displayed separately from verification truth` PASS.

### Spatial Home
- `workspaces.js:renderOverview()` shows `nodeVerification = formatVerification(v1Device?.verification_status)`
  and `ledVerification = formatVerification(v1Device?.capabilities.test_led?.verification_status)` from registry.

### Devices
- Relay cards read `capability?.risk_level`, `capability?.verification_status`, `capability?.command_allowed !== true`.
- Labels are derived dynamically from registry; no hard-coded `RESTRICTED` or `NOT VERIFIED` button text.

---

## 7. "Kiểm tra hệ thống" Consistency Fix

In `static/ui/presence-commands.js` (line 82):
```js
const espConnection = snapshot.v1Device?.connection ?? snapshot.device.availability;
```

This expression uses the **V1 device connection** from `GET /api/v1/devices` (which derives connectivity from
heartbeat-based `CommandService._device.connection`) as the primary source. Falls back to legacy availability only
if v1Device is absent.

Result: when ESP01 is ONLINE (heartbeat received), `espConnection = "online"` regardless of old availability
state. The "Kiểm tra hệ thống" response shows `ESP01 online` consistently.

**No regression to legacy UNKNOWN** when V1 status is ONLINE. Test
`online connectivity is displayed separately from verification truth` confirms `v1Device?.connection` is read.

---

## 8. Audit Event Verification

`_record_safety_denial()` in `app.py` (lines 220–235) records:

```python
details = {
    "node": decision.node_id,           # e.g. "esp01"
    "capability": decision.capability_id, # e.g. "relay_3"
    "action": decision.action,           # e.g. "off"
    "status": decision.verification_status, # e.g. "restricted"
    "risk": decision.risk_level,         # e.g. "restricted"
    "reason": decision.reason,           # e.g. "restricted_capability"
    "execution_mode": decision.execution_mode,
}
```

Confirmed by test `test_denial_audit_contains_structured_safety_truth` → **PASS**.
No secrets, API keys or device credentials in audit record.

---

## 9. Quality Gate Result — npm run check:all

```
✅ Typecheck       PASS
✅ ESLint          PASS
✅ Frontend tests  PASS — 25/25
✅ Build           PASS
✅ Backend tests   PASS — 33/33
✅ Python compile  PASS
```

**Total: 25 frontend + 33 backend = 58 tests, 0 failures.**

---

## 10. Exact Test Counts

### Frontend (node --test)
- accessibility: 1
- alex-state: 4
- command-lifecycle: 4
- core-runtime: 3
- frontend-safety: 4
- presence-intent: 1
- quality: 3
- realtime: 2
- sound-engine: 3
- **Total: 25 tests, 25 pass, 0 fail**

### Backend (python -m unittest)
- test_app_safety.AppSafetyBoundaryTests: 10 tests
- test_hardware.HardwareVerticalSliceTests: 10 tests
- test_orchestration.OrchestrationTests: 3 tests
- test_safety.CentralSafetyPolicyTests: 7 tests
- test_store.AlexStoreTests: 2 tests  
- **Total: 33 tests in 4.141s, 33 pass, 0 fail (OK)**

---

## 11. Browser Validation

**Browser tooling is not available in this environment.**

This is explicitly stated as required by the task. No fabricated browser PASS is claimed.

What IS confirmed:
- The frontend JS was statically analyzed by ESLint and TypeScript (0 errors)
- The build pipeline produces `dist/static` successfully
- Frontend unit tests covering the relevant behavior paths all PASS
- Presence-commands.js uses `v1Device?.connection` (verified by static source analysis + test assertion)

What is NOT confirmed:
- Live browser rendering of Presence / Spatial Home / Devices
- Desktop / mobile visual appearance from a running server instance
- Console error state in a real browser session

---

## 12. Remaining Limitations

1. **Phase 7 not complete** — Full hardware verification checklist (power-cycle, reconnect, duplicate,
   timeout, long soak) has not been completed. `esp01` remains at `basic_physical_validated`, not `hardware_verified`.
2. **relay_1..4 remain RESTRICTED** — No relay has been physically verified. No commands are allowed.
3. **Browser validation not available** — The running-app browser check must be performed manually.
4. **Orange Pi hardware not tested** — All backend tests ran on Windows dev environment.
5. **Tailscale / remote access not verified** — Remote access path untested in this session.

---

## Verification Matrix for Stated Requirements

| # | Requirement | Status |
|---|---|---|
| 1 | ESP01 hardware_verified remains false | ✅ CONFIRMED (registry + test) |
| 2 | test_led = basic_physical_validated | ✅ CONFIRMED (registry + test) |
| 3 | test_led command_allowed = true | ✅ CONFIRMED (registry + test) |
| 4 | relay_1..4 = restricted | ✅ CONFIRMED (registry + 4 tests) |
| 5 | relay command_allowed = false | ✅ CONFIRMED (policy + test) |
| 6 | API values from CapabilityRegistry | ✅ CONFIRMED (fixture swap test PASS) |
| 7 | Command response no global ESP01 claim | ✅ CONFIRMED (`_with_command_verification` + test) |
| 8 | ONLINE ≠ HARDWARE VERIFIED | ✅ CONFIRMED (source separation + test) |
| 9 | Registry fixture changes all API output | ✅ CONFIRMED (`test_status_and_device_apis_derive_truth_from_registry_fixture`) |
| 10 | "Kiểm tra hệ thống" uses V1 connectivity | ✅ CONFIRMED (`v1Device?.connection` in presence-commands.js + test) |
