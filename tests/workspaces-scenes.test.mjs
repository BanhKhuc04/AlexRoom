import { test } from "node:test";
import assert from "node:assert";
import { AlexApi } from "../static/core/api.js";
import { WorkspaceDataController } from "../static/core/workspace-data.js";

// Expose minimal escapeHtml
globalThis.escapeHtml = (str) => {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
};

globalThis.document = {
  hidden: false,
  addEventListener: () => {},
};

globalThis.window = {
  location: { protocol: "http:" },
};

globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };

// Expose dummy DOM classes for tests
class DummyElement {}
globalThis.HTMLElement = DummyElement;
globalThis.HTMLFormElement = DummyElement;
globalThis.HTMLButtonElement = DummyElement;
globalThis.HTMLDialogElement = DummyElement;
globalThis.HTMLInputElement = DummyElement;
globalThis.HTMLSelectElement = DummyElement;

class MockElement extends DummyElement {
  constructor(dataset = {}) {
    super();
    this.dataset = dataset;
    this.events = {};
    this.style = {};
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this._childNodes = [];
  }
  addEventListener(evt, cb) { this.events[evt] = cb; }
  querySelector() { return new MockElement(); }
  querySelectorAll() { return []; }
  reset() {}
  showModal() {}
  close() {}
}
test("AlexApi getScenes calls correct endpoint", async () => {
  let calledUrl = "";
  const api = new AlexApi();
  api.request = async (url) => { calledUrl = url; return { items: [] }; };
  await api.getScenes();
  assert.equal(calledUrl, "/api/v1/scenes");
});

test("AlexApi saveScene uses PUT and encoded URL", async () => {
  let requestObj;
  const api = new AlexApi();
  api.request = async (url, opts) => { requestObj = { url, opts }; return {}; };
  await api.saveScene("scene_1 2", { name: "test", steps: [] });
  assert.equal(requestObj.url, "/api/v1/scenes/scene_1%202");
  assert.equal(requestObj.opts.method, "PUT");
  assert.equal(requestObj.opts.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(requestObj.opts.body), { body: { name: "test", steps: [] } });
});

// 2. Controller State Tests
test("WorkspaceDataController loads scenes once", async () => {
  const api = new AlexApi();
  let calls = 0;
  api.getScenes = async () => { calls++; return { items: [] }; };

  const ctrl = new WorkspaceDataController(api, () => {});
  ctrl.loadScenes();
  ctrl.loadScenes(); // duplicate shouldn't refetch
  assert.equal(ctrl.scenesLoading, true);

  await new Promise(r => setTimeout(r, 10)); // let promises resolve
  assert.equal(calls, 1);
  assert.equal(ctrl.scenesLoading, false);
  assert.deepEqual(ctrl.scenesPayload, []);
});

test("WorkspaceDataController refreshScenes forces reload", async () => {
  const api = new AlexApi();
  let calls = 0;
  api.getScenes = async () => { calls++; return { items: [] }; };

  const ctrl = new WorkspaceDataController(api, () => {});
  ctrl.loadScenes();
  await new Promise(r => setTimeout(r, 10));
  ctrl.loadScenes(true); // force reload
  await new Promise(r => setTimeout(r, 10));
  assert.equal(calls, 2);
});

test("WorkspaceDataController initial load error caches error, no retry loop", async () => {
  const api = new AlexApi();
  let calls = 0;
  api.getScenes = async () => { calls++; throw new Error("Network Error"); };

  const ctrl = new WorkspaceDataController(api, () => {});
  ctrl.loadScenes();
  await new Promise(r => setTimeout(r, 10));

  assert.equal(ctrl.scenesError, "Loi khi tai du lieu Scenes.");
  assert.equal(ctrl.scenesPayload, null);

  ctrl.loadScenes(); // rerender should not refetch
  await new Promise(r => setTimeout(r, 10));
  assert.equal(calls, 1);
});

test("WorkspaceDataController duplicate save is blocked", async () => {
  const api = new AlexApi();
  let calls = 0;
  api.saveScene = async () => {
    calls++;
    await new Promise(r => setTimeout(r, 20));
    return {};
  };

  const ctrl = new WorkspaceDataController(api, () => {});
  ctrl.saveScene("s1", { name: "test" });
  const result = await ctrl.saveScene("s1", { name: "test" }); // duplicate
  assert.equal(result, false);
  assert.equal(calls, 1);
});

test("WorkspaceDataController save failure boolean and dialog lifecycle", async () => {
  const api = new AlexApi();
  api.getScenes = async () => { return { items: [{ id: "s1", name: "scene1" }] }; };
  api.saveScene = async () => { throw new Error("Save error"); };

  let notifies = 0;
  const ctrl = new WorkspaceDataController(api, () => { notifies++; });
  ctrl.loadScenes();
  await new Promise(r => setTimeout(r, 10));
  assert.equal(ctrl.scenesPayload.length, 1);

  const notifiesBeforeSave = notifies;
  const success = await ctrl.saveScene("s1", { name: "scene1_new" });
  assert.equal(success, false);
  assert.equal(ctrl.scenesPayload.length, 1); // cached data preserved
  assert.equal(notifies - notifiesBeforeSave, 0); // No notify on failure
});

