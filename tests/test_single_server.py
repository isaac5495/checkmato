"""Single-process gate: uvicorn serves UI + API + exports on one port.

The old two-process flow (uvicorn + next dev on 3000) died with
ERR_CONNECTION_REFUSED whenever either window closed; this mode needs only:
    .venv\\Scripts\\python.exe -m uvicorn app.server:app --port 8000
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
PORT = 8777  # avoids clashing with a dev server already on 8000
BASE = f"http://127.0.0.1:{PORT}"


def main():
    out_dir = ROOT / "web" / "out"
    if not out_dir.exists():
        print("SKIP: web/out missing — run `npm run build` in web/ first")
        return 1
    # Point the child server at a THROWAWAY quota store. Without this the gate
    # reads the developer's real .quota.json and starts failing with HTTP 429
    # purely because the app was exercised 25 times that day -- a test that
    # depends on how much the dev used the tool is not a gate, it is a
    # tripwire. The quota logic itself is covered hermetically in test_units.
    quota_store = Path(tempfile.gettempdir()) / f"checkmato_test_quota_{os.getpid()}.json"
    env = dict(os.environ, CHECKMATO_QUOTA_PATH=str(quota_store))
    proc = subprocess.Popen([PY, "-X", "utf8", "-m", "uvicorn", "app.server:app",
                             "--port", str(PORT), "--host", "127.0.0.1"],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=2)
                break
            except Exception:
                time.sleep(1)
        checks = []
        html = urllib.request.urlopen(BASE + "/", timeout=10).read().decode()
        checks.append(("UI at :%d" % PORT, "Check" in html and "<script" in html))
        body = urllib.parse.urlencode({
            "text": "Nimbus was founded in 2008. The team has 1,200 people.",
            "web": "false", "llm": "false"}).encode()
        req = urllib.request.Request(BASE + "/api/check", data=body,
                                     headers={"Content-Type":
                                              "application/x-www-form-urlencoded"})
        sse = urllib.request.urlopen(req, timeout=60).read().decode()
        job = None
        for b in sse.split("\n\n"):
            if "event: done" in b:
                job = json.loads([ln for ln in b.splitlines()
                                  if ln.startswith("data:")][0][6:])["job_id"]
        checks.append(("check via UI port", bool(job)))
        raw = urllib.request.urlopen(f"{BASE}/api/export/{job}/jsonl",
                                     timeout=10).read()
        recs = [json.loads(x) for x in raw.decode().splitlines()]
        checks.append((f"export ({len(recs)} records)",
                       len(recs) >= 2 and all("claim_id" in r for r in recs)))
        rep = json.loads(urllib.request.urlopen(f"{BASE}/api/report/{job}",
                                                timeout=10).read())
        checks.append(("paragraphs for highlight view",
                       bool(rep["meta"].get("paragraphs"))))
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
        quota_store.unlink(missing_ok=True)
    ok = all(v for _, v in checks)
    for name, v in checks:
        print(f"  [{'PASS' if v else 'FAIL'}] {name}")
    print("SINGLE-SERVER:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
