"""English BYOS evaluation: support rate, false support, not-checked.

Runs the deterministic judge over the committed synthetic suite and reports the
metrics the improvement plan uses. Prose is excluded from the support
denominator and must be reported as not-checked.

Usage:
  .venv\\Scripts\\python.exe -X utf8 tests\\run_eval_en.py --suite tests\\eval_en
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    import argparse
    import tempfile

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    from eval_en import suite
    from app.byos import apply_byos
    from app.extract import extract_claims
    from app.judge import judge
    from app.library import Library

    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default=str(ROOT / "tests" / "eval_en"))
    a = ap.parse_args(argv or sys.argv[1:])
    suite_dir = Path(a.suite)
    if not suite_dir.exists():
        print(f"SUITE MISSING: {suite_dir}")
        return 1

    with tempfile.TemporaryDirectory() as td:
        libdir = Path(td) / "library"
        libdir.mkdir()
        for name, text in suite.SOURCES.items():
            (libdir / name).write_text(text, encoding="utf-8")
        lib = Library(libdir)

        claims, cases = [], []
        for i, case in enumerate(suite.CASES):
            sentence = case["sentence"]
            if case["type"] == "prose":
                c = {"id": f"e{i}", "type": "event", "raw": sentence[:60],
                     "sentence": sentence, "para": i * 10,
                     "span": [0, len(sentence)], "verdict": "unverified",
                     "confidence": "low", "evidence": []}
            else:
                found = extract_claims([sentence])
                c = next((x for x in found if x["type"] == case["type"]), None)
                if c is None:
                    print(f"CLAIM EXTRACTION MISS: {sentence}")
                    return 1
                c["id"] = f"e{i}"
                c["para"] = i * 10
            claims.append(c)
            cases.append(case)

        judge(claims, lib.corpus)
        apply_byos(claims, lib, "sources_only")

        true_cases = [c for c in cases if c["expected"] == "supported"]
        false_cases = [c for c in cases
                       if c["expected"] in ("not_supported", "contradicted")]
        absent_cases = [c for c in cases if c["expected"] == "not_supported"]
        prose_cases = [c for c in cases if c["expected"] == "not_checked"]

        supported_true = sum(1 for c, case in zip(claims, cases)
                             if case["expected"] == "supported"
                             and c["verdict"] == "supported")
        supported_total = sum(1 for c in claims if c["verdict"] == "supported")
        false_supported = sum(1 for c, case in zip(claims, cases)
                              if case["expected"] != "supported"
                              and c["verdict"] == "supported")
        false_contradicted = sum(1 for c, case in zip(claims, cases)
                                 if case["expected"] == "not_supported"
                                 and c["verdict"] == "contradicted")
        not_checked = sum(1 for c, case in zip(claims, cases)
                          if case["expected"] == "not_checked"
                          and c["verdict"] == "unverified"
                          and "Prose claim" in (c.get("suggestion") or ""))
        internal = sum(1 for c in claims if c["verdict"] == "internal_conflict")

        m = len(true_cases)
        support_rate = 100.0 * supported_true / m if m else 0.0
        false_support = 100.0 * false_supported / supported_total \
            if supported_total else 0.0
        false_contra = 100.0 * false_contradicted / len(absent_cases) \
            if absent_cases else 0.0

        print(f"SUITE: {len(true_cases)} true, {len(false_cases)} false, "
              f"{len(prose_cases)} prose")
        print(f"SUPPORT RATE: {support_rate:.1f}% "
              f"({supported_true}/{m})")
        print(f"FALSE SUPPORT: {false_support:.1f}% "
              f"({false_supported}/{supported_total})")
        print(f"NOT CHECKED: {not_checked}")
        print(f"FALSE CONTRADICTION: {false_contra:.1f}% "
              f"({false_contradicted}/{len(absent_cases)})")
        print(f"INTERNAL CONFLICTS: {internal}")

        ok = (support_rate >= 90.0 and false_support == 0.0
              and false_contra == 0.0 and internal < 5 and m >= 40)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
