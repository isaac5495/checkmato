"""Manual W1.4 gold-set evaluator (network; not part of run_all.py).

Reads a reviewed gold JSON (id/claim/label/note from reports/w1-gold-*.json),
runs the semantic judge against a BYOS library, and reports per-label recall /
false-support. The labels file is private and gitignored; this script contains
no case literals.

    .venv\\Scripts\\python.exe -X utf8 tests\\run_nli_gold.py \\
        --labels reports\\w1-gold-50-reviewed.json \\
        --library C:\\path\\to\\library [--provider deepseek|agnes|auto]

Labels: supported / partial -> true; not_supported -> false; narrative ->
skipped by eligibility (unless --include-narrative); unclear -> excluded.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_claims(labels, include_narrative=False):
    claims = []
    for row in labels:
        lab = row.get("label") or "unclear"
        verdict = "narrative" if (lab == "narrative" and not include_narrative) \
            else "unverified"
        claims.append({
            "id": row["id"], "type": "event", "verdict": verdict,
            "raw": row["claim"], "sentence": row["claim"],
            "sentence_context": row["claim"], "context_sentence": row["claim"],
            "origin": "sentence", "evidence": [], "confidence": "low",
            "suggestion": "", "_gold": lab, "_note": row.get("note") or "",
        })
    return claims


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="reports/w1-gold-50-reviewed.json")
    ap.add_argument("--library", required=True)
    ap.add_argument("--provider", default="auto",
                    choices=("auto", "deepseek", "agnes"))
    ap.add_argument("--include-narrative", action="store_true",
                    help="do not pre-mark narrative labels; tests false support")
    ap.add_argument("--semantic-retrieval", action="store_true",
                    help="enable the optional W2 embedding lane")
    ap.add_argument("--out", default="reports/w1-gold-50-eval.json")
    a = ap.parse_args()

    from app import nli
    from app.corpus import Corpus
    from app.llm import LLM

    if a.semantic_retrieval:
        os.environ["CHECKMATO_SEMANTIC"] = "1"

    labels = json.loads(Path(a.labels).read_text(encoding="utf-8"))["labels"]
    claims = build_claims(labels, include_narrative=a.include_narrative)
    corpus = Corpus(a.library)
    llm = LLM(max_calls=24, max_tokens=80000, max_seconds=300)
    if a.provider == "deepseek":
        llm.key_agnes_relay = None
        llm.key_agnes = None
        llm.key_groq = None
        llm.key_openai = None
        llm.key_gemini = None
    elif a.provider == "agnes":
        llm.key_deepseek = None
        llm.key_groq = None
        llm.key_openai = None
        llm.key_gemini = None
    if not llm.available:
        print("no LLM key for provider", a.provider)
        return 2

    nli.judge(llm, claims, corpus=corpus, max_claims=len(claims), batch=8)
    counts, rows = {}, []
    for c in claims:
        g = c["_gold"]
        counts.setdefault(g, [0, 0])
        counts[g][1] += 1
        if c["verdict"] == "supported":
            counts[g][0] += 1
        ev = (c.get("evidence") or [{}])[0]
        rows.append({"id": c["id"], "gold": g, "verdict": c["verdict"],
                     "claim": c["raw"], "note": c["_note"],
                     "ref": ev.get("ref", ""),
                     "quote": (ev.get("quote") or "")[:120]})
        print(f"{c['id']} {g:13s} -> {c['verdict']:10s} | {c['raw'][:60]}")

    print("\nBY GOLD:")
    for k, (hit, total) in sorted(counts.items()):
        print(f"  {k:13s} {hit}/{total} supported")
    print("llm calls", llm.calls, "tokens", llm.tokens,
          "provider", llm.provider or "(none)")
    out = {"labels": a.labels, "library": a.library,
           "provider": llm.provider, "llm_calls": llm.calls,
           "tokens": llm.tokens, "counts": counts, "rows": rows}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