// 3. Render Tests
test("renderWorkspace includes scenes when requested", async () => {
  const { renderWorkspace } = await import("../static/ui/workspaces.js");

  const container = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
  const snapshot = { device: { mode: "sleep" } };
  const scenesState = { payload: [], loading: false, error: null, saveInFlight: new Set() };

  renderWorkspace(container, "scenes", snapshot, { scenesState });

  assert.ok(container.innerHTML.includes("Mode hiện tại: <b>SLEEP</b>"));
  assert.ok(container.innerHTML.includes("Saved Scenes"));
});

test("renderScenes room modes only home/study/sleep/away", async () => {
  const { renderWorkspace } = await import("../static/ui/workspaces.js");
  const container = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
  renderWorkspace(container, "scenes", { device: { mode: "home" } }, { scenesState: { payload: [] } });
  const html = container.innerHTML;

  assert.match(html, /data-room-mode="home">KÍCH HOẠT LẠI/);
  assert.match(html, /data-room-mode="study"/);
  assert.match(html, /data-room-mode="sleep"/);
  assert.match(html, /data-room-mode="away"/);
  assert.doesNotMatch(html, /data-room-mode="relax"/);
  assert.doesNotMatch(html, /data-room-mode="energy saving"/);
});

test("renderScenes - editor eligibility and HTML rendering", async () => {
  const { renderWorkspace } = await import("../static/ui/workspaces.js");
  const state = {
    payload: [
      { id: "s1", name: "Safe test_led editable", source: "local", steps: [{ node_id: "esp01", target: "test_led", action: "set", value: true }] },
      { id: "s2", name: "Relay read only", source: "local", steps: [{ node_id: "esp01", target: "relay_1", action: "set", value: true }] },
      { id: "s3", name: "Custom payload read only", source: "local", steps: [{ node_id: "esp01", target: "test_led", action: "set", value: true, payload: { value: false } }] },
      { id: "s4", name: "Unknown target read only", source: "local", steps: [{ node_id: "esp01", target: "other", action: "set", value: true }] },
      { id: "s5", name: "Malformed collection read only", source: "local", steps: {} },
      { id: "s6", name: "XSS <script>alert(1)</script>", source: "local", steps: [] },
      { id: "home", name: "Home", safety_level: "safe", steps: [], execution: "backend_mode_contract" },
      { id: "s8", name: "Unknown top-level metadata", source: "local", steps: [], unknown_field: 123 },
      { id: "s9", name: "Unknown step field", source: "local", steps: [{ node_id: "esp01", target: "test_led", action: "set", value: true, extra: 1 }] },
      { id: "missing_steps", name: "Missing Steps", source: "local" }
    ],
    loading: false, error: null, saveInFlight: new Set()
  };

  const container = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
  renderWorkspace(container, "scenes", { device: { mode: "home" } }, { scenesState: state });
  const html = container.innerHTML;

  // XSS Escaping
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);

  // Editor eligibility
  assert.match(html, /data-edit-scene="s1"/); // s1 is editable
  assert.doesNotMatch(html, /data-edit-scene="s2"/); // s2 restricted
  assert.doesNotMatch(html, /data-edit-scene="s3"/); // s3 restricted
  assert.doesNotMatch(html, /data-edit-scene="s4"/); // s4 restricted
  assert.doesNotMatch(html, /data-edit-scene="s5"/); // s5 restricted
  assert.doesNotMatch(html, /data-edit-scene="home"/); // home has backend metadata
  assert.doesNotMatch(html, /data-edit-scene="s8"/); // unknown top-level metadata
  assert.doesNotMatch(html, /data-edit-scene="s9"/); // unknown step field
  assert.doesNotMatch(html, /data-edit-scene="missing_steps"/); // missing steps

  // ADVANCED / READ ONLY should appear for restricted ones
  const readOnlyMatches = html.match(/ADVANCED \/ READ ONLY/g);
  assert.ok(readOnlyMatches && readOnlyMatches.length === 7);

  // RESTRICTED HARDWARE badge for relay target
  assert.match(html, /RESTRICTED HARDWARE/);

  // INVALID FORMAT for malformed collection
  assert.match(html, /INVALID FORMAT/);
});

test("renderScenes stable ID and source preservation", async () => {
  const { renderWorkspace } = await import("../static/ui/workspaces.js");
  const state = {
    payload: [{ id: "test_stable_id", name: "Stable", source: "external", steps: [] }],
    loading: false, error: null, saveInFlight: new Set()
  };
  const container = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
  renderWorkspace(container, "scenes", { device: { mode: "home" } }, { scenesState: state });
  const html = container.innerHTML;

  assert.match(html, /Nguồn: external/);
  assert.match(html, /data-edit-scene="test_stable_id"/);
});

