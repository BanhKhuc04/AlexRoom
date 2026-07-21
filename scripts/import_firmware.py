import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

def calculate_sha256(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def validate_semver(version: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))

def main():
    parser = argparse.ArgumentParser(description="ALEX Firmware Import Tool")
    parser.add_argument("--node-type", required=True, help="Type of node (e.g., esp01)")
    parser.add_argument("--version", required=True, help="Semantic version (e.g., 1.0.1)")
    parser.add_argument("--file", required=True, type=Path, help="Path to firmware binary")
    args = parser.parse_args()

    if not validate_semver(args.version):
        print(f"Error: Invalid semantic version format: {args.version}")
        sys.exit(1)

    if not args.file.is_file():
        print(f"Error: Firmware file not found: {args.file}")
        sys.exit(1)

    base_dir = Path(__file__).resolve().parent.parent
    default_firmware_dir = base_dir / "data" / "firmware"
    firmware_dir = Path(os.getenv("ALEX_FIRMWARE_DIR", str(default_firmware_dir)))

    node_dir = firmware_dir / args.node_type
    version_dir = node_dir / args.version
    manifest_path = node_dir / "manifest.json"
    target_bin = version_dir / "firmware.bin"

    if target_bin.exists():
        print(f"Error: Release {args.version} already exists for {args.node_type}.")
        print("To overwrite, remove the existing directory manually.")
        sys.exit(1)

    # Prepare directories
    version_dir.mkdir(parents=True, exist_ok=True)

    # Process file
    size = args.file.stat().st_size
    if size == 0:
        print("Error: Firmware file is empty.")
        sys.exit(1)

    sha256 = calculate_sha256(args.file)

    # Copy binary
    print(f"Copying {args.file} to {target_bin}...")
    shutil.copy2(args.file, target_bin)
    
    # Read or initialize manifest
    manifest = {}
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            print(f"Warning: Could not read existing manifest: {e}")
            manifest = {}

    if "releases" not in manifest:
        manifest["releases"] = {}

    manifest["releases"][args.version] = {
        "nodeType": args.node_type,
        "version": args.version,
        "filename": "firmware.bin",
        "size": size,
        "sha256": sha256,
        "releasedAt": datetime.now(timezone.utc).isoformat(),
        "minimumCompatibleProtocol": 1
    }

    # Atomically write manifest
    temp_manifest = manifest_path.with_suffix(".tmp")
    with open(temp_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    temp_manifest.replace(manifest_path)

    print(f"Success! Imported {args.node_type} firmware {args.version}.")
    print(f"SHA-256: {sha256}")
    print(f"Size: {size} bytes")

if __name__ == "__main__":
    main()
