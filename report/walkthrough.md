# 🛠️ ALEX Auto-Update Walkthrough

This walkthrough details how the production-safe Git Auto-Update system was implemented for the Orange Pi environment.

## Changes Made

1. **`deploy/alex-auto-update.py`**:
   - Implemented a resilient fast-forward logic (`git merge --ff-only`).
   - Integrated dependency safeguards by rejecting updates automatically if `requirements-orangepi.txt` has changed.
   - Enforced checks for any tracked uncommitted modifications.
   - Designed an automated rollback sequence if the health verification fails to secure system availability.
   - Used robust file-locks to prevent overlapping cron runs.
   - Preserved `vanhkhuc` ownership securely even when executed with `root` privileges.

2. **`deploy/alex-update.service` & `deploy/alex-update.timer`**:
   - Created the systemd oneshot service that executes the auto-updater under root privileges safely.
   - Implemented a reliable `Persistent=true` timer mapped to a 2-minute cycle avoiding parallel overlapping processes.

3. **`tests/test_auto_update.py`**:
   - Developed comprehensive unit tests specifically mocking `git`, system calls, HTTP checks, and edge cases.

4. **`docs/DEPLOYMENT.md`**:
   - Appended a structured Section 11 indicating precise steps to install, trace, and temporarily disable this newly implemented Git auto-updater on production deployments without risking server misconfiguration.

## Validation Results

A rigorous test suite utilizing `npm run check:all` was executed successfully.

- **Backend tests:** Expanded to **49 test cases** (`Ran 49 tests in 4.587s OK`), successfully bringing the 10 mocked Git, network, OS integrity, and health-rollback test matrices to a full green build.
- **Secrets Management:** The tests confidently validated that GitHub credentials or MQTT passwords are not inappropriately leaked into the update history file (`/var/lib/alex/update-history.jsonl`).
- **OS Support:** Reconciled `os.geteuid` incompatibility explicitly on the development environment ensuring cross-compatibility and testing on Windows.

> [!TIP]
> The auto-update service is designed to be highly conservative. Any changes you make manually to tracked files directly on the Orange Pi, or updates containing new pip requirements, will intentionally freeze the automatic update to protect your environment and require you to perform a manual review.
