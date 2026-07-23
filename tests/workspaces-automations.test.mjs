import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { renderAutomations } from "../static/ui/workspaces.js";
import { AlexApi } from "../static/core/api.js";
import { WorkspaceDataController, generateId } from "../static/core/workspace-data.js";

// ============================================================
// 1. API CONTRACT
// ============================================================

test("getAutomations calls correct endpoint", async () => {
  let requestedUrl = "";
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async (url) => { requestedUrl = url; return {}; };
  await api.getAutomations();
  assert.equal(requestedUrl, "/api/v1/automations");
});

test("saveAutomation - URL encoded, PUT, Content-Type, body", async () => {
  let reqUrl = "", reqMethod = "", reqHeaders = {}, reqBody = "";
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async (url, options) => {
    reqUrl = url;
    reqMethod = options.method;
    reqHeaders = options.headers ?? {};
    reqBody = options.body;
    return {};
  };

  const def = { name: "test", enabled: true, trigger: { type: "time", at: "08:00" }, conditions: [], actions: [], source: "local" };
  await api.saveAutomation("id with spaces", def);

  assert.equal(reqUrl, "/api/v1/automations/id%20with%20spaces");
  assert.equal(reqMethod, "PUT");
  assert.equal(reqHeaders["Content-Type"], "application/json");
  const parsed = JSON.parse(reqBody);
  assert.equal(parsed.body.name, "test");
  assert.equal(parsed.body.id, undefined);
  assert.equal(parsed.body.lastRun, undefined);
});

test("runAutomation - URL encoded, POST, Content-Type, body", async () => {
  let reqUrl = "", reqMethod = "", reqHeaders = {}, reqBody = "";
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async (url, options) => {
    reqUrl = url; reqMethod = options.method; reqHeaders = options.headers ?? {}; reqBody = options.body; return {};
  };
  await api.runAutomation("my id");
  assert.equal(reqUrl, "/api/v1/automations/my%20id/run");
  assert.equal(reqMethod, "POST");
  assert.equal(reqHeaders["Content-Type"], "application/json");
  assert.equal(JSON.parse(reqBody).type, "manual");
});

// ============================================================
// 2. generateId HELPER
// ============================================================

test("generateId returns string", () => {
  const id = generateId();
  assert.equal(typeof id, "string");
  assert.ok(id.length > 0);
});

// ============================================================
// 3. renderAutomations UI BEHAVIOR
// ============================================================

test("renderAutomations shows Run Now only for manual rules", () => {
  const state = {
    payload: [
      { id: "1", name: "manual rule", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [] },
      { id: "2", name: "time rule", enabled: true, trigger: { type: "time", at: "12:00" }, conditions: [], actions: [] },
      { id: "3", name: "device rule", enabled: true, trigger: { type: "device_state" }, conditions: [], actions: [] },
    ],
    loading: false, error: null, runInFlight: new Set()
  };
  const html = renderAutomations(state);
  assert.match(html, /data-run-automation="1"/);
  assert.doesNotMatch(html, /data-run-automation="2"/);
  assert.doesNotMatch(html, /data-run-automation="3"/);
  assert.match(html, /AUTO ONLY/);
});

test("renderAutomations editor eligibility - unsupported action shapes are READ ONLY", () => {
  const state = {
    payload: [
      { id: "1", name: "manual + relay", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [{ target: "relay_2", action: "on" }] },
      { id: "2", name: "manual + unknown", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [{ target: "unknown", action: "set" }] },
      { id: "3", name: "manual + empty actions", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [] },
    ],
    loading: false, error: null, runInFlight: new Set()
  };
  const html = renderAutomations(state);
  assert.doesNotMatch(html, /data-edit-automation="1"/);
  assert.doesNotMatch(html, /data-edit-automation="2"/);
  assert.doesNotMatch(html, /data-edit-automation="3"/);
  assert.equal(html.match(/ADVANCED \/ READ ONLY/g).length, 3);
});

test("renderAutomations editor eligibility - exactly one supported action is editable", () => {
  const state = {
    payload: [
      { id: "1", name: "manual + supported", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [{ node_id: "esp01", target: "test_led", action: "set", value: true }] },
      { id: "2", name: "time + supported", enabled: true, trigger: { type: "time", at: "12:00" }, conditions: [], actions: [{ node_id: "esp01", target: "test_led", action: "set", value: false }] },
    ],
    loading: false, error: null, runInFlight: new Set()
  };
  const html = renderAutomations(state);
  assert.match(html, /data-edit-automation="1"/);
  assert.match(html, /data-edit-automation="2"/);
  assert.doesNotMatch(html, /ADVANCED \/ READ ONLY/);
});

