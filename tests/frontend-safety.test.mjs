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

test("device safety labels and permissions are rendered from registry fields", async () => {
  const workspaceSource = await readFile(new URL("../static/ui/workspaces.js", import.meta.url), "utf8");
  assert.match(workspaceSource, /capability\?\.risk_level/);
  assert.match(workspaceSource, /capability\?\.verification_status/);
  assert.match(workspaceSource, /capability\?\.command_allowed !== true/);
  assert.match(workspaceSource, /ledCapability\?\.command_allowed/);
  assert.doesNotMatch(workspaceSource, /disabled>RESTRICTED/);
  assert.doesNotMatch(workspaceSource, /disabled>NOT VERIFIED/);
});

test("online connectivity is displayed separately from verification truth", async () => {
  const workspaceSource = await readFile(new URL("../static/ui/workspaces.js", import.meta.url), "utf8");
  const presenceSource = await readFile(new URL("../static/ui/presence-view.js", import.meta.url), "utf8");
  const commandSource = await readFile(new URL("../static/ui/presence-commands.js", import.meta.url), "utf8");
  assert.match(workspaceSource, /ESP01 VERIFY \/ \$\{nodeVerification\}/);
  assert.match(workspaceSource, /v1Device\?\.verification_status/);
  assert.match(presenceSource, /v1Device\?\.verification_status/);
  assert.match(commandSource, /v1Device\?\.connection/);
  assert.match(commandSource, /v1Device\?\.verification_status/);
  assert.match(commandSource, /v1Device\?\.hardware_verified/);
  assert.doesNotMatch(presenceSource, /connection.*hardware_verified/);
});

test("logical room modes do not claim a physical ACK lifecycle", async () => {
  const appSource = await readFile(new URL("../static/app.js", import.meta.url), "utf8");
  assert.doesNotMatch(appSource, /createDeviceCommand\(\{ deviceId: "alex-core\/room-mode"/);
  assert.match(appSource, /physical_actions\?\.length === 0/);
  assert.match(appSource, /EVIDENCE \/ API LOGICAL STATE/);
});
