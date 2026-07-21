import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("shell exposes keyboard, reduced-motion and accessible navigation contracts", async () => {
  const [html, base, app] = await Promise.all([
    readFile(new URL("../static/index.html", import.meta.url), "utf8"),
    readFile(new URL("../static/styles/base.css", import.meta.url), "utf8"),
    readFile(new URL("../static/app.js", import.meta.url), "utf8"),
  ]);
  assert.match(html, /href="#primaryContent"/);
  assert.match(html, /aria-label="Không gian làm việc"/);
  assert.match(html, /aria-label="Tình trạng hệ thống"/);
  assert.match(base, /:focus-visible/);
  assert.match(base, /prefers-reduced-motion/);
  assert.match(app, /document\.hidden/);
  assert.match(app, /event\.ctrlKey/);
});
