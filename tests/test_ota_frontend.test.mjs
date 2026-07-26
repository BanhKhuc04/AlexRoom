import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("frontend OTA command includes confirmation and appropriate polling", async () => {
  const appSource = await readFile(new URL("../static/app.js", import.meta.url), "utf8");
  
  assert.match(appSource, /async function executeOtaCommand/);
  assert.match(appSource, /window\.confirm\(/);
  assert.match(appSource, /api\.requestOta\(/);
  assert.match(appSource, /otaInfo\?.state\?.status/);
  assert.match(appSource, /\["requested", "downloading", "installing", "rebooting"\]\.includes/);
});

test("frontend OTA UI correctly checks conditions before allowing update", async () => {
  const workspaceSource = await readFile(new URL("../static/ui/workspaces.js", import.meta.url), "utf8");
  
  // Verify that the OTA UI panel is appended
  assert.match(workspaceSource, /<article class="workspace-panel"><h2>ESP01 · Firmware \/ OTA<\/h2>/);
  // Verify that the button contains the data attribute
  assert.match(workspaceSource, /data-ota-target="\$\{escapeHtml\(availableVer\)\}"/);
  // Verify that button is disabled if not online, no update, or currently active
  assert.match(workspaceSource, /canUpdate \? "" : "disabled"/);
  
  // Verify event delegation for data-ota-target exists
  assert.match(workspaceSource, /querySelectorAll\("\[data-ota-target\]"\)/);
  assert.match(workspaceSource, /actions\.onOta\(/);
});

import { AlexApi } from "../static/core/api.js";

test("AlexApi getSnapshot behavioral tests for authentication and OTA polling", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const originalSessionStorage = globalThis.sessionStorage;

  try {
    const mockStorage = {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
    globalThis.sessionStorage = mockStorage;

    const pendingTimers = new Map();
    let nextTimerId = 1;
    globalThis.window = {
      setTimeout: (cb) => {
        const id = nextTimerId++;
        pendingTimers.set(id, cb);
        return id;
      },
      clearTimeout: (id) => {
        pendingTimers.delete(id);
      }
    };

    const requests = [];

    globalThis.fetch = async (url, options) => {
      requests.push({ url, headers: options?.headers ? new Headers(options.headers) : new Headers() });
      return {
        ok: true,
        json: async () => ({})
      };
    };

    const api = new AlexApi("http://localhost:8000");

    // 1. Unauthenticated
    api.setApiKey("");
    requests.length = 0;
    await api.getSnapshot();

    const unauthOtaReq = requests.find(r => r.url.includes("/api/v1/ota/esp01"));
    assert.equal(unauthOtaReq, undefined, "Unauthenticated getSnapshot MUST NOT request /api/v1/ota/esp01");
    for (const req of requests) {
      assert.equal(req.headers.has("X-Alex-Key"), false, `Unauthenticated request to ${req.url} MUST NOT send X-Alex-Key`);
    }

    // 2. Authenticated
    api.setApiKey("test-secret-key");
    requests.length = 0;
    await api.getSnapshot();

    const authOtaReq = requests.find(r => r.url.includes("/api/v1/ota/esp01"));
    assert.notEqual(authOtaReq, undefined, "Authenticated getSnapshot MUST request /api/v1/ota/esp01");
    assert.equal(authOtaReq.headers.get("X-Alex-Key"), "test-secret-key", "Authenticated request MUST send X-Alex-Key header");

  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
    globalThis.sessionStorage = originalSessionStorage;
  }
});
