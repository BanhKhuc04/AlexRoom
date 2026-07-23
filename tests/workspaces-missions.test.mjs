import { test } from "node:test";
import assert from "node:assert";
import { AlexApi } from "../static/core/api.js";
import { WorkspaceDataController } from "../static/core/workspace-data.js";
import { renderMissions } from "../static/ui/workspaces.js";

// Expose minimal escapeHtml
globalThis.escapeHtml = (str) => {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
};

globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };

// 1. API Method Tests
test("AlexApi getMissions calls correct endpoint", async () => {
  let calledUrl = "";
  const api = new AlexApi();
  api.request = async (url) => { calledUrl = url; return { items: [] }; };
  await api.getMissions();
  assert.equal(calledUrl, "/api/v1/missions");
});

test("AlexApi getMissionRuns calls correct endpoint", async () => {
  let calledUrl = "";
  const api = new AlexApi();
  api.request = async (url) => { calledUrl = url; return { items: [] }; };
  await api.getMissionRuns();
  assert.equal(calledUrl, "/api/v1/mission_runs");
});

test("AlexApi saveMission uses PUT and encoded URL", async () => {
  let requestObj;
  const api = new AlexApi();
  api.request = async (url, opts) => { requestObj = { url, opts }; return {}; };
  await api.saveMission("mission_1 2", { name: "test", steps: [] });
  assert.equal(requestObj.url, "/api/v1/missions/mission_1%202");
  assert.equal(requestObj.opts.method, "PUT");
  assert.equal(requestObj.opts.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(requestObj.opts.body), { body: { name: "test", steps: [] } });
});

test("AlexApi runMission uses POST and encoded URL", async () => {
  let requestObj;
  const api = new AlexApi();
  api.request = async (url, opts) => { requestObj = { url, opts }; return {}; };
  await api.runMission("mission_X");
  assert.equal(requestObj.url, "/api/v1/missions/mission_X/run");
  assert.equal(requestObj.opts.method, "POST");
  assert.equal(requestObj.opts.headers["Content-Type"], "application/json");
});

// 2. WorkspaceDataController Tests
test("WorkspaceDataController loadMissions concurrency protection and deduplication", async () => {
  let fetchCount = 0;
  const api = new AlexApi();
  api.getMissions = async () => { fetchCount++; return { items: [] }; };
  api.getMissionRuns = async () => { fetchCount++; return { items: [] }; };
  
  const ctrl = new WorkspaceDataController(api, () => {});
  ctrl.loadMissions();
  ctrl.loadMissions(); // Duplicate while loading
  assert.equal(ctrl.missionsLoading, true);
  
  // Wait for tick
  await new Promise(r => setTimeout(r, 0));
  assert.equal(fetchCount, 2); // 1 getMissions + 1 getMissionRuns
  assert.equal(ctrl.missionsLoading, false);
});

test("WorkspaceDataController loadMissions error no retry loop", async () => {
  const api = new AlexApi();
  api.getMissions = async () => { throw new Error("fail"); };
  api.getMissionRuns = async () => { return { items: [] }; };
  
  const ctrl = new WorkspaceDataController(api, () => {});
  ctrl.loadMissions();
  await new Promise(r => setTimeout(r, 0));
  
  assert.equal(ctrl.missionsError, "Loi khi tai Missions. Vui long thu lai.");
  
  let fetchCount = 0;
  api.getMissions = async () => { fetchCount++; return { items: [] }; };
  ctrl.loadMissions(); // Without force, should not retry error
  await new Promise(r => setTimeout(r, 0));
  assert.equal(fetchCount, 0);
  
  ctrl.loadMissions(true); // Explicit refresh
  await new Promise(r => setTimeout(r, 0));
  assert.equal(fetchCount, 1);
});

test("WorkspaceDataController runMission single flight and reload", async () => {
  let reloaded = false;
  const api = new AlexApi();
  api.runMission = async () => { return {}; };
  api.getMissions = async () => { reloaded = true; return { items: [] }; };
  api.getMissionRuns = async () => { return { items: [] }; };
  
  const ctrl = new WorkspaceDataController(api, () => {});
  ctrl.runMission("test1");
  ctrl.runMission("test1"); // Prevented
  assert.equal(ctrl.missionRunInFlight.size, 1);
  
  await new Promise(r => setTimeout(r, 0));
  assert.equal(ctrl.missionRunInFlight.size, 0);
  assert.equal(reloaded, true);
});

test("WorkspaceDataController runMission failure sets missionsError", async () => {
  const api = new AlexApi();
  api.runMission = async () => { throw new Error("run failed"); };
  api.getMissions = async () => { return { items: [] }; };
  api.getMissionRuns = async () => { return { items: [] }; };
  
  const ctrl = new WorkspaceDataController(api, () => {});
  ctrl.runMission("test1");
  await new Promise(r => setTimeout(r, 0));
  assert.equal(ctrl.missionsError, "Loi khi chay Mission test1.");
});

