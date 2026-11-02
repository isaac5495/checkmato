"""No case answers in the engine.

A general tool becomes a demo one "if company == X" at a time. This gate fails
when a fixture answer (a name, a figure) appears in app/, and when case names
appear in the BYOS modules. Existing comments elsewhere are out of scope: they
illustrate a failure mode, they do not decide one.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

FIXTURE_ANSWERS = ["Acme", "Harbor Ledger", "125 million", "華光", "陳艾莉"]
CASE_NAMES = ["Kingsoft", "金山", "求伯君", "WPS", "西山居", "Lei Jun"]
BYOS_MODULES = {"library.py", "byos.py", "glossary.py"}


def main():
    hits = []
    for p in sorted(APP.glob("*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for term in FIXTURE_ANSWERS:
            if term in text:
                hits.append(f"{p.name}: fixture answer {term!r}")
        if p.name in BYOS_MODULES:
            for term in CASE_NAMES:
                if term in text:
                    hits.append(f"{p.name}: case name {term!r}")
    if hits:
        print("NO-CASE-LITERALS: FAIL")
        for h in hits:
            print("  " + h)
        return 1
    print("NO-CASE-LITERALS: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
