"""Run every CheckMato gate. Exit 0 = ship-able state."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
TESTS = ["test_units.py", "run_eval.py", "test_web_guard.py", "test_diff.py",
         "test_robustness.py", "test_webapp.py", "test_single_server.py",
         "test_subject_guard.py", "test_queries.py", "test_venue_guard.py",
         "test_compound.py", "test_prose_retrieval.py",
         "test_narrative_floor.py", "test_claim_units.py",
         "test_search_cache.py", "test_nli.py", "test_precision.py",
         "test_coverage.py", "test_free_tier.py"]

# The main gates are OFFLINE and must stay that way: a corpus verdict is
# documented as deterministic, and the Jev subject fallback is a network call
# that a developer's .env would otherwise switch on implicitly (proved by
# instrumenting run_eval: 0 calls today, but only because no fixture happens
# to trip it — that is luck, not a guarantee). The fallback has its own
# network-gated test; here it is switched off so "deterministic" stays true.
OFFLINE = {"JEV_SUBJECT_FALLBACK": "0",
           # a developer's .env now carries a DeepSeek key (llm.py loads .env);
           # an empty value makes _load_env_file skip it, so the gates stay
           # network-free and the "no key -> unusable" assertions stay meaningful
           "DEEPSEEK_API_KEY": ""}


def main():
    env = dict(os.environ, **OFFLINE)
    failed = []
    r = subprocess.run([PY, "-m", "ruff", "check", "app", "tests"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
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
                           encoding="utf-8", errors="replace", env=env)
        last = [ln for ln in r.stdout.splitlines() if ln.strip()][-1:] or [""]
        print(f"[{'PASS' if r.returncode == 0 else 'FAIL'}] {t:20} {last[0][:90]}")
        if r.returncode:
            failed.append(t)
            print(r.stdout[-600:], r.stderr[-400:])
    print("\nALL GATES:", "PASS" if not failed else f"FAIL {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
