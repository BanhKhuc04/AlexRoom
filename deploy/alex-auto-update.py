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
STATE_FILE = "/var/lib/alex/ota_state.json"
LKG_FILE = "/var/lib/alex/last_known_good.json"
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
    return result.stdout.strip(), result.returncode

def run_cmd_str(cmd, cwd=REPO_DIR, check=True):
    out, rc = run_cmd(cmd, cwd=cwd, check=check)
    return out

def is_tree_dirty():
    status = run_cmd_str(["git", "status", "--porcelain", "-uno"])
    return bool(status)

def read_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to read {path}: {e}")
        return default if default is not None else {}

def write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Atomic write
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        logging.error(f"Failed to write {path}: {e}")

def get_state():
    return read_json(STATE_FILE, {"state": "idle", "failed_candidates": {}})

def set_state(state_dict):
    write_json(STATE_FILE, state_dict)

def get_lkg():
    return read_json(LKG_FILE, {})

def set_lkg(lkg_dict):
    write_json(LKG_FILE, lkg_dict)

def mark_lkg(commit):
    lkg = get_lkg()
    lkg["commit"] = commit
    version, _ = run_cmd(["git", "show", f"{commit}:VERSION"], check=False)
    lkg["version"] = version.strip() if version else "unknown"
    lkg["verified_at"] = get_utc_now()
    lkg["health"] = "healthy"
    set_lkg(lkg)

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
            commits = run_cmd_str(["git", "log", f"{old_commit}..{new_commit}", "--oneline"])
            log_entry["changes"] = commits.splitlines()
            
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
    run_cmd_str(["systemctl", "restart", SERVICE_NAME], cwd="/", check=True)

def parse_semver(v):
    try:
        parts = [int(x) for x in v.strip().split("-")[0].split(".")]
        return parts + [0] * (3 - len(parts))
    except Exception:
        return [0,0,0]

def validate_candidate(commit, old_commit):
    # Check VERSION exists and parseable
    version_content, rc = run_cmd(["git", "show", f"{commit}:VERSION"], check=False)
    if rc != 0 or not version_content:
        return False, "Missing VERSION file in candidate"
    
    cand_version = version_content.strip()
    old_version_content, rc2 = run_cmd(["git", "show", f"{old_commit}:VERSION"], check=False)
    old_version = old_version_content.strip() if rc2 == 0 else "0.0.0"

    if parse_semver(cand_version) < parse_semver(old_version):
        return False, f"Candidate version {cand_version} is older than {old_version}"

    # Check app.py exists
    app_content, rc = run_cmd(["git", "ls-tree", "-r", commit, "app.py"], check=False)
    if rc != 0 or not app_content:
        return False, "Missing app.py in candidate tree"
        
    # Check disk space
    usage = shutil.disk_usage(REPO_DIR)
    free_mb = usage.free / (1024 * 1024)
    if free_mb < 50:
        return False, "Insufficient disk space for update"

    return True, "Valid"

def rollback(old_commit, new_commit, reason, state):
    logging.info(f"Rolling back to {old_commit}...")
    state["state"] = "rolling_back"
    set_state(state)
    
    try:
        run_cmd_str(["git", "reset", "--hard", old_commit])
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            run_cmd_str(["chown", "-R", "vanhkhuc:vanhkhuc", REPO_DIR], cwd="/")
        restart_service()
        
        if check_health(timeout=30):
            logging.info("UPDATE_FAILED_ROLLED_BACK")
            record_history(old_commit, new_commit, "UPDATE_FAILED_ROLLED_BACK", reason)
            state["state"] = "idle"
            state.setdefault("failed_candidates", {})[new_commit] = {"reason": reason, "timestamp": get_utc_now()}
            set_state(state)
        else:
            logging.error("CRITICAL_ROLLBACK_FAILURE: Health check failed even after rollback.")
            record_history(old_commit, new_commit, "CRITICAL_ROLLBACK_FAILURE", reason)
            state["state"] = "idle"
            state.setdefault("failed_candidates", {})[new_commit] = {"reason": reason + " AND rollback failed", "timestamp": get_utc_now()}
            set_state(state)
    except Exception as e:
        logging.error(f"CRITICAL_ROLLBACK_FAILURE: Exception during rollback: {e}")
        record_history(old_commit, new_commit, "CRITICAL_ROLLBACK_FAILURE", str(e))
        state["state"] = "idle"
        state.setdefault("failed_candidates", {})[new_commit] = {"reason": str(e), "timestamp": get_utc_now()}
        set_state(state)

