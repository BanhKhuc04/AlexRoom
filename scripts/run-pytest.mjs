import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const isWindows = os.platform() === "win32";

const venvPython = path.join(
  ".venv",
  isWindows ? "Scripts" : "bin",
  isWindows ? "python.exe" : "python"
);

const python = fs.existsSync(venvPython)
  ? venvPython
  : isWindows
    ? "python"
    : "python3";

try {
  execFileSync(python, ["-m", "pytest", "-q", "tests/"], {
    stdio: "inherit",
  });
} catch {
  process.exit(1);
}