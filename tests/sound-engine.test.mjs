import assert from "node:assert/strict";
import test from "node:test";

import { createSoundEngine, normalizeSoundSettings } from "../static/core/sound-engine.js";

class FakeParam {
  values = [];
  setTargetAtTime(value) { this.values.push(value); }
  setValueAtTime(value) { this.values.push(value); }
  exponentialRampToValueAtTime(value) { this.values.push(value); }
}

class FakeNode {
  gain = new FakeParam();
  frequency = new FakeParam();
  connect() { return this; }
  disconnect() { this.disconnected = true; }
  addEventListener(_name, callback) { this.onEnded = callback; }
  start() {}
  stop() { this.onEnded?.(); }
}

let contextInstances = 0;
class FakeAudioContext {
  constructor() { contextInstances += 1; }
  state = "running";
  currentTime = 1;
  destination = new FakeNode();
  createGain() { return new FakeNode(); }
  createOscillator() { return new FakeNode(); }
  async resume() { this.state = "running"; }
  async close() { this.state = "closed"; }
}

test("sound engine owns one AudioContext and suppresses duplicate cues", async () => {
  contextInstances = 0;
  let time = 1000;
  const engine = createSoundEngine({ AudioContext: FakeAudioContext, now: () => time });
  assert.equal(await engine.unlock(), true);
  assert.equal(await engine.unlock(), true);
  assert.equal(contextInstances, 1);
  assert.equal(engine.play("wake"), true);
  assert.equal(engine.play("wake"), false);
  time += 200;
  assert.equal(engine.play("wake"), true);
  await engine.destroy();
  assert.deepEqual(engine.diagnostics, { hasContext: false, unlocked: false, destroyed: true, mode: "normal", ducked: false, activePriority: 2 });
});

test("priority, ducking, silent/night modes and failure isolation are deterministic", async () => {
  let time = 2000;
  const engine = createSoundEngine({ AudioContext: FakeAudioContext, now: () => time });
  await engine.unlock();
  assert.equal(engine.play("critical"), true);
  time += 10;
  assert.equal(engine.play("processing_delay"), false);
  engine.setTtsDucking(true);
  assert.equal(engine.diagnostics.ducked, true);
  assert.equal(engine.configure({ mode: "night" }).mode, "night");
  assert.equal(engine.configure({ mode: "silent" }).mode, "silent");
  time += 1000;
  assert.equal(engine.play("warning"), false);
  await engine.destroy();
});

test("sound settings normalize persistence payloads safely", () => {
  const settings = normalizeSoundSettings({ mode: "unknown", master: 4, alerts: -2, ambience: 0.25 });
  assert.equal(settings.mode, "normal");
  assert.equal(settings.master, 1);
  assert.equal(settings.alerts, 0);
  assert.equal(settings.ambience, 0.25);
});
