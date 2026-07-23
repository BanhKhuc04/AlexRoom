import test from "node:test";
import assert from "node:assert";
import { AlexApi } from "../static/core/api.js";
import { WorkspaceDataController } from "../static/core/workspace-data.js";
import { renderBackup } from "../static/ui/workspaces.js";

// Expose minimal mock globals if needed
globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };

// 1. API Contract Tests
test("AlexApi getBackups calls correct endpoint", async () => {
  let requestedUrl = "";
  let requestInit = null;
  const api = new AlexApi();
  api.request = async (url, init) => {
    requestedUrl = url;
    requestInit = init;
    return {};
  };
  await api.getBackups();
  assert.equal(requestedUrl, "/api/v1/backups");
  assert.equal(requestInit?.method ?? "GET", "GET");
});

test("AlexApi createBackup uses POST and correct endpoint", async () => {
  let requestedUrl = "";
  let requestInit = null;
  const api = new AlexApi();
  api.request = async (url, init) => {
    requestedUrl = url;
    requestInit = init;
    return {};
  };
  await api.createBackup();
  assert.equal(requestedUrl, "/api/v1/backup");
  assert.equal(requestInit.method, "POST");
});

// 2. Controller Behavior Tests
test("WorkspaceDataController initial backup load calls API once", async () => {
  let calls = 0;
  const api = new AlexApi();
  api.getBackups = async () => { calls++; return { items: [], retention: 7, directory: "backups" }; };
  const ctrl = new WorkspaceDataController(api, () => {});
  
  ctrl.loadBackups();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(calls, 1);
});

test("WorkspaceDataController rerender does NOT refetch backups", async () => {
  let calls = 0;
  const api = new AlexApi();
  api.getBackups = async () => { calls++; return { items: [], retention: 7, directory: "backups" }; };
  const ctrl = new WorkspaceDataController(api, () => {});
  
  ctrl.loadBackups();
  await new Promise(r => setTimeout(r, 0));
  ctrl.loadBackups();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(calls, 1);
});

test("WorkspaceDataController explicit refresh refetches backups", async () => {
  let calls = 0;
  const api = new AlexApi();
  api.getBackups = async () => { calls++; return { items: [], retention: 7, directory: "backups" }; };
  const ctrl = new WorkspaceDataController(api, () => {});
  
  ctrl.loadBackups();
  await new Promise(r => setTimeout(r, 0));
  ctrl.loadBackups(true);
  await new Promise(r => setTimeout(r, 0));
  assert.equal(calls, 2);
});

test("WorkspaceDataController initial error does not retry loop on rerender", async () => {
  let calls = 0;
  const api = new AlexApi();
  api.getBackups = async () => { calls++; throw new Error("fail"); };
  const ctrl = new WorkspaceDataController(api, () => {});
  
  ctrl.loadBackups();
  await new Promise(r => setTimeout(r, 0));
  ctrl.loadBackups();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(calls, 1);
  assert.ok(ctrl.backupError);
});

test("WorkspaceDataController explicit retry works after error", async () => {
  let calls = 0;
  const api = new AlexApi();
  api.getBackups = async () => { calls++; throw new Error("fail"); };
  const ctrl = new WorkspaceDataController(api, () => {});
  
  ctrl.loadBackups();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(calls, 1);
  ctrl.loadBackups(true);
  await new Promise(r => setTimeout(r, 0));
  assert.equal(calls, 2);
});

test("WorkspaceDataController duplicate createBackup is blocked", async () => {
  let createCalls = 0;
  const api = new AlexApi();
  api.createBackup = async () => { createCalls++; return {}; };
  const ctrl = new WorkspaceDataController(api, () => {});
  
  const p1 = ctrl.createBackup();
  const p2 = ctrl.createBackup(); // Should be blocked
  
  const [res1, res2] = await Promise.all([p1, p2]);
  assert.equal(createCalls, 1);
  assert.equal(res1, true);
  assert.equal(res2, false);
});

