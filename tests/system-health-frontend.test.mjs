import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


test(
  "aggregated health is fetched as non fatal snapshot data",
  async () => {
    const source = await readFile(
      new URL(
        "../static/core/api.js",
        import.meta.url,
      ),
      "utf8",
    );

    assert.match(
      source,
      /\/api\/system\/health/,
    );

    assert.match(
      source,
      /systemHealth/,
    );

    assert.match(
      source,
      /catch\(\(\)\s*=>\s*null\)/,
    );
  },
);


test(
  "system workspace shows production health",
  async () => {
    const source = await readFile(
      new URL(
        "../static/ui/workspaces.js",
        import.meta.url,
      ),
      "utf8",
    );

    for (const marker of [
      "SYSTEM HEALTH",
      "systemHealth",
      "hardware_runtime",
      "update_timer",
      "backup_count",
      "ALEX VERSION",
      "DATABASE",
      "MQTT",
      "ESP01",
    ]) {
      assert.ok(
        source.includes(marker),
        `missing ${marker}`,
      );
    }
  },
);
