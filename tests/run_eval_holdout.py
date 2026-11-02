"""Independent hold-out evaluation (different entities and adversarial cases)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    import tempfile

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    from eval_en_holdout import suite
    from app.byos import apply_byos
    from app.extract import extract_claims
    from app.judge import judge
    from app.library import Library

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
                c = {"id": f"h{i}", "type": "event", "raw": sentence[:60],
                     "sentence": sentence, "para": i * 10,
                     "span": [0, len(sentence)], "verdict": "unverified",
                     "confidence": "low", "evidence": []}
            else:
                found = extract_claims([sentence])
                c = next((x for x in found if x["type"] == case["type"]), None)
                if c is None:
                    print(f"CLAIM EXTRACTION MISS: {sentence}")
                    return 1
                c["id"] = f"h{i}"
                c["para"] = i * 10
            claims.append(c)
            cases.append(case)

        judge(claims, lib.corpus)
        apply_byos(claims, lib, "sources_only")

        true_cases = [c for c in cases if c["expected"] == "supported"]
        absent = [c for c in cases if c["expected"] == "not_supported"]
        prose = [c for c in cases if c["expected"] == "not_checked"]
        false_all = [c for c in cases if c["expected"] != "supported"
                     and c["expected"] != "not_checked"]

        supported_true = sum(1 for c, case in zip(claims, cases)
                             if case["expected"] == "supported"
                             and c["verdict"] == "supported")
        supported_total = sum(1 for c in claims if c["verdict"] == "supported")
        false_supported = sum(1 for c, case in zip(claims, cases)
                              if case["expected"] in ("not_supported",
                                                      "contradicted")
                              and c["verdict"] == "supported")
        false_contra = sum(1 for c, case in zip(claims, cases)
                           if case["expected"] == "not_supported"
                           and c["verdict"] == "contradicted")
        not_checked = sum(1 for c, case in zip(claims, cases)
                          if case["expected"] == "not_checked"
                          and c["verdict"] == "unverified"
                          and "Prose claim" in (c.get("suggestion") or ""))
        internal = sum(1 for c in claims if c["verdict"] == "internal_conflict")

        m = len(true_cases)
        rate = 100.0 * supported_true / m if m else 0.0
        fs = 100.0 * false_supported / supported_total if supported_total else 0.0
        fc = 100.0 * false_contra / len(absent) if absent else 0.0

        print(f"HOLDOUT: {m} true, {len(false_all)} false, {len(prose)} prose")
        print(f"HOLDOUT SUPPORT RATE: {rate:.1f}% ({supported_true}/{m})")
        print(f"HOLDOUT FALSE SUPPORT: {fs:.1f}% "
              f"({false_supported}/{supported_total})")
        print(f"HOLDOUT NOT CHECKED: {not_checked}")
        print(f"HOLDOUT FALSE CONTRADICTION: {fc:.1f}% "
              f"({false_contra}/{len(absent)})")
        print(f"HOLDOUT INTERNAL CONFLICTS: {internal}")

        for c, case in zip(claims, cases):
            if case["expected"] in ("not_supported", "contradicted") \
                    and c["verdict"] == "supported":
                print(f"  FALSE SUPPORT CASE: {case['sentence']}")
                for ev in c.get("evidence") or []:
                    print(f"    evidence: {ev.get('ref')} | "
                          f"{(ev.get('quote') or '')[:100]}")

        return 0 if (rate >= 90.0 and fs == 0.0 and fc == 0.0
                     and internal < 5) else 1


if __name__ == "__main__":
    sys.exit(main())
