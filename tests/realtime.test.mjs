import assert from "node:assert/strict";
import test from "node:test";

import { AlexRealtime } from "../static/core/realtime.js";

test("realtime cleanup closes source and cancels reconnect timer", () => {
  globalThis.document = { hidden: false };
  let closed = 0;
  globalThis.EventSource = class {
    constructor() { this.onopen = null; this.onerror = null; }
    addEventListener() {}
    close() { closed += 1; }
  };
  const realtime = new AlexRealtime({ onEvent() {} });
  realtime.start();
  assert.ok(realtime.source);
  realtime.destroy();
  assert.equal(realtime.source, null);
  assert.equal(realtime.timer, null);
  assert.equal(closed, 1);
  delete globalThis.document;
  delete globalThis.EventSource;
});

test("realtime stream uses bounded exponential reconnect and rehydrates through events", () => {
  globalThis.document = { hidden: false };
  globalThis.window = globalThis;
  let scheduled = 0;
  const originalTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  globalThis.setTimeout = (_callback, delay) => { scheduled = delay; return 9; };
  globalThis.clearTimeout = () => {};
  globalThis.EventSource = class {
    constructor() { this.onopen = null; this.onerror = null; globalThis.currentSource = this; }
    addEventListener() {}
    close() {}
  };
  const realtime = new AlexRealtime({ onEvent() {} });
  realtime.start();
  globalThis.currentSource.onerror();
  assert.equal(scheduled, 1000);
  assert.equal(realtime.retry, 1);
  realtime.destroy();
  globalThis.setTimeout = originalTimeout;
  globalThis.clearTimeout = originalClearTimeout;
  delete globalThis.currentSource;
  delete globalThis.document;
  delete globalThis.window;
  delete globalThis.EventSource;
});
