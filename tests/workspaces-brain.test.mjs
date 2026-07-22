import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { renderBrain } from "../static/ui/workspaces.js";
import { AlexApi } from "../static/core/api.js";

test("getBrain calls correct endpoint", async () => {
  let requestedUrl = "";
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async (url) => { requestedUrl = url; return {}; };

  await api.getBrain();
  assert.equal(requestedUrl, "/api/v1/brain");
});

test("wakeBrain calls correct endpoint and method", async () => {
  let requestedUrl = "";
  let requestedMethod = "";
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async (url, options) => { requestedUrl = url; requestedMethod = options?.method; return {}; };

  await api.wakeBrain();
  assert.equal(requestedUrl, "/api/v1/brain/wake");
  assert.equal(requestedMethod, "POST");
});

test("renderBrain offline state allows wake", () => {
  const html = renderBrain({ payload: { state: "offline", host: "192.168.1.100", hardware_verified: true }, loading: false, error: null, wakeInFlight: false });
  assert.match(html, /WAKE BRAIN/);
  assert.match(html, /CONFIGURED/);
  assert.match(html, /class="error">OFFLINE<\/dd>/);
  assert.doesNotMatch(html, /disabled>WAKE BRAIN/);
});

test("renderBrain waking state disables wake and shows WAKING...", () => {
  const html = renderBrain({ payload: { state: "waking", host: "192.168.1.100", hardware_verified: false }, loading: false, error: null, wakeInFlight: false });
  assert.match(html, /WAKING\.\.\./);
  assert.match(html, /disabled>WAKING\.\.\./);
});

test("renderBrain degraded state allows wake", () => {
  const html = renderBrain({ payload: { state: "degraded", host: "192.168.1.100", hardware_verified: false }, loading: false, error: null, wakeInFlight: false });
  assert.match(html, /WAKE BRAIN/);
  assert.doesNotMatch(html, /disabled>WAKE BRAIN/);
});

test("renderBrain empty/unknown fields handled safely", () => {
  const html = renderBrain({ payload: { state: "offline", host: null, hardware_verified: false }, loading: false, error: null, wakeInFlight: false });
  assert.match(html, /Chưa cấu hình/);
  assert.match(html, /NOT CONFIGURED/);
  assert.match(html, /disabled>WAKE BRAIN/);
});

test("renderBrain XSS escaping", () => {
  const html = renderBrain({ payload: { state: "<script>", host: "<evil>" }, loading: false, error: "<err>", wakeInFlight: false });
  assert.match(html, /&lt;evil&gt;/);
  assert.match(html, /&lt;SCRIPT&gt;/);
  assert.match(html, /&lt;err&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("renderBrain does not invent PORT 22", () => {
  const html = renderBrain({ payload: { state: "offline", host: "192.168.1.100", hardware_verified: true }, loading: false, error: null, wakeInFlight: false });
  assert.doesNotMatch(html, />22</);
  assert.doesNotMatch(html, /PORT/);
});

test("cached brain refetch and polling behavior (source analysis)", async () => {
  const appSource = await readFile(new URL("../static/app.js", import.meta.url), "utf8");
  // Error retry loop fixed
  assert.match(appSource, /if \(!force && \(brainPayload \|\| brainError\)\) return;/);
  assert.match(appSource, /if \(brainLoading\) return;/);
  // Bounded polling
  assert.match(appSource, /const BRAIN_WAKE_POLL_INTERVAL_MS = 2000;/);
  assert.match(appSource, /const BRAIN_WAKE_MAX_POLLS = 23;/);
  assert.match(appSource, /brainWakePollCount < BRAIN_WAKE_MAX_POLLS/);
  // Leave Brain cancels polling
  assert.match(appSource, /if \(workspace !== "brain"\) cancelBrainPolling\(\);/);
  // Wake flight
  assert.match(appSource, /if \(brainWakeInFlight\) return;/);
  assert.match(appSource, /onRefresh:\s*\(\)\s*=>\s*loadBrain\(true\)/);
});
