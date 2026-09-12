"""BLIND generalization test — LEGO, a company used in NO other fixture.
Facts pulled from real web sources (lego.com / Wikipedia / history.com), then an
AI-written-style paragraph seeded with errors. Expectations were decided by
reading the corpus, NOT by running the tool (pre-registered)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.cli import run  # noqa: E402

# (substring of claim, expected verdict, note)
EXPECT = [
    ("1932", "supported", "corpus: founded/began 1932 (lego.com + wikipedia)"),
    ("1929", "contradicted", "REAL ERROR: named 1934 (wiki) / official 1936"),
    ("DKK 3,000", "supported", "corpus states DKK 3,000 verbatim"),
    ("150 employees", "unverified", "corpus has 26/40 for the 1942 fire, not the 1924 rebuild"),
    ("Quality is not a destination", "unverified", "fabricated quote, absent from corpus"),
    ("shocking message", "supported", "verbatim in lego.com"),
    ("1951", "contradicted", "REAL ERROR: machine bought 1946/1947"),
    ("1958", "supported", "patented 1958 (wiki + lego.com)"),
]


def main():
    findings, meta = run(ROOT / "tests" / "case_lego_blind.md",
                         ROOT / "tests" / "corpus_lego",
                         ROOT / "reports" / "blind", fx_rates={})
    def blob(f):
        return f["sentence"] + " " + f["raw"]

    fails = []
    for needle, want, why in EXPECT:
        match = next((f for f in findings if needle in blob(f) and f["verdict"] == want), None)
        # for year claims the "raw" is just the number; match on sentence too
        if not match:
            seen = [f["verdict"] for f in findings if needle in blob(f)]
            status = "FAIL"
            fails.append(needle)
        else:
            status = "PASS"
            seen = [match["verdict"]]
        print(f"  [{status}] {needle:28} want={want:12} got={seen}  ({why})")
    flagged = [f for f in findings if f["verdict"] in
               {"contradicted", "internal_conflict", "misattributed", "paraphrase_flag", "needs_fix"}]
    print(f"\n  claims extracted: {len([f for f in findings if f.get('para') is not None])}"
          f" | flags: {len(flagged)}")
    print("BLIND/LEGO:", "PASS" if not fails else f"FAIL {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
