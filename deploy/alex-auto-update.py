#!/usr/bin/env python3
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

# Constants
REPO_DIR = "/opt/alex/AlexRoom-0.2.0-hardware-rc"
LOCK_FILE = "/var/lock/alex-auto-update.lock"
HISTORY_FILE = "/var/lib/alex/update-history.jsonl"
HEALTH_URL = "http://127.0.0.1:8000/health"
SERVICE_NAME = "alex-core.service"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def get_utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def run_cmd(cmd, cwd=REPO_DIR, check=True):
    result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        logging.error(f"Command failed: {' '.join(cmd)}")
        logging.error(result.stderr)
        result.check_returncode()
    return result.stdout.strip()

def is_tree_dirty():
    # Only checks tracked files. Untracked files (??) are ignored.
    status = run_cmd(["git", "status", "--porcelain", "-uno"])
    return bool(status)

def record_history(old_commit, new_commit, result, message=""):
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        log_entry = {
            "timestamp": get_utc_now(),
            "previous_commit": old_commit,
            "current_commit": new_commit,
            "result": result
        }
        if message:
            log_entry["message"] = message
            
        if old_commit and new_commit and old_commit != new_commit:
            commits = run_cmd(["git", "log", f"{old_commit}..{new_commit}", "--oneline"]).splitlines()
            log_entry["changes"] = commits
            
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        logging.error(f"Failed to write history: {e}")

def check_health(timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(HEALTH_URL)
            with urllib.request.urlopen(req, timeout=5) as res:
                if res.status == 200:
                    data = json.loads(res.read().decode("utf-8"))
                    if data.get("api") == "online" and data.get("mqtt") == "connected":
                        return True
        except Exception:
            pass
        time.sleep(2)
    return False

def restart_service():
    logging.info(f"Restarting {SERVICE_NAME}...")
    run_cmd(["systemctl", "restart", SERVICE_NAME], cwd="/", check=True)

def main():
    if not os.path.exists(REPO_DIR):
        logging.error(f"Repository directory {REPO_DIR} does not exist.")
        sys.exit(1)

    try:
        import fcntl
        with open(LOCK_FILE, "w") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                logging.info("Another update process is running. Exiting.")
                sys.exit(0)
                
            run_update()
    except ImportError:
        # Fallback for systems without fcntl (e.g., Windows during testing)
        run_update()

def run_update():
    logging.info("Fetching origin main...")
    run_cmd(["git", "fetch", "origin", "main"])
    
    old_commit = run_cmd(["git", "rev-parse", "HEAD"])
    new_commit = run_cmd(["git", "rev-parse", "origin/main"])
    
    if old_commit == new_commit:
        logging.info("NO_UPDATE. Already at the latest commit.")
        sys.exit(0)
        
    logging.info(f"Update available: {old_commit} -> {new_commit}")
    
    if is_tree_dirty():
        logging.error("ABORT UPDATE. Local tracked modifications found.")
        sys.exit(1)
        
    merge_base = run_cmd(["git", "merge-base", "HEAD", "origin/main"])
    if merge_base != old_commit:
        logging.error("ABORT UPDATE. Divergent history. Fast-forward not possible.")
        sys.exit(1)
        
    changed_files = run_cmd(["git", "diff", "--name-only", "HEAD", "origin/main"]).splitlines()
    if "requirements-orangepi.txt" in changed_files:
        logging.error("DEPENDENCY_UPDATE_REQUIRES_MANUAL_DEPLOYMENT")
        sys.exit(1)
        
    logging.info("Updating source tree (fast-forward)...")
    run_cmd(["git", "merge", "--ff-only", "origin/main"])
    
    # Preserve ownership for vanhkhuc if we are running as root
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        run_cmd(["chown", "-R", "vanhkhuc:vanhkhuc", REPO_DIR], cwd="/")
        
    try:
        restart_service()
    except Exception as e:
        logging.error(f"Failed to restart service: {e}")
        rollback(old_commit, new_commit, "Service restart failed")
        sys.exit(1)
        
    logging.info("Waiting for health check...")
    if check_health(timeout=30):
        logging.info("ALEX AUTO UPDATE SUCCESS")
        record_history(old_commit, new_commit, "ALEX AUTO UPDATE SUCCESS")
        sys.exit(0)
    else:
        logging.error("Health check failed. Initiating rollback...")
        rollback(old_commit, new_commit, "Health check failed")
        sys.exit(1)

def rollback(old_commit, new_commit, reason):
    logging.info(f"Rolling back to {old_commit}...")
    try:
        run_cmd(["git", "reset", "--hard", old_commit])
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            run_cmd(["chown", "-R", "vanhkhuc:vanhkhuc", REPO_DIR], cwd="/")
        restart_service()
        
        if check_health(timeout=30):
            logging.info("UPDATE_FAILED_ROLLED_BACK")
            record_history(old_commit, new_commit, "UPDATE_FAILED_ROLLED_BACK", reason)
        else:
            logging.error("CRITICAL_ROLLBACK_FAILURE: Health check failed even after rollback.")
            record_history(old_commit, new_commit, "CRITICAL_ROLLBACK_FAILURE", reason)
    except Exception as e:
        logging.error(f"CRITICAL_ROLLBACK_FAILURE: Exception during rollback: {e}")
        record_history(old_commit, new_commit, "CRITICAL_ROLLBACK_FAILURE", str(e))

if __name__ == "__main__":
    main()
