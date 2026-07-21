import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Vietnamese test_led intent does not rely on ASCII word boundaries", async () => {
  const source = await readFile(new URL("../static/ui/presence-commands.js", import.meta.url), "utf8");
  assert.match(source, /\(bật\|tắt\).*đèn/);
  assert.doesNotMatch(source, /\\b\(bật\|tắt\).*đèn/);
});