test("WorkspaceDataController successful backup reloads truth", async () => {
  let loadCalls = 0;
  const api = new AlexApi();
  api.createBackup = async () => { return {}; };
  api.getBackups = async () => { loadCalls++; return { items: [] }; };
  const ctrl = new WorkspaceDataController(api, () => {});
  
  await ctrl.createBackup();
  assert.equal(loadCalls, 1); // Auto reloaded after create
});

test("WorkspaceDataController failed backup visible, cached data survives, UI notified", async () => {
  const api = new AlexApi();
  api.createBackup = async () => { throw new Error("fail"); };
  let notifies = 0;
  const ctrl = new WorkspaceDataController(api, () => { notifies++; });
  ctrl.backupPayload = { items: [], retention: 7, directory: "bk" }; // Cached
  
  const res = await ctrl.createBackup();
  assert.equal(res, false);
  assert.equal(ctrl.backupError, "Loi khi tao backup.");
  assert.ok(ctrl.backupPayload); // Survived
  assert.equal(ctrl.backupCreateInFlight, false); // Restored
  assert.equal(notifies, 2); // 1 for start, 1 for finally
});

// 3. UI Rendering Tests
test("renderBackup Loading state", () => {
  const html = renderBackup({ payload: null, loading: true, error: null, createInFlight: false });
  assert.match(html, /Đang tải/);
});

test("renderBackup Empty/Unknown state", () => {
  const html = renderBackup({ payload: null, loading: false, error: null, createInFlight: false });
  assert.match(html, /Chưa có dữ liệu/);
});

test("renderBackup real latest backup, history, integrity truth", () => {
  const state = {
    payload: {
      items: [
        { file: "f1.db", metadata_file: "f1.json", size_bytes: 10240, sha256: "hash1", integrity: "ok", created_at: "2026-07-23T10:00:00Z" },
        { file: "f2.db", metadata_file: "f2.json", size_bytes: 5120, sha256: "hash2", integrity: "metadata_missing" }
      ],
      retention: 7,
      directory: "backups_dir"
    },
    loading: false, error: null, createInFlight: false
  };
  const html = renderBackup(state);
  
  // Latest
  assert.match(html, /10 KB/);
  assert.match(html, /2026-07-23T10:00:00Z/);
  assert.match(html, /status-emerald">OK/); // Integrity ok is green
  
  // History
  assert.match(html, /metadata_missing/i);
  assert.match(html, /status-critical.*METADATA_MISSING/); // Integrity failed is red
  assert.match(html, /backups_dir/);
  assert.match(html, /7 bản/);
});

test("renderBackup failure state and cached data survives", () => {
  const state = {
    payload: { items: [], retention: 7, directory: "bk" },
    loading: false, error: "Tạo backup thất bại.", createInFlight: false
  };
  const html = renderBackup(state);
  
  // Inline error
  assert.match(html, /Tạo backup thất bại\./);
  assert.match(html, /THỬ LẠI/);
  
  // Content still visible
  assert.match(html, /bk/);
});

test("renderBackup XSS escaping", () => {
  const state = {
    payload: {
      items: [{ file: "<script>", metadata_file: "", size_bytes: 0, sha256: "", integrity: "<img src=x onerror=alert(1)>", source_database: "<bad>" }],
      retention: 1, directory: "dir"
    },
    loading: false, error: "Error <script>", createInFlight: false
  };
  const html = renderBackup(state);
  
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<bad>/);
  assert.match(html, /&lt;bad&gt;/);
  assert.doesNotMatch(html, /<img/);
});

test("renderBackup no fake restore control", () => {
  const state = {
    payload: { items: [{ file: "f1", metadata_file: "m1", size_bytes: 1, sha256: "1", integrity: "ok" }], retention: 1, directory: "1" },
    loading: false, error: null, createInFlight: false
  };
  const html = renderBackup(state);
  
  // Ensure we did not invent a restore button
  assert.doesNotMatch(html, /RESTORE/i);
  assert.doesNotMatch(html, /KHÔI PHỤC/i);
});