test("renderAutomations shows test_led action summary clearly", () => {
  const state = {
    payload: [
      { id: "1", name: "led on", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [{ node_id: "esp01", target: "test_led", action: "set", value: true }] },
    ],
    loading: false, error: null, runInFlight: new Set()
  };
  const html = renderAutomations(state);
  assert.match(html, /Test LED/);
  assert.match(html, /BẬT/);
});

test("renderAutomations shows RESTRICTED for relay actions", () => {
  const state = {
    payload: [
      { id: "1", name: "relay rule", enabled: true, trigger: { type: "device_state" }, conditions: [], actions: [{ target: "relay_1", action: "on" }] },
    ],
    loading: false, error: null, runInFlight: new Set()
  };
  const html = renderAutomations(state);
  assert.match(html, /RESTRICTED HARDWARE/);
  assert.match(html, /relay_1/);
});

test("renderAutomations no risk_level fabricated in HTML output", () => {
  const state = {
    payload: [
      { id: "1", name: "r", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [{ node_id: "esp01", target: "test_led", action: "set", value: true }] },
    ],
    loading: false, error: null, runInFlight: new Set()
  };
  const html = renderAutomations(state);
  assert.doesNotMatch(html, /risk_level/);
});

test("renderAutomations honestly renders blockedReason without fake success", () => {
  const state = {
    payload: [
      { id: "1", name: "failed", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [], blockedReason: "safety_policy_denied", result: "failed" }
    ],
    loading: false, error: null, runInFlight: new Set()
  };
  const html = renderAutomations(state);
  assert.match(html, /safety_policy_denied/);
  assert.match(html, /failed/);
  assert.doesNotMatch(html, /completed/);
});

test("renderAutomations XSS escaping", () => {
  const state = {
    payload: [
      { id: "<script>", name: "<evil>", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [], source: "<xss>" }
    ],
    loading: false, error: null, runInFlight: new Set()
  };
  const html = renderAutomations(state);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;evil&gt;/);
});

// ============================================================
// 4. WORKSPACE DATA CONTROLLER
// ============================================================

test("WorkspaceDataController initial automation load calls API once", async () => {
  let calls = 0;
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async () => { calls++; return { items: [] }; };
  const wdc = new WorkspaceDataController(api, () => {});
  wdc.loadAutomations();
  await new Promise(r => setTimeout(r, 10));
  assert.equal(calls, 1);
});

test("WorkspaceDataController rerender does NOT refetch automations", async () => {
  let calls = 0;
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async () => { calls++; return { items: [] }; };
  const wdc = new WorkspaceDataController(api, () => {});
  wdc.loadAutomations();
  await new Promise(r => setTimeout(r, 10));
  wdc.loadAutomations(); // re-render - should not fetch
  wdc.loadAutomations();
  await new Promise(r => setTimeout(r, 5));
  assert.equal(calls, 1);
});

test("WorkspaceDataController explicit refresh refetches", async () => {
  let calls = 0;
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async () => { calls++; return { items: [] }; };
  const wdc = new WorkspaceDataController(api, () => {});
  wdc.loadAutomations();
  await new Promise(r => setTimeout(r, 10));
  wdc.loadAutomations(true); // explicit refresh
  await new Promise(r => setTimeout(r, 10));
  assert.equal(calls, 2);
});

test("WorkspaceDataController automation error does not retry loop on rerender", async () => {
  let calls = 0;
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async () => { calls++; throw new Error("fail"); };
  const wdc = new WorkspaceDataController(api, () => {});
  wdc.loadAutomations();
  await new Promise(r => setTimeout(r, 20));
  wdc.loadAutomations(); // re-render, should NOT retry
  await new Promise(r => setTimeout(r, 5));
  assert.equal(calls, 1);
  assert.ok(wdc.automationsError);
});

test("WorkspaceDataController explicit retry after error works", async () => {
  let calls = 0;
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async () => { calls++; throw new Error("fail"); };
  const wdc = new WorkspaceDataController(api, () => {});
  wdc.loadAutomations();
  await new Promise(r => setTimeout(r, 20));
  assert.equal(calls, 1);
  wdc.loadAutomations(true); // explicit retry
  await new Promise(r => setTimeout(r, 20));
  assert.equal(calls, 2);
});