def recover_interrupted_state(state, old_commit, new_commit):
    current_status = state.get("state")
    if current_status in ("idle", "staging"):
        return
        
    logging.info(f"Recovering interrupted state: {current_status}")
    
    if current_status == "verifying":
        # We were verifying. Let's check health.
        if check_health(timeout=10):
            logging.info("ALEX AUTO UPDATE SUCCESS (Recovered)")
            mark_lkg(new_commit)
            record_history(old_commit, new_commit, "ALEX AUTO UPDATE SUCCESS")
            state["state"] = "idle"
            set_state(state)
            sys.exit(0)
        else:
            logging.error("Health check failed on recovery. Initiating rollback...")
            rollback(old_commit, new_commit, "Health check failed after recovery", state)
            sys.exit(1)
            
    elif current_status == "activating":
        # We were in the middle of activating, maybe files are inconsistent
        rollback(old_commit, new_commit, "Interrupted during activation", state)
        sys.exit(1)
        
    elif current_status == "rolling_back":
        # We were rolling back
        rollback(old_commit, new_commit, "Interrupted during rollback", state)
        sys.exit(1)

def run_update():
    old_commit = run_cmd_str(["git", "rev-parse", "HEAD"])
    
    state = get_state()
    # Explicitly recover if interrupted
    if state.get("state") != "idle":
        recover_interrupted_state(state, state.get("old_commit", old_commit), state.get("candidate", old_commit))
    
    logging.info("Fetching origin main...")
    out, rc = run_cmd(["git", "fetch", "origin", "main"], check=False)
    if rc != 0:
        logging.error("No network / GitHub unreachable (fetch failed). Update fails safely.")
        sys.exit(1)
        
    new_commit = run_cmd_str(["git", "rev-parse", "origin/main"])
    
    if old_commit == new_commit:
        logging.info("NO_UPDATE. Already at the latest commit.")
        sys.exit(0)
        
    logging.info(f"Update candidate available: {old_commit} -> {new_commit}")
    
    # Check if this candidate previously failed
    if new_commit in state.get("failed_candidates", {}):
        logging.warning(f"Candidate {new_commit} previously failed. Skipping to avoid infinite rollback loops.")
        sys.exit(0)
        
    if is_tree_dirty():
        logging.error("ABORT UPDATE. Local tracked modifications found.")
        sys.exit(1)
        
    merge_base = run_cmd_str(["git", "merge-base", "HEAD", "origin/main"])
    if merge_base != old_commit:
        logging.error("ABORT UPDATE. Divergent history. Fast-forward not possible.")
        sys.exit(1)
        
    changed_files = run_cmd_str(["git", "diff", "--name-only", "HEAD", "origin/main"]).splitlines()
    if "requirements-orangepi.txt" in changed_files:
        logging.error("DEPENDENCY_UPDATE_REQUIRES_MANUAL_DEPLOYMENT")
        sys.exit(1)

    # Static Validation (Pre-Activation)
    state["state"] = "staging"
    state["candidate"] = new_commit
    state["old_commit"] = old_commit
    set_state(state)
    
    is_valid, validation_msg = validate_candidate(new_commit, old_commit)
    if not is_valid:
        logging.error(f"Candidate validation failed: {validation_msg}")
        state["state"] = "idle"
        state["failed_candidates"][new_commit] = {"reason": validation_msg, "timestamp": get_utc_now()}
        set_state(state)
        sys.exit(1)

    # Pre-flight health check
    if not check_health(timeout=5):
        logging.error("Core is unhealthy before update. Do not start OTA.")
        state["state"] = "idle"
        set_state(state)
        sys.exit(1)

    # Activation
    logging.info("Activating candidate (fast-forward)...")
    state["state"] = "activating"
    set_state(state)
    
    out, rc = run_cmd(["git", "merge", "--ff-only", "origin/main"], check=False)
    if rc != 0:
        logging.error("Merge failed during activation.")
        rollback(old_commit, new_commit, "Merge failed", state)
        sys.exit(1)
    
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        run_cmd_str(["chown", "-R", "vanhkhuc:vanhkhuc", REPO_DIR], cwd="/")
        
    try:
        restart_service()
    except Exception as e:
        logging.error(f"Failed to restart service: {e}")
        rollback(old_commit, new_commit, "Service restart failed", state)
        sys.exit(1)
        
    # Health Verification
    logging.info("Waiting for health check...")
    state["state"] = "verifying"
    set_state(state)
    
    if check_health(timeout=30):
        logging.info("ALEX AUTO UPDATE SUCCESS")
        mark_lkg(new_commit)
        record_history(old_commit, new_commit, "ALEX AUTO UPDATE SUCCESS")
        state["state"] = "idle"
        set_state(state)
        sys.exit(0)
    else:
        logging.error("Health check failed. Initiating rollback...")
        rollback(old_commit, new_commit, "Health check failed", state)
        sys.exit(1)

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
        run_update()

if __name__ == "__main__":
    main()
