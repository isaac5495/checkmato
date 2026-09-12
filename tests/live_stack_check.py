"""Live-stack check: uvicorn(8000) + next dev(3000) + page + /api rewrite -> engine.
Run: python tests/live_stack_check.py   (self-cleaning; prints PASS/FAIL lines)"""
import subprocess
import sys
import time
from pathlib import Path

import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")


def get(url, timeout=120, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def wait(url, tries=40, sleep=2):
    for _ in range(tries):
        try:
            return get(url)
        except Exception:
            time.sleep(sleep)
    raise RuntimeError(f"never up: {url}")


def main():
    api = subprocess.Popen([PY, "-X", "utf8", "-m", "uvicorn", "app.server:app",
                            "--port", "8000"], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen(["npm.cmd", "run", "dev"], cwd=ROOT / "web",
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fails = []
    try:
        st, h = wait("http://127.0.0.1:8000/api/health")
        ok = '"ok":true' in h.replace(" ", "")
        print(("  [PASS]" if ok else "  [FAIL]"), "backend /api/health (8000)")
        fails += [] if ok else ["health"]

        st, page = wait("http://localhost:3000", tries=50)
        ok = st == 200 and "Check" in page
        print(("  [PASS]" if ok else "  [FAIL]"), f"frontend page (3000) status {st}")
        fails += [] if ok else ["page"]

        body = ("text="
                "Apple was founded by Steve Jobs in 1974. The company reports "
                "15,000 employees across six offices. That 12,000-person group "
                "shipped the remake in 1998."
                "&web=false&llm=false").encode()
        st, sse = get("http://localhost:3000/api/check", timeout=120, data=body,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        checks = sse.count('"stage": "check"') + sse.count('"stage":"check"')
        done = "event: done" in sse
        ok = st == 200 and done and checks >= 4
        print(("  [PASS]" if ok else "  [FAIL]"),
              f"rewrite 3000->8000 ran engine (SSE {checks} claim checks, done={done})")
        fails += [] if ok else ["rewrite+engine"]
    finally:
        for p in (api, web):
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True)
            except Exception:
                pass
    print("LIVE STACK:", "PASS" if not fails else f"FAIL {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
