"""
Orchestrator: seed test DB, start uvicorn with ENVIRONMENT=test, run pytest, cleanup.
Runs everything in the same Python process tree to guarantee ENVIRONMENT inheritance.
"""
import requests
import os
import sys
import subprocess
import time

# Force test environment BEFORE any app import
os.environ["ENVIRONMENT"] = "test"

# 1. Seed
print("[SEED] Seeding test DB...")
ret = subprocess.call([sys.executable, "run_setup_test_db.py"])
if ret != 0:
    sys.exit(ret)

# 2. Start uvicorn with ENVIRONMENT explicitly in env
print("[START] Starting uvicorn with ENVIRONMENT=test...")
uvicorn_env = os.environ.copy()
uvicorn_env["ENVIRONMENT"] = "test"
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", "8000"],
    env=uvicorn_env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

# 3. Wait for health
print("[WAIT] Waiting for API...")
for i in range(30):
    time.sleep(1)
    try:
        r = requests.get("http://localhost:8000/health", timeout=2)
        if r.status_code == 200:
            print("[READY] API is up!")
            break
    except Exception:
        pass
else:
    print("[FATAL] API did not start within 30s")
    proc.kill()
    sys.exit(1)

# 4. Run pytest
print("[PYTEST] Running tests...")
test_ret = subprocess.call([sys.executable, "-m", "pytest", "tests/", "-v"])

# 5. Cleanup
print("[STOP] Shutting down...")
proc.kill()

sys.exit(test_ret)
