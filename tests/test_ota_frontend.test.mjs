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

test("api.js exposes requestOta and fetches otaInfo in getSnapshot", async () => {
  const apiSource = await readFile(new URL("../static/core/api.js", import.meta.url), "utf8");
  
  assert.match(apiSource, /async requestOta/);
  assert.match(apiSource, /\/api\/v1\/ota\/esp01/);
  assert.match(apiSource, /otaInfo:/);
});
