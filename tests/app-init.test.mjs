import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

// Mock minimal DOM environment for app.js static initialization test
class MockElement {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.dataset = {};
    this.style = { setProperty() {} };
    this.classList = {
      toggle: () => {},
      add: () => {},
      remove: () => {},
      contains: () => false,
    };
    this.listeners = {};
    this.value = "";
    this.checked = false;
    this.textContent = "";
    this.innerHTML = "";
    this.hidden = false;
    this.className = "";
  }
  addEventListener(event, listener) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(listener);
  }
  removeEventListener(event, listener) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(l => l !== listener);
    }
  }
  setAttribute(key, val) { this[key] = val; }
  removeAttribute(key) { delete this[key]; }
  querySelector() { return new MockElement(); }
  querySelectorAll() { return [new MockElement("button")]; }
  getBoundingClientRect() { return { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600 }; }
  focus() {}
  showModal() {}
  close() {}
  getContext() {
    const dummyGradient = { addColorStop() {} };
    const dummyContext = new Proxy({}, {
      get: (_target, prop) => {
        if (prop === "createLinearGradient" || prop === "createRadialGradient") {
          return () => dummyGradient;
        }
        return () => {};
      }
    });
    return dummyContext;
  }
}

class MockHTMLElement extends MockElement {}
class MockHTMLButtonElement extends MockElement {}
class MockHTMLInputElement extends MockElement {}
class MockHTMLTextAreaElement extends MockElement {}
class MockHTMLSelectElement extends MockElement {}

test("static/app.js contains valid quality, voice, and init references", async () => {
  const appSource = await readFile(new URL("../static/app.js", import.meta.url), "utf8");

  // Verify quality is declared in module scope
  assert.match(appSource, /let quality\s*=/);
  assert.match(appSource, /let userReducedMotion\s*=/);
  assert.match(appSource, /let soundSettings\s*=/);

  // Verify voice client, audio recorder, voice playback instantiation
  assert.match(appSource, /const voicePlayback = new VoicePlayback\(\);/);
  assert.match(appSource, /const voiceClient = new VoiceClient\(/);
  assert.match(appSource, /const audioRecorder = new AudioRecorder\(/);

  // Verify init calls applyExperience with quality
  assert.match(appSource, /async function init\(\)\s*\{[\s\S]*?applyExperience\(quality,\s*userReducedMotion\);/);

  // Verify microphone toggle wiring in bindEvents
  assert.match(appSource, /elements\.microphoneToggle\.addEventListener\("click",\s*\(\)\s*=>\s*\{/);
});

test("app.js module imports resolve and execute init path without ReferenceError", async () => {
  // Setup global mock DOM
  const elementMap = new Map();
  const getElement = (selector) => {
    if (!elementMap.has(selector)) {
      elementMap.set(selector, new MockElement());
    }
    return elementMap.get(selector);
  };

  const mockStorage = {
    getItem: (key) => (key === "alexQuality" ? "balanced" : null),
    setItem: () => {},
  };

  const mockResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };

  const mockEventSource = class {
    addEventListener() {}
    close() {}
  };

  const mockLocation = { protocol: "http:", host: "localhost:8000" };

  const mockWindow = {
    location: mockLocation,
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    localStorage: mockStorage,
    sessionStorage: mockStorage,
    ResizeObserver: mockResizeObserver,
    EventSource: mockEventSource,
    HTMLElement: MockHTMLElement,
    HTMLButtonElement: MockHTMLButtonElement,
    HTMLInputElement: MockHTMLInputElement,
    HTMLTextAreaElement: MockHTMLTextAreaElement,
    HTMLSelectElement: MockHTMLSelectElement,
    requestAnimationFrame: () => 1,
    cancelAnimationFrame: () => {},
    AudioContext: class {
      createGain() { return { connect() {}, gain: { value: 1 } }; }
      createOscillator() { return { connect() {}, start() {}, stop() {} }; }
    },
    setInterval: () => 100,
    setTimeout: (fn) => { setTimeout(fn, 0); return 101; },
    clearTimeout: () => {},
    clearInterval: () => {},
    addEventListener: () => {},
  };

  const mockDocument = {
    querySelector: (sel) => getElement(sel),
    querySelectorAll: () => [new MockElement("button")],
    addEventListener: () => {},
    documentElement: { style: { setProperty: () => {} } },
    body: { dataset: {}, style: {} },
    hidden: false,
  };

  Object.defineProperty(globalThis, "window", { value: mockWindow, configurable: true, writable: true });
  Object.defineProperty(globalThis, "document", { value: mockDocument, configurable: true, writable: true });
  Object.defineProperty(globalThis, "location", { value: mockLocation, configurable: true, writable: true });
  Object.defineProperty(globalThis, "localStorage", { value: mockStorage, configurable: true, writable: true });
  Object.defineProperty(globalThis, "sessionStorage", { value: mockStorage, configurable: true, writable: true });
  Object.defineProperty(globalThis, "ResizeObserver", { value: mockResizeObserver, configurable: true, writable: true });
  Object.defineProperty(globalThis, "EventSource", { value: mockEventSource, configurable: true, writable: true });
  Object.defineProperty(globalThis, "HTMLElement", { value: MockHTMLElement, configurable: true, writable: true });
  Object.defineProperty(globalThis, "HTMLButtonElement", { value: MockHTMLButtonElement, configurable: true, writable: true });
  Object.defineProperty(globalThis, "HTMLInputElement", { value: MockHTMLInputElement, configurable: true, writable: true });
  Object.defineProperty(globalThis, "HTMLTextAreaElement", { value: MockHTMLTextAreaElement, configurable: true, writable: true });
  Object.defineProperty(globalThis, "HTMLSelectElement", { value: MockHTMLSelectElement, configurable: true, writable: true });

  if (!("serviceWorker" in globalThis.navigator)) {
    Object.defineProperty(globalThis.navigator, "serviceWorker", {
      value: { register: async () => {} },
      configurable: true,
      writable: true,
    });
  }

  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      health: { api: "online", mqtt: "connected" },
      device: { availability: "online", mode: "home" },
      config: { room_name: "AlexRoom" },
      events: [],
      v1Device: { connection: "online" }
    })
  });

  // Import app.js dynamically to execute top-level init()
  await import("../static/app.js?test=" + Date.now());

  // If we reach here without ReferenceError or throwing, initialization succeeded!
  assert.ok(true, "app.js init() executed cleanly");

  // Verify presenceView microphone wiring
  const micToggle = getElement("#microphoneToggle");
  assert.ok(micToggle.listeners.click, "microphoneToggle click listener must be registered");
});
