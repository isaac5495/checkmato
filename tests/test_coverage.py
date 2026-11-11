"""W6 coverage split: `unverified` is not one state.

A claim we never checked is not a negative finding. Pin the buckets so the
report and the UI cannot collapse "checked, not found" back into "not checked".
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.report import coverage_counts

    findings = [
        {"verdict": "supported"},
        {"verdict": "unverified", "_searched": True},
        {"verdict": "unverified", "_searched": False},
        {"verdict": "unverified"},                 # no _searched key at all
        {"verdict": "unverified", "_mode": "sources_only"},
        {"verdict": "deferred_web"},
        {"verdict": "no_source"},
        {"verdict": "narrative"},
        {"verdict": "structure"},
        {"verdict": "contradicted"},
        {"verdict": "internal_conflict"},
        {"verdict": "needs_fix"},
        {"verdict": "paraphrase_flag"},
        {"verdict": "conflicting"},
    ]
    c = coverage_counts(findings)
    assert c["supported"] == 1
    assert c["checked_not_found"] == 2, c        # web-searched + BYOS mode
    assert c["not_checked"] == 3, c            # false + no key + deferred_web
    assert c["no_source"] == 1
    assert c["not_checkable"] == 1
    assert c["structure"] == 1
    assert c["needs_attention"] == 4, c        # contradicted/internal/needs_fix/paraphrase
    assert c["conflicting"] == 1
    assert sum(c.values()) == len(findings), (sum(c.values()), len(findings))
    print("COVERAGE TESTS: PASS (9 assertions)")


if __name__ == "__main__":
    main()