// 4. Editor State Regression Tests
test("Editor State Regression A: ON, OFF, ON -> remove middle step -> save", async () => {
  const { renderWorkspace } = await import("../static/ui/workspaces.js");

  let savedDef = null;
  const state = {
    payload: [{ id: "s1", name: "Scene A", source: "local", steps: [] }],
    loading: false, error: null, saveInFlight: new Set(),
    onSave: async (id, def) => { savedDef = def; return true; }
  };

  const stepsContainer = new MockElement();
  const container = new MockElement();
  const form = new MockElement();
  container.querySelector = (sel) => {
    if (sel === "#scene-form") return form;
    if (sel === "#sceneStepsContainer") return stepsContainer;
    return new MockElement();
  };
  const createMockStep = (val) => {
    const el = new MockElement();
    el.querySelector = () => {
      const sel = new MockElement();
      sel.value = val ? "true" : "false";
      return sel;
    };
    return el;
  };

  stepsContainer.querySelectorAll = (sel) => {
    if (sel === ".scene-step-editor") {
      return [createMockStep(true), createMockStep(true)]; // first and third ON
    }
    return [];
  };
  // formData fake
  const fd = new Map([["sceneName", "Test A"], ["editingId", "s1"]]);
  globalThis.FormData = class { constructor() { this.get = (k) => fd.get(k); } };

  renderWorkspace(container, "scenes", { device: { mode: "home" } }, { scenesState: state });

  // trigger submit
  if (!form.events["submit"]) throw new Error("form.events.submit is missing!");
  form.events["submit"]({ preventDefault: () => {} });

  assert.equal(savedDef.steps.length, 2);
  assert.equal(savedDef.steps[0].value, true);
  assert.equal(savedDef.steps[1].value, true);
});

test("Editor State Regression B: Existing step ON -> change to OFF -> Add -> first remains OFF", async () => {
  const { renderWorkspace } = await import("../static/ui/workspaces.js");

  const container = new MockElement();
  const addBtn = new MockElement();

  // Before clicking add, we simulate the current DOM having 1 step turned OFF
  const stepsContainer = new MockElement();
  stepsContainer.querySelectorAll = (sel) => {
    if (sel === ".scene-step-editor") {
      const el = new MockElement();
      el.querySelector = () => { const sel = new MockElement(); sel.value = "false"; return sel; };
      return [el];
    }
    return [];
  };
  container.querySelector = (sel) => {
    if (sel === "#addSceneActionBtn") return addBtn;
    if (sel === "#sceneStepsContainer") return stepsContainer;
    return new MockElement();
  };

  renderWorkspace(container, "scenes", { device: { mode: "home" } }, { scenesState: { payload: [] } });

  // wait, to capture renderSteps result we can just override container.innerHTML or step container innerHTML.
  // Actually, workspaces.js searches for #sceneStepsContainer on the container to set innerHTML!
  // Let's provide a getter/setter
  let inner = "";
  Object.defineProperty(stepsContainer, "innerHTML", { get: () => inner, set: (v) => { inner = v; } });

  // Call the click event for add
  if (addBtn.events["click"]) {
    addBtn.events["click"]();
  }

  // Now innerHTML should have 2 steps, and the first should have value="false" selected
  assert.match(inner, /value="false"\s*selected/);
  // Second should have value="true" selected (default)
  assert.match(inner, /value="true"\s*selected/);
});

test("Editor State Regression C: Open/edit fully supported Scene -> save -> exact steps preserved", async () => {
  const { renderWorkspace } = await import("../static/ui/workspaces.js");

  let savedDef = null;
  const originalSteps = [
    { node_id: "esp01", target: "test_led", action: "set", value: true },
    { node_id: "esp01", target: "test_led", action: "set", value: false }
  ];
  const state = {
    payload: [{ id: "s1", name: "Scene C", source: "local", steps: originalSteps }],
    loading: false, error: null, saveInFlight: new Set(),
    onSave: async (id, def) => { savedDef = def; return true; }
  };

  const stepsContainer = new MockElement();
  const container = new MockElement();
  const editBtn = new MockElement({ editScene: "s1" });
  const form = new MockElement();

  container.querySelectorAll = (sel) => {
    if (sel === "[data-edit-scene]") return [editBtn];
    return [];
  };
  container.querySelector = (sel) => {
    if (sel === "#scene-form") return form;
    if (sel === "#sceneStepsContainer") return stepsContainer;
    return new MockElement();
  };
  stepsContainer.querySelectorAll = (sel) => {
    if (sel === ".scene-step-editor") {
      return originalSteps.map(st => {
        const el = new MockElement();
        el.querySelector = () => {
          const sel = new MockElement();
          sel.value = st.value ? "true" : "false";
          return sel;
        };
        return el;
      });
    }
    return [];
  };

  renderWorkspace(container, "scenes", { device: { mode: "home" } }, { scenesState: state });

  const fd = new Map([["sceneName", "Scene C"], ["editingId", "s1"]]);
  globalThis.FormData = class { constructor() { this.get = (k) => fd.get(k); } };

  form.events["submit"]({ preventDefault: () => {} });

  assert.deepEqual(savedDef.steps, originalSteps);
});
