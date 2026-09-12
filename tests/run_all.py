"""Run every CheckMato gate. Exit 0 = ship-able state."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
TESTS = ["test_units.py", "run_eval.py", "test_web_guard.py", "test_diff.py",
         "test_robustness.py", "test_webapp.py", "test_single_server.py"]


def main():
    failed = []
    r = subprocess.run([PY, "-m", "ruff", "check", "app", "tests"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if "No module named ruff" in r.stderr:
        print("[FAIL] lint(ruff)           ruff missing: pip install -r requirements.txt")
        failed.append("lint(ruff)")
    else:
        out = r.stdout.strip().splitlines() or [""]
        print(f"[{'PASS' if r.returncode == 0 else 'FAIL'}] {'lint(ruff)':20} {out[-1][:90]}")
        if r.returncode:
            failed.append("lint(ruff)")
            print(r.stdout[-800:])
    for t in TESTS:
        r = subprocess.run([PY, "-X", "utf8", str(ROOT / "tests" / t)],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        last = [ln for ln in r.stdout.splitlines() if ln.strip()][-1:] or [""]
        print(f"[{'PASS' if r.returncode == 0 else 'FAIL'}] {t:20} {last[0][:90]}")
        if r.returncode:
            failed.append(t)
            print(r.stdout[-600:], r.stderr[-400:])
    print("\nALL GATES:", "PASS" if not failed else f"FAIL {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
