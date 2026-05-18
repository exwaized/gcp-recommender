"""
run_pipeline.py — one-command end-to-end execution
Usage: python run_pipeline.py
Equivalent to GCP Cloud Composer DAG / Vertex AI Pipeline
"""
import subprocess
import sys
import os
import time
import requests

BASE = os.path.dirname(os.path.abspath(__file__))

def step(msg):
    print(f"\n{'='*55}")
    print(f"  {msg}")
    print('='*55)

def run(cmd, cwd=BASE):
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        print(f"FAILED: {cmd}")
        sys.exit(1)

def wait_for_api(url="http://localhost:8080/health", timeout=15):
    for _ in range(timeout):
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return True
        except:
            pass
        time.sleep(1)
    return False

if __name__ == "__main__":
    step("Step 1/3 — Generating synthetic dataset (BigQuery-equivalent)")
    run(f"python {BASE}/data/generate_data.py")

    step("Step 2/3 — Training ALS model + registering to MLflow (Vertex AI-equivalent)")
    run(f"python {BASE}/models/train.py")

    step("Step 3/3 — Starting FastAPI server (Cloud Run-equivalent)")
    print("  Server starting at http://localhost:8080")
    print("  Dashboard: open dashboard/Dashboard.jsx in claude.ai")
    print("  API docs:  http://localhost:8080/docs")
    print("\n  Press Ctrl+C to stop\n")
    
    server = subprocess.Popen(
        f"python -m uvicorn api.main:app --host 0.0.0.0 --port 8080",
        shell=True, cwd=BASE
    )
    
    if wait_for_api():
        print("\n  API is live! Testing endpoints...")
        import json
        r = requests.post("http://localhost:8080/recommend",
                          json={"user_id": "U0001", "n": 3},
                          headers={"Content-Type": "application/json"})
        print(f"\n  Sample recs for U0001:")
        for rec in r.json().get("recommendations", []):
            print(f"    [{rec['score']:.3f}] {rec['title']}")
    
    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()
        print("\n  Server stopped.")
