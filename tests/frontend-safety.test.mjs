import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("frontend relay commands use the central V1 gateway and no legacy relay route", async () => {
  const apiSource = await readFile(new URL("../static/core/api.js", import.meta.url), "utf8");
  const appSource = await readFile(new URL("../static/app.js", import.meta.url), "utf8");

  assert.doesNotMatch(apiSource, /\/api\/devices\/esp01\/relays/);
  assert.doesNotMatch(appSource, /controlRelay|waitForRelayAck/);
  assert.match(appSource, /requestDeviceCommand\(`relay_\$\{relayId\}`/);
  assert.doesNotMatch(apiSource, /risk_level:\s*["']safe["']/);
});

test("relay cards stay visibly restricted and not verified", async () => {
  const workspaceSource = await readFile(new URL("../static/ui/workspaces.js", import.meta.url), "utf8");
  assert.match(workspaceSource, /disabled>RESTRICTED/);
  assert.match(workspaceSource, /disabled>NOT VERIFIED/);
});

test("logical room modes do not claim a physical ACK lifecycle", async () => {
  const appSource = await readFile(new URL("../static/app.js", import.meta.url), "utf8");
  assert.doesNotMatch(appSource, /createDeviceCommand\(\{ deviceId: "alex-core\/room-mode"/);
  assert.match(appSource, /physical_actions\?\.length === 0/);
  assert.match(appSource, /EVIDENCE \/ API LOGICAL STATE/);
});
