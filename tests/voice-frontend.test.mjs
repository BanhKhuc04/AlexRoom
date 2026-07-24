import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { VoiceClient } from "../static/core/voice-client.js";
import { AudioRecorder } from "../static/core/audio-recorder.js";
import { VoicePlayback } from "../static/core/voice-playback.js";

test("VoiceClient initializes cleanly and connects with mock WebSocket", async () => {
  class MockWebSocket {
    static OPEN = 1;
    constructor(url) {
      this.url = url;
      this.readyState = 1; // OPEN
      setTimeout(() => {
        if (this.onopen) this.onopen();
      }, 10);
    }
    send(data) {
      try {
        const parsed = JSON.parse(data);
        if (parsed.type === "auth") {
          setTimeout(() => {
            if (this.onmessage) {
              this.onmessage({ data: JSON.stringify({ type: "auth_ok", state: "listening" }) });
            }
          }, 15);
        }
      } catch {
        // Safe ignore
      }
    }
    close() { setTimeout(() => this.onclose?.(), 10); }
  }
  globalThis.WebSocket = MockWebSocket;

  const client = new VoiceClient();
  assert.equal(client.state, "idle");
  assert.equal(client.authenticated, false);

  const connected = await client.connect("test-key", "http://localhost:8000");
  assert.equal(connected, true);
  assert.equal(client.authenticated, true);
  client.close();
});

test("AudioRecorder exports valid 16kHz 16-bit mono WAV buffer", async () => {
  const recorder = new AudioRecorder();
  recorder.pcmChunks = [new Float32Array(160)];
  const wavBuffer = await recorder.stop();

  assert.ok(wavBuffer instanceof ArrayBuffer);
  const view = new DataView(wavBuffer);
  // Check RIFF header
  const riff = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
  assert.equal(riff, "RIFF");
  // Check WAVE format
  const wave = String.fromCharCode(view.getUint8(8), view.getUint8(9), view.getUint8(10), view.getUint8(11));
  assert.equal(wave, "WAVE");
  // Check sample rate = 16000
  assert.equal(view.getUint32(24, true), 16000);
});

test("VoicePlayback manages state and stop cleanly", async () => {
  const playback = new VoicePlayback();
  assert.equal(playback.isPlaying, false);
  playback.stop();
  assert.equal(playback.isPlaying, false);
});

test("Service Worker cache version is updated to phase-1.0-v1", async () => {
  const swSource = await readFile(new URL("../static/sw.js", import.meta.url), "utf8");
  assert.match(swSource, /alex-nexus-mark3-phase-1.0-v1/);
  assert.match(swSource, /voice-client\.js/);
  assert.match(swSource, /audio-recorder\.js/);
  assert.match(swSource, /voice-playback\.js/);
});
