import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Legacy Phase 2 fallback is removed and replaced by executeBrainChat", async () => {
  const source = await readFile(new URL("../static/ui/presence-commands.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /Intent này chưa được nối trong Phase 2/);
  assert.match(source, /executeBrainChat/);
});
