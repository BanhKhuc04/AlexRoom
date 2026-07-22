import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { renderLogs } from "../static/ui/workspaces.js";
import { AlexApi } from "../static/core/api.js";

test("getAudit actual requested URL and limit normalization", async () => {
  let requestedUrl = "";
  globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
  const api = new AlexApi();
  api.request = async (url) => { requestedUrl = url; return { items: [], source: "sqlite" }; };

  await api.getAudit();
  assert.equal(requestedUrl, "/api/v1/audit?limit=80");

  await api.getAudit(0);
  assert.equal(requestedUrl, "/api/v1/audit?limit=1");

  await api.getAudit(-1);
  assert.equal(requestedUrl, "/api/v1/audit?limit=1");

  await api.getAudit(80);
  assert.equal(requestedUrl, "/api/v1/audit?limit=80");

  await api.getAudit(201);
  assert.equal(requestedUrl, "/api/v1/audit?limit=200");

  await api.getAudit(NaN);
  assert.equal(requestedUrl, "/api/v1/audit?limit=80");

  await api.getAudit("invalid string");
  assert.equal(requestedUrl, "/api/v1/audit?limit=80");
});

test("renderLogs outputs honest empty state", () => {
  const html = renderLogs({ payload: { items: [], source: "sqlite" }, loading: false, error: null });
  assert.match(html, /Chưa có sự kiện từ backend\./);
  assert.doesNotMatch(html, /Đang tải dữ liệu/);
});

test("renderLogs actual output and XSS escaping", () => {
  const html = renderLogs({
    loading: false,
    error: null,
    payload: {
      source: "sqlite",
      items: [{
        created_at: "2026-07-23T00:00:00Z",
        kind: "<script>alert(1)</script>",
        level: "error",
        message: "<img src=x onerror=alert(2)>",
        source: "<evil>",
        details: null,
      }],
    }
  });

  assert.match(html, /\[&lt;evil&gt;\]/);
  assert.match(html, /&lt;SCRIPT&gt;ALERT\(1\)&lt;\/SCRIPT&gt;/);
  assert.match(html, /&lt;img src=x onerror=alert\(2\)&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("renderLogs outputs loading state", () => {
  const html = renderLogs({ loading: true, error: null, payload: null });
  assert.match(html, /Đang tải dữ liệu/);
});

test("renderLogs outputs error state", () => {
  const html = renderLogs({ loading: false, error: "<script>alert('err')</script>", payload: null });
  assert.match(html, /&lt;script&gt;alert\(&#039;err&#039;\)&lt;\/script&gt;/);
  assert.match(html, /THỬ LẠI/);
});

test("cached audit refetch behavior (source analysis)", async () => {
  const appSource = await readFile(new URL("../static/app.js", import.meta.url), "utf8");
  assert.match(appSource, /if \(!force && \(auditPayload \|\| auditError\)\) return;/);
  assert.match(appSource, /if \(auditLoading\) return;/);
  assert.match(appSource, /onRefresh:\s*\(\)\s*=>\s*loadAudit\(true\)/);
});
