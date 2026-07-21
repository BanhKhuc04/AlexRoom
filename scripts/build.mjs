import { cp, mkdir, readFile, rm, stat } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const source = resolve(root, "static");
const destination = resolve(root, "dist", "static");
const distRoot = resolve(root, "dist");

if (!destination.startsWith(`${distRoot}\\`) && !destination.startsWith(`${distRoot}/`)) {
  throw new Error("Build destination escaped the repository dist directory.");
}

const requiredFiles = [
  "index.html",
  "styles.css",
  "app.js",
  "sw.js",
  "manifest.webmanifest",
  "core/alex-state.js",
  "core/audio-waveform.js",
  "core/core-renderer.js",
  "core/core-visuals.js",
  "core/frame-loop.js",
  "core/command-lifecycle.js",
  "core/quality.js",
  "core/realtime.js",
  "core/sound-engine.js",
  "ui/elements-phase2.js",
  "ui/presence-commands.js",
  "ui/presence-view.js",
];

for (const relativePath of requiredFiles) {
  const file = resolve(source, relativePath);
  const info = await stat(file);
  if (!info.isFile() || info.size === 0) {
    throw new Error(`Missing build asset: ${relativePath}`);
  }
}

const html = await readFile(resolve(source, "index.html"), "utf8");
for (const requiredId of ["presenceMode", "commandCenter", "alexCore", "commandNav"]) {
  if (!html.includes(`id="${requiredId}"`)) {
    throw new Error(`Missing shell element #${requiredId}`);
  }
}

await rm(distRoot, { recursive: true, force: true });
await mkdir(distRoot, { recursive: true });
await cp(source, destination, { recursive: true });

console.log(`Static build ready: ${destination}`);
