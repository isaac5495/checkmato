"""Free-tier policy: 40 web searches is a CAP, never a floor.

The planner sizes budgets to the document (`max_search` was historically a
floor). The hosted guest tier needs the opposite: BYOS is unlimited, web is
capped at 40 per document, and claims reached after the cap must stay
"not checked" — never "checked, not found".
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app import estimate
    from app.report import coverage_counts

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"FREE TIER FAIL: {msg}"
        n += 1

    stats = {"doc": "x.md", "words": 1000, "paras": 10, "claims": 100,
             "need_web": 100, "uniq_need_web": 100}
    cfg = {"max_search": 60, "max_pages": 16, "deep_max_claims": 16,
           "llm_max_calls": 30, "llm_max_tokens": 60000}

    full = estimate.scaled_budgets(stats, cfg, web=True, llm=True)
    capped = estimate.scaled_budgets(stats, cfg, web=True, llm=True,
                                     search_cap=40)
    ok(full["max_search"] > 40, f"full plan is larger than the cap ({full['max_search']})")
    ok(capped["max_search"] == 40, f"cap is a hard cap ({capped['max_search']})")
    ok(capped["web_max_seconds"] > 0, "time ceiling is recomputed after the cap")
    ok(capped["max_pages"] == full["max_pages"], "cap must not shrink page reads")
    ok(capped["llm_max_calls"] == full["llm_max_calls"], "cap must not shrink LLM calls")

    e = estimate.estimate(stats, cfg, web=True, llm=True, search_cap=40)
    ok(e["budgets"]["max_search"] == 40, "estimate uses the capped budget")
    ok(e["search_cap"] == 40, "estimate reports the cap")
    ok("Free-tier cap" in (e["recommend"] or ""), "estimate explains the cap")

    findings = [
        {"verdict": "unverified", "_mode": "sources_then_web",
         "_skip_reason": "web budget reached before this item"},
        {"verdict": "unverified", "_mode": "sources_then_web"},
        {"verdict": "unverified", "_mode": "web_only"},
    ]
    c = coverage_counts(findings)
    ok(c["not_checked"] == 2, f"budget-skips and web-only misses are not checked ({c})")
    ok(c["checked_not_found"] == 1, f"a BYOS-checked claim stays checked-not-found ({c})")
    ok(sum(c.values()) == 3, f"coverage buckets are exhaustive ({c})")

    print(f"FREE TIER TESTS: PASS ({n} assertions)")


if __name__ == "__main__":
    main()
