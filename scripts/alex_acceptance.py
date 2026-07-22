#!/usr/bin/env python3
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

def print_result(name, ok, details=""):
    status = "PASS" if ok else "FAIL"
    color = "\033[92m" if ok else "\033[91m"
    reset = "\033[0m"
    print(f"[{color}{status}{reset}] {name}")
    if details:
        print(f"       {details}")

def run_cmd(cmd):
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5, check=False)
    except Exception as e:
        return subprocess.CompletedProcess(args=cmd, returncode=-1, stdout="", stderr=str(e))

def check_systemd_active(service):
    res = run_cmd(["systemctl", "is-active", service])
    return res.stdout.strip() == "active"

def sqlite_integrity(db_path: Path) -> bool:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        res = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        return res is not None and res[0] == "ok"
    except Exception:
        return False

def sqlite_quick_check(db_path: Path) -> bool:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        res = conn.execute("PRAGMA quick_check").fetchone()
        conn.close()
        return res is not None and res[0] == "ok"
    except Exception:
        return False

def main():
    results = {}
    is_ready = True

    print("========================================")
    print("ALEX NEXUS OS - PRODUCTION ACCEPTANCE")
    print("========================================")

    def report(name, ok, detail):
        nonlocal is_ready
        results[name] = {"ok": ok, "detail": detail}
        print_result(name, ok, detail)
        if not ok:
            is_ready = False

    # 1. Version
    version_file = Path("/opt/alex/AlexRoom-0.2.0-hardware-rc/VERSION")
    if version_file.is_file():
        version = version_file.read_text().strip()
        report("Version", True, version)
    else:
        report("Version", False, "Missing VERSION file")

    # 2. Systemd Failed Units
    res = run_cmd(["systemctl", "--failed", "--no-legend", "--no-pager"])
    failed_lines = [line.strip() for line in res.stdout.splitlines() if line.strip() and not line.startswith("0 loaded")]
    if res.returncode == 0 and len(failed_lines) == 0:
        report("Systemd Failed Units", True, "No failed units")
    else:
        report("Systemd Failed Units", False, f"Failed units found: {failed_lines}")

    # 3. Core Service
    core_ok = check_systemd_active("alex-core.service")
    report("Core Service", core_ok, "Active" if core_ok else "Not active")

    # 4. Timers
    timers = ["alex-health.timer", "alex-backup.timer", "alex-update.timer", "alex-watchdog.timer"]
    timers_ok = True
    bad_timers = []
    for t in timers:
        if not check_systemd_active(t):
            timers_ok = False
            bad_timers.append(t)
    report("Systemd Timers", timers_ok, "All active" if timers_ok else f"Inactive: {bad_timers}")

    # 5. Database Integrity
    db_path = Path("/var/lib/alex/alex.db")
    if db_path.exists():
        if sqlite_integrity(db_path):
            report("Database Integrity", True, "PRAGMA integrity_check == ok")
        else:
            report("Database Integrity", False, "Integrity check failed")
    else:
        report("Database Integrity", False, "Database file not found")

    # 6. Aggregated Health API
    try:
        req = urllib.request.Request("http://127.0.0.1:8000/api/system/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                health_data = json.loads(resp.read().decode("utf-8"))
                
                # Verify available, not stale, overall healthy
                if not health_data.get("available", False):
                    report("Health API", False, "Health snapshot not available")
                elif health_data.get("stale", True):
                    report("Health API", False, "Health snapshot is stale")
                elif health_data.get("status") != "healthy":
                    report("Health API", False, f"Overall status: {health_data.get('status')}")
                else:
                    # check actual health check fields
                    checks = health_data.get("report", {}).get("checks", {})
                    issues = []
                    if checks.get("database", {}).get("status") != "healthy": issues.append("database")
                    if checks.get("core_service", {}).get("status") != "healthy": issues.append("core_service")
                    if checks.get("backup", {}).get("status") != "healthy": issues.append("backup")
                    if checks.get("update_timer", {}).get("status") != "healthy": issues.append("update_timer")
                    
                    hw = checks.get("hardware_runtime", {})
                    if hw.get("mqtt") != "connected": issues.append("mqtt not connected")
                    if hw.get("device") != "online": issues.append("device offline")
                    if "heartbeat_age_seconds" in hw and hw["heartbeat_age_seconds"] > 60: issues.append("stale heartbeat")
                    
                    if issues:
                        report("Health API", False, f"Subsystem issues: {issues}")
                    else:
                        report("Health API", True, "available=True, stale=False, status=healthy, subsystems OK")
            else:
                report("Health API", False, f"HTTP {resp.status}")
    except Exception as e:
        report("Health API", False, f"Request failed: {str(e)}")

    # 7. Backup Integrity
    backups_dir = Path("/var/lib/alex/backups")
    if backups_dir.exists():
        backups = list(backups_dir.glob("alex-*.db"))
        if backups:
            latest_backup = max(backups, key=lambda p: p.stat().st_mtime)
            age = time.time() - latest_backup.stat().st_mtime
            if age > 86400 * 2: # 48 hours to be safe
                report("Backup Integrity", False, f"Latest backup too old: {age/3600:.1f} hours")
            else:
                if sqlite_quick_check(latest_backup) and sqlite_integrity(latest_backup):
                    report("Backup Integrity", True, "Latest backup recent and valid")
                else:
                    report("Backup Integrity", False, "Latest backup quick_check/integrity_check failed")
        else:
            report("Backup Integrity", False, "No backups found")
    else:
        report("Backup Integrity", False, "Backup directory not found")

    # 8. Recovery Readiness
    base_dir = Path("/opt/alex/AlexRoom-0.2.0-hardware-rc")
    req_files = [base_dir / "alex_restore.py", base_dir / "scripts/restore_backup.py", base_dir / "scripts/restore_production.py"]
    missing = [f.name for f in req_files if not f.exists()]
    if missing:
        report("Recovery Readiness", False, f"Missing files: {missing}")
    else:
        report("Recovery Readiness", True, "Recovery CLI modules present")

    # 9. OTA Readiness
    ota_state_path = Path("/var/lib/alex/ota_state.json")
    if not ota_state_path.exists():
        report("OTA Readiness", True, "OTA state missing (idle assumed)")
    else:
        try:
            with open(ota_state_path, "r") as f:
                json.load(f)
            report("OTA Readiness", True, "OTA state readable")
        except Exception as e:
            report("OTA Readiness", False, f"OTA state corrupt: {e}")

    # 10. Rollback Readiness
    lkg_path = Path("/var/lib/alex/last_known_good.json")
    if lkg_path.exists():
        try:
            with open(lkg_path, "r") as f:
                lkg = json.load(f)
            if "commit" in lkg:
                report("Rollback Readiness", True, f"LKG valid: {lkg['commit'][:7]}")
            else:
                report("Rollback Readiness", False, "LKG missing commit")
        except Exception as e:
            report("Rollback Readiness", False, f"LKG corrupt: {e}")
    else:
        report("Rollback Readiness", False, "LKG missing (required for automatic rollback)")

    # 11. Security
    env_file = Path("/etc/alex/alex.env")
    if env_file.exists():
        st = env_file.stat()
        mode = st.st_mode & 0o777
        if mode in (0o600, 0o400):
            uid = st.st_uid
            # Try to resolve uid to name, but it might fail on windows test env, so check if it matches current user or 0 (root)
            if uid == 0 or uid == os.getuid() if hasattr(os, "getuid") else True:
                report("Security", True, f"Permissions {oct(mode)} are secure")
            else:
                report("Security", False, f"File owner mismatch (uid={uid})")
        else:
            report("Security", False, f"Insecure permissions {oct(mode)}")
    else:
        report("Security", False, "Missing /etc/alex/alex.env")

    print("========================================")
    print("SUMMARY")
    print("========================================")
    if is_ready:
        print("\033[92mPRODUCTION READY\033[0m")
    else:
        print("\033[91mNOT READY\033[0m - Some critical checks failed")
        
    out_file = Path("/opt/alex/AlexRoom-0.2.0-hardware-rc/acceptance.json")
    out_data = json.dumps({"ready": is_ready, "components": results}, indent=2)
    try:
        out_file.write_text(out_data)
        print(f"Written to {out_file}")
    except Exception as e:
        print(f"FAILED TO WRITE OUTPUT JSON: {e}")
        # DO NOT SWALLOW SILENTLY
        sys.exit(2)

    sys.exit(0 if is_ready else 1)

if __name__ == "__main__":
    main()
