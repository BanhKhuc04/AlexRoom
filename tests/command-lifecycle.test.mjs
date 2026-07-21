import assert from "node:assert/strict";
import test from "node:test";

import {
  createDeviceCommand,
  isTerminalCommandPhase,
  transitionCommand,
} from "../static/core/command-lifecycle.js";

test("device command is only confirmed after waiting for reported state", () => {
  let command = createDeviceCommand({
    id: "cmd-1",
    deviceId: "esp01/relay_1",
    action: "ON",
    now: "2026-07-21T00:00:00.000Z",
  });
  command = transitionCommand(command, "sending", { now: "2026-07-21T00:00:01.000Z" });
  command = transitionCommand(command, "waiting_ack", { now: "2026-07-21T00:00:02.000Z" });
  command = transitionCommand(command, "accepted", { now: "2026-07-21T00:00:02.200Z" });
  command = transitionCommand(command, "waiting_reported_state", { now: "2026-07-21T00:00:02.400Z" });
  command = transitionCommand(command, "confirmed", {
    now: "2026-07-21T00:00:03.000Z",
    acknowledgmentSource: "mqtt_reported_state",
  });

  assert.equal(command.phase, "confirmed");
  assert.equal(command.acknowledgmentSource, "mqtt_reported_state");
  assert.equal(isTerminalCommandPhase(command.phase), true);
});

test("waiting command can time out with a user-readable reason", () => {
  let command = createDeviceCommand({ id: "cmd-2", deviceId: "esp01/relay_2", action: "OFF" });
  command = transitionCommand(command, "sending");
  command = transitionCommand(command, "waiting_ack");
  command = transitionCommand(command, "timed_out", { failureReason: "ESP01 không báo trạng thái trong 7 giây." });

  assert.equal(command.phase, "timed_out");
  assert.match(command.failureReason ?? "", /7 giây/);
});

test("a terminal command cannot be changed into a false success", () => {
  let command = createDeviceCommand({ id: "cmd-3", deviceId: "esp01/relay_3", action: "ON" });
  command = transitionCommand(command, "sending");
  command = transitionCommand(command, "failed", { failureReason: "MQTT offline" });

  assert.throws(() => transitionCommand(command, "confirmed"), /Invalid command transition/);
});

test("retry returns through sending and never skips ACK causality", () => {
  let command = createDeviceCommand({ id: "cmd-4", deviceId: "esp01/test_led", action: "set" });
  command = transitionCommand(command, "sending");
  command = transitionCommand(command, "waiting_ack");
  command = transitionCommand(command, "retrying");
  command = transitionCommand(command, "sending");
  command = transitionCommand(command, "waiting_ack");
  assert.throws(() => transitionCommand(command, "confirmed"), /Invalid command transition/);
});
