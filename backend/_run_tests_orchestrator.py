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

# Set working directory to the backend folder (where this script lives)
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BACKEND_DIR)

# ── 0. Kill any existing process on port 8000 ──
print("[STOP] Killing any existing uvicorn on port 8000...")
try:
    # Windows: use netstat to find PID on port 8000, then kill it
    import re
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True, text=True, timeout=5
    )
    pids_on_8000 = set()
    for line in result.stdout.splitlines():
        if ":8000" in line and "LISTENING" in line:
            parts = line.strip().split()
            if parts:
                pid = parts[-1]
                if pid.isdigit():
                    pids_on_8000.add(pid)
    if pids_on_8000:
        for pid in pids_on_8000:
            subprocess.call(["taskkill", "/F", "/PID", pid],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"   Killed PID {pid} on port 8000")
        time.sleep(2)
    else:
        print("   Port 8000 is free")
except Exception as e:
    print(f"   Port kill check (non-fatal): {e}")

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
    stderr=None,
)

# 3. Wait for health
print("[WAIT] Waiting for API...")
for i in range(30):
    time.sleep(1)
    # Check if process died
    if proc.poll() is not None:
        stderr_out = proc.stderr.read().decode('utf-8', errors='replace')[:500]
        print(f"[FATAL] uvicorn died early: {stderr_out}")
        sys.exit(1)
    try:
        r = requests.get("http://localhost:8000/health", timeout=2)
        if r.status_code == 200:
            # Verify it's actually our test instance
            try:
                db_check = requests.get(
                    "http://localhost:8000/debug/db-url", timeout=2)
                if db_check.status_code == 200:
                    data = db_check.json()
                    if data.get("is_safe"):
                        print(
                            "[READY] API is up! (test env confirmed via /debug/db-url)")
                        break
                    else:
                        print(f"[FATAL] /debug/db-url says not safe: {data}")
                        proc.kill()
                        sys.exit(1)
                else:
                    print(
                        f"[FATAL] /debug/db-url returned {db_check.status_code}: {db_check.text[:200]}")
                    proc.kill()
                    sys.exit(1)
            except Exception as e:
                print(f"[FATAL] /debug/db-url failed: {e}")
                proc.kill()
                sys.exit(1)
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
