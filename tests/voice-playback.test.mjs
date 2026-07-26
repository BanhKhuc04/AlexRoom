import test from "node:test";
import assert from "node:assert";
import { VoicePlayback } from "../static/core/voice-playback.js";

// Mock the global performance object for tests
if (!global.performance) {
  global.performance = { now: () => Date.now() };
}

test("VoicePlayback instantiation", () => {
  const playback = new VoicePlayback();
  assert.strictEqual(playback.isPlaying, false);
  const diag = playback.getDiagnostics();
  assert.strictEqual(diag.playCount, 0);
  assert.strictEqual(diag.decodeErrors, 0);
  assert.strictEqual(diag.contextState, "none");
});

test("VoicePlayback missing AudioContext degrades gracefully", async () => {
  // Ensure no global AudioContext
  const originalContext = global.window?.AudioContext;
  if (global.window) {
    global.window.AudioContext = undefined;
    global.window.webkitAudioContext = undefined;
  } else {
    global.window = {};
  }
  
  const playback = new VoicePlayback();
  // Should not throw, should just return early
  await playback.playAudio(new ArrayBuffer(10));
  
  const diag = playback.getDiagnostics();
  assert.strictEqual(diag.playCount, 0);
  
  // Restore
  if (originalContext) {
    global.window.AudioContext = originalContext;
  }
});

test("VoicePlayback decoding failure is instrumented", async () => {
  class MockContext {
    constructor() {
      this.state = "running";
    }
    async decodeAudioData() {
      throw new Error("Invalid audio data");
    }
    close() {
      this.state = "closed";
      return Promise.resolve();
    }
  }
  
  global.window = { AudioContext: MockContext };
  
  const playback = new VoicePlayback();
  await playback.playAudio(new ArrayBuffer(10));
  
  const diag = playback.getDiagnostics();
  assert.strictEqual(diag.decodeErrors, 1);
  assert.strictEqual(playback.isPlaying, false);
});

test("VoicePlayback successful playback is instrumented", async () => {
  class MockBufferSource {
    constructor() {
      this.buffer = null;
      this.onended = null;
    }
    connect() {}
    start() {
      // Simulate ended immediately
      setTimeout(() => {
        if (this.onended) this.onended();
      }, 0);
    }
    stop() {}
    disconnect() {}
  }
  
  class MockContext {
    constructor() {
      this.state = "running";
      this.destination = {};
    }
    async decodeAudioData() {
      return {
        duration: 1.5,
        sampleRate: 16000
      };
    }
    createBufferSource() {
      return new MockBufferSource();
    }
    close() {
      this.state = "closed";
      return Promise.resolve();
    }
  }
  
  global.window = { 
    AudioContext: MockContext,
    atob: (str) => Buffer.from(str, 'base64').toString('binary')
  };
  
  const playback = new VoicePlayback();
  await playback.playAudio("YmFzZTY0dGVzdA=="); // base64test
  
  const diag = playback.getDiagnostics();
  assert.strictEqual(diag.decodeErrors, 0);
  assert.strictEqual(diag.playCount, 1);
  assert.strictEqual(diag.lastDurationSec, 1.5);
  assert.strictEqual(diag.lastSampleRate, 16000);
  assert.ok(diag.lastDecodeTimeMs >= 0);
});
