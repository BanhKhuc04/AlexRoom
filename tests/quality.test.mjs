import assert from "node:assert/strict";
import test from "node:test";

import { createMotionProfile, normalizeQualityMode } from "../static/core/quality.js";

test("unknown quality settings safely fall back to balanced", () => {
  assert.equal(normalizeQualityMode("ultra"), "balanced");
  assert.equal(normalizeQualityMode(null), "balanced");
});

test("reduced motion overrides all animation intensities", () => {
  const profile = createMotionProfile("cinematic", true);
  assert.equal(profile.animationScale, 0);
  assert.equal(profile.particles, 0);
  assert.equal(profile.reducedMotion, true);
});

test("quality profiles are ordered by visual intensity", () => {
  const performance = createMotionProfile("performance", false);
  const balanced = createMotionProfile("balanced", false);
  const cinematic = createMotionProfile("cinematic", false);
  assert.ok(performance.animationScale < balanced.animationScale);
  assert.ok(balanced.animationScale < cinematic.animationScale);
});
