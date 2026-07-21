import assert from "node:assert/strict";
import test from "node:test";

import { ALEX_VISUAL_STATES } from "../static/core/alex-state.js";
import { createAudioWaveform } from "../static/core/audio-waveform.js";
import { CORE_VISUAL_PROFILES, getCoreVisualProfile } from "../static/core/core-visuals.js";
import { createFrameLoop } from "../static/core/frame-loop.js";

test("all ten ALEX states have distinct semantic visual signatures", () => {
  assert.equal(Object.keys(CORE_VISUAL_PROFILES).length, ALEX_VISUAL_STATES.length);
  const signatures = ALEX_VISUAL_STATES.map((state) => JSON.stringify(getCoreVisualProfile(state)));
  assert.equal(new Set(signatures).size, ALEX_VISUAL_STATES.length);
  assert.ok(getCoreVisualProfile("idle").energy < getCoreVisualProfile("wake").energy);
  assert.equal(getCoreVisualProfile("offline").rotation, 0);
  assert.equal(getCoreVisualProfile("listening").wave, 1);
});

test("frame loop never owns more than one frame and cancels it on destroy", () => {
  let nextHandle = 1;
  const callbacks = new Map();
  const cancelled = [];
  const loop = createFrameLoop({
    requestFrame(callback) {
      const handle = nextHandle;
      nextHandle += 1;
      callbacks.set(handle, callback);
      return handle;
    },
    cancelFrame(handle) {
      cancelled.push(handle);
      callbacks.delete(handle);
    },
    render() {},
  });

  loop.start();
  loop.start();
  assert.equal(loop.diagnostics.pendingFrames, 1);
  const [handle, callback] = callbacks.entries().next().value;
  callbacks.delete(handle);
  callback(16);
  assert.equal(loop.diagnostics.renderedFrames, 1);
  assert.equal(loop.diagnostics.pendingFrames, 1);
  loop.destroy();
  assert.equal(loop.diagnostics.pendingFrames, 0);
  assert.equal(loop.diagnostics.destroyed, true);
  assert.equal(cancelled.length, 1);
});

test("microphone waveform releases graph, context and every media track", async () => {
  let trackStopped = false;
  let sourceDisconnected = false;
  let analyserDisconnected = false;
  let contextClosed = false;
  const track = { readyState: "live", stop() { trackStopped = true; this.readyState = "ended"; } };
  const stream = { getTracks: () => [track] };
  const analyser = {
    fftSize: 0,
    smoothingTimeConstant: 0,
    frequencyBinCount: 16,
    disconnect() { analyserDisconnected = true; },
    getByteTimeDomainData(bytes) { bytes.fill(128); },
  };
  const source = {
    connect() {},
    disconnect() { sourceDisconnected = true; },
  };
  class FakeAudioContext {
    state = "running";
    createAnalyser() { return analyser; }
    createMediaStreamSource() { return source; }
    async close() { contextClosed = true; this.state = "closed"; }
  }
  const waveform = createAudioWaveform(
    { mediaDevices: { getUserMedia: async () => stream } },
    { AudioContext: FakeAudioContext },
  );

  assert.equal(await waveform.start(), true);
  assert.equal(waveform.diagnostics.liveTracks, 1);
  assert.equal(waveform.samples(8, 0, 1).length, 8);
  await waveform.stop();
  assert.deepEqual(waveform.diagnostics, { mode: "synthetic", hasContext: false, hasStream: false, liveTracks: 0 });
  assert.equal(trackStopped, true);
  assert.equal(sourceDisconnected, true);
  assert.equal(analyserDisconnected, true);
  assert.equal(contextClosed, true);
});

