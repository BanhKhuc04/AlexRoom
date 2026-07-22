import { execSync } from 'child_process';
import os from 'os';
import path from 'path';

const isWindows = os.platform() === 'win32';
const venvPath = path.join('.venv', isWindows ? 'Scripts' : 'bin', isWindows ? 'python.exe' : 'python');

try {
  execSync(venvPath + " -m pytest -q tests/", { stdio: "inherit" });
} catch {
  process.exit(1);
}