test("WorkspaceDataController duplicate runAutomation same ID is blocked", async () => {
  let runCalls = 0;
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  let resolveFn;
  api.request = async (url) => {
    if (url.includes("/run")) runCalls++;
    return new Promise(r => { resolveFn = r; }).then(() => {});
  };
  const wdc = new WorkspaceDataController(api, () => {});
  wdc.runAutomation("id1");
  wdc.runAutomation("id1"); // duplicate - should be blocked
  wdc.runAutomation("id1");
  // Allow microtasks to process
  await new Promise(r => setTimeout(r, 5));
  if (resolveFn) resolveFn({});
  await new Promise(r => setTimeout(r, 5));
  assert.equal(runCalls, 1);
});

test("WorkspaceDataController duplicate saveAutomation same ID is blocked", async () => {
  let saveCalls = 0;
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  let resolveFn;
  api.request = async (url, options) => {
    if (options && options.method === "PUT") saveCalls++;
    return new Promise(r => { resolveFn = r; }).then(() => ({ saved: true }));
  };
  const wdc = new WorkspaceDataController(api, () => {});
  const def = { name: "t", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [] };
  const p1 = wdc.saveAutomation("id1", def);
  const p2 = wdc.saveAutomation("id1", def); // duplicate
  await new Promise(r => setTimeout(r, 5));
  if (resolveFn) resolveFn({ saved: true });
  const [res1, res2] = await Promise.all([p1, p2]);
  assert.equal(saveCalls, 1);
  assert.equal(res1, true);
  assert.equal(res2, false);
});

test("WorkspaceDataController saveAutomation failure returns false", async () => {
  const api = new AlexApi();
  api.saveAutomation = async () => { throw new Error("save fail"); };
  const wdc = new WorkspaceDataController(api, () => {});
  const res = await wdc.saveAutomation("id1", { name: "t", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [] });
  assert.equal(res, false);
});

test("WorkspaceDataController successful save triggers backend reload", async () => {
  let calls = 0;
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async () => { calls++; return { items: [], saved: true }; };
  const wdc = new WorkspaceDataController(api, () => {});
  const def = { name: "t", enabled: true, trigger: { type: "manual" }, conditions: [], actions: [] };
  await wdc.saveAutomation("id1", def);
  await new Promise(r => setTimeout(r, 10));
  // First call = save PUT, second call = reload GET
  assert.ok(calls >= 2);
});

test("WorkspaceDataController destroy cancels Brain polling", () => {
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async () => ({ state: "waking" });
  const wdc = new WorkspaceDataController(api, () => {});
  wdc.brainWakePollTimer = setTimeout(() => {}, 10000);
  wdc.destroy();
  assert.equal(wdc.brainWakePollTimer, null);
  assert.equal(wdc._destroyed, true);
});

// ============================================================
// 5. SOURCE ANALYSIS
// ============================================================

test("WorkspaceDataController architecture (source analysis)", async () => {
  const appSource = await readFile(new URL("../static/app.js", import.meta.url), "utf8");
  assert.match(appSource, /workspaceData\.loadAutomations\(\)/);
  assert.match(appSource, /workspaceData\.saveAutomation\(id, definition\)/);
  assert.match(appSource, /workspaceData\.runAutomation\(id\)/);
  assert.match(appSource, /workspaceData\.destroy\(\)/);
  assert.match(appSource, /saveInFlight: workspaceData\.automationSaveInFlight/);

  const wdcSource = await readFile(new URL("../static/core/workspace-data.js", import.meta.url), "utf8");
  assert.match(wdcSource, /loadAutomations\(force = false\)/);
  assert.match(wdcSource, /this\.loadAutomations\(true\)/);
  assert.match(wdcSource, /automationSaveInFlight/);
  assert.match(wdcSource, /destroy\(\)/);

  const workspacesSource = await readFile(new URL("../static/ui/workspaces.js", import.meta.url), "utf8");
  // No fabricated risk_level in automation creation
  assert.doesNotMatch(workspacesSource, /risk_level:\s*(["'])safe\1/);
  // Ensure the action explicitly targets the correct node and action structure
  assert.match(workspacesSource, /node_id:\s*(["'])esp01\1/);
  assert.match(workspacesSource, /target:\s*(["'])test_led\1/);
  assert.match(workspacesSource, /action:\s*(["'])set\1/);
  // Time validation present
  assert.match(workspacesSource, /isValidHHMM/);
  // Edit support
  assert.match(workspacesSource, /data-edit-automation/);
  // Source preserved on toggle
  assert.match(workspacesSource, /rule\.source \|\| "local_software"/);
  // generateId used
  assert.match(workspacesSource, /generateId\(\)/);
});