test("WorkspaceDataController saveMission single flight and reload", async () => {
  let reloaded = false;
  const api = new AlexApi();
  api.saveMission = async () => { return {}; };
  api.getMissions = async () => { reloaded = true; return { items: [] }; };
  api.getMissionRuns = async () => { return { items: [] }; };
  
  const ctrl = new WorkspaceDataController(api, () => {});
  const p1 = ctrl.saveMission("test1", { name: "t", steps: [] });
  const p2 = ctrl.saveMission("test1", { name: "t", steps: [] }); // Prevented
  assert.equal(ctrl.missionSaveInFlight.size, 1);
  
  const [res1, res2] = await Promise.all([p1, p2]);
  
  assert.equal(res1, true); // First call succeeds
  assert.equal(res2, false); // Second call fails due to in-flight
  
  assert.equal(ctrl.missionSaveInFlight.size, 0);
  assert.equal(reloaded, true);
});

test("WorkspaceDataController saveMission failure returns false", async () => {
  const api = new AlexApi();
  api.saveMission = async () => { throw new Error("save fail"); };
  const ctrl = new WorkspaceDataController(api, () => {});
  const res = await ctrl.saveMission("test1", { name: "t", steps: [] });
  assert.equal(res, false);
});

// 3. UI Rendering & Editor Eligibility
test("renderMissions - editor eligibility and HTML rendering", () => {
  const state = {
    missionsPayload: [
      { id: "m1", name: "Safe Mission", source: "local", steps: [{ node_id: "esp01", target: "test_led", action: "set", value: true }] },
      { id: "m2", name: "Relay Mission", source: "local", steps: [{ node_id: "esp01", target: "relay_1", action: "set", value: true }] },
      { id: "m3", name: "Empty Mission", source: "local", steps: [] },
      { id: "m4", name: "XSS <script>alert(1)</script>", source: "local", steps: [{ node_id: "esp01", target: "test_led", action: "set", value: true }] },
      { id: "m5", name: "Payload Mission", source: "local", steps: [{ node_id: "esp01", target: "test_led", action: "set", value: true, payload: { value: false } }] },
      { id: "m6", name: "Null Steps", source: "local", steps: null },
      { id: "m7", name: "Object Steps", source: "local", steps: {} }
    ],
    missionRunsPayload: [
      { mission_id: "run1", name: "Run Partial", status: "partial", started_at: "now", completed_at: "now", steps: [
        { index: 0, target: "relay_1", action: "set", status: "failed", failure_reason: "restricted", safety_decision: { allowed: false, reason: "Restricted capability", verification_status: "UNVERIFIED", node_hardware_verified: false } },
        { index: 1, target: "test_led", action: "set", status: "confirmed", failure_reason: null, safety_decision: { allowed: true, reason: null, verification_status: "VERIFIED", node_hardware_verified: true } }
      ]}
    ],
    loading: false, error: null, runInFlight: new Set(), saveInFlight: new Set()
  };

  const html = renderMissions(state);
  
  // XSS Escaping
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);

  // Editor eligibility
  assert.match(html, /data-edit-mission="m1"/); // m1 is editable
  assert.doesNotMatch(html, /data-edit-mission="m2"/); // m2 restricted
  assert.doesNotMatch(html, /data-edit-mission="m3"/); // m3 empty

  // ADVANCED / READ ONLY should appear thrice (for m2, m3, m5) and INVALID / READ ONLY twice (m6, m7)
  const readOnlyMatches = html.match(/ADVANCED \/ READ ONLY/g);
  assert.ok(readOnlyMatches && readOnlyMatches.length >= 3);
  const invalidMatches = html.match(/INVALID \/ READ ONLY/g);
  assert.ok(invalidMatches && invalidMatches.length >= 2);

  // RESTRICTED HARDWARE badge for relay target
  assert.match(html, /RESTRICTED HARDWARE/);

  // Run History specific rendering
  assert.match(html, /Run Partial/);
  assert.match(html, /status-warning/); // "partial" status triggers warning class
  assert.match(html, /status-critical.*failed/); // step 0 failed
  assert.match(html, /restricted/); // failure reason printed
  
  // Safety decision rendering
  assert.match(html, /DENIED/);
  assert.match(html, /ALLOWED/);
  assert.match(html, /UNVERIFIED/); // node_hardware_verified false renders honestly
  assert.match(html, /VERIFIED/);
});

test("renderMissions - cached missions remain renderable with run error", () => {
  const state = {
    missionsPayload: [{ id: "m1", name: "M1", source: "local", steps: [] }],
    missionRunsPayload: [],
    loading: false,
    error: "Run failed error message",
    runInFlight: new Set(), saveInFlight: new Set()
  };
  const html = renderMissions(state);
  
  // Inline error should be rendered instead of replacing the whole view
  assert.match(html, /Run failed error message/);
  assert.match(html, /status-badge status-critical/);
  
  // The mission should still be visible
  assert.match(html, /M1/);
});
