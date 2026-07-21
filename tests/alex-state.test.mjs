import assert from "node:assert/strict";
import test from "node:test";

import {
  canTransitionAlexState,
  createAlexStateMachine,
  transitionAlexState,
} from "../static/core/alex-state.js";

test("ALEX follows the wake/listen/think/act/success lifecycle", () => {
  const machine = createAlexStateMachine();
  for (const state of ["wake", "listening", "thinking", "acting", "success", "idle"]) {
    assert.equal(machine.can(state), true);
    assert.equal(machine.transition(state), state);
  }
  assert.equal(machine.value, "idle");
});

test("ALEX rejects a transition that skips causal states", () => {
  assert.equal(canTransitionAlexState("idle", "success"), false);
  assert.throws(() => transitionAlexState("idle", "success"), /Invalid ALEX visual transition/);
});

test("offline recovers through idle before listening", () => {
  const machine = createAlexStateMachine("offline");
  assert.equal(machine.can("listening"), false);
  assert.equal(machine.transition("idle"), "idle");
  assert.equal(machine.transition("wake"), "wake");
});

test("repeated visual transitions remain stable during a 500-cycle soak", () => {
  const machine = createAlexStateMachine();
  const sequence = ["wake", "listening", "thinking", "acting", "speaking", "success", "idle"];
  for (let cycle = 0; cycle < 500; cycle += 1) {
    for (const state of sequence) machine.transition(state);
  }
  assert.equal(machine.value, "idle");
});
