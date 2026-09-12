import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.cli import run  # noqa: E402
from app.judge import FLAG_VERDICTS  # noqa: E402

# ECB year-end reference rates (offline stubs; live runs fetch from frankfurter.app)
SUITES = [
    {"name": "EN", "doc": ROOT / "tests" / "case_ai_draft.md",
     "corpus": ROOT / "tests" / "corpus",
     "names": ROOT / "tests" / "en_names.csv",
     "fx": {("USD", "HKD", 2011): 7.7618, ("USD", "CNY", 2014): 6.1190}},
    {"name": "ZH", "doc": ROOT / "tests" / "case_zh.md",
     "corpus": ROOT / "tests" / "corpus_zh",
     "names": None,
     "fx": {("USD", "CNY", 2011): 6.3235}},
    {"name": "KS", "doc": ROOT / "tests" / "case_ks_en.md",
     "corpus": ROOT / "tests" / "corpus_ks",
     "names": ROOT / "tests" / "ks_names.csv",
     "fx": {}},
]


def ensure_pdf():
    p = SUITES[0]["corpus"] / "annual_report.pdf"
    if p.exists():
        return
    import pymupdf
    lines = ["Nimbus Cloud Annual Report (Excerpt)",
             "Nimbus Cloud opened its Singapore office in 2019.",
             "R&D spending reached US$45 million in 2020."]
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), lines[0], fontsize=14)
    for i, t in enumerate(lines[1:], 1):
        page.insert_text((72, 90 + i * 28), t, fontsize=11)
    doc.save(str(p))


def finding_blob(f):
    parts = [f.get("sentence", ""), f.get("raw", ""), f.get("note", ""),
             f.get("suggestion", "")]
    parts += [e["ref"] + " " + e["quote"] for e in f.get("evidence", [])]
    return " ".join(p for p in parts if p)


def check_suite(s):
    expected = json.loads((ROOT / "tests" / f"expected_{s['name']}.json")
                          .read_text(encoding="utf-8")) \
        if (ROOT / "tests" / f"expected_{s['name']}.json").exists() else \
        json.loads((ROOT / "tests" / "expected.json").read_text(encoding="utf-8"))
    out = ROOT / "reports" / "eval" / s["name"]
    findings, meta = run(s["doc"], s["corpus"], out, fx_rates=s["fx"],
                         names=s.get("names"))
    blobs = [(f, finding_blob(f)) for f in findings]

    hits, misses = 0, []
    for exp in expected:
        match = next((f for f, b in blobs
                      if f["verdict"] in exp["verdicts"]
                      and any(h in b for h in exp["hints"])), None)
        if match:
            hits += 1
            print(f"  [PASS] {exp['id']:22} {exp['verdicts'][0]:16} via {match['id']}")
        else:
            seen = ", ".join(f["verdict"] for f, b in blobs
                             if any(h in b for h in exp["hints"])) or "no match"
            misses.append(exp["id"])
            print(f"  [FAIL] {exp['id']:22} MISSED (seen: {seen})")
    recall = hits / len(expected)

    flagged = [(f, b) for f, b in blobs if f["verdict"] in FLAG_VERDICTS]

    def matched(f, b):
        return any(f["verdict"] in e["verdicts"] and any(h in b for h in e["hints"])
                   for e in expected)

    fps = [f for f, b in flagged if not matched(f, b)]
    for f in fps:
        print(f"  [FP]   {f['id']:22} {f['verdict']}: {f['raw'][:50]}")
    precision = 1 - len(fps) / len(flagged) if flagged else 1.0

    recs = [json.loads(x) for x in (out / "claims.jsonl").read_text(encoding="utf-8").splitlines()]
    required = {"claim_id", "source_span", "quote", "type", "verdict",
                "confidence", "evidence", "notes", "status"}
    contract_ok = all(required <= set(r) for r in recs)
    anchors_ok = meta["anchor_ok"] == meta["anchor_total"]
    print(f"  {s['name']}: recall {recall:.0%} precision {precision:.0%} "
          f"contract {'OK' if contract_ok else 'BROKEN'} "
          f"anchors {meta['anchor_ok']}/{meta['anchor_total']}"
          f" {'OK' if anchors_ok else 'BROKEN'}")
    return recall, precision, misses, fps, contract_ok, anchors_ok


def main():
    ensure_pdf()
    tot_r = tot_p = tot_n = 0
    all_ok = True
    for s in SUITES:
        print(f"\n== Suite {s['name']} ==")
        recall, precision, misses, fps, contract_ok, anchors_ok = check_suite(s)
        tot_r += recall * 100
        tot_p += precision * 100
        tot_n += 1
        all_ok = all_ok and recall >= 0.8 and precision >= 0.8 \
            and contract_ok and anchors_ok
    print(f"\nMEAN RECALL {tot_r / tot_n:.0f}%  MEAN PRECISION {tot_p / tot_n:.0f}%  "
          f"(gates: 80% / 80%; contract & anchors must be 100%)")
    print("EVAL GATE:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
