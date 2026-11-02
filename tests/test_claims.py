"""W2.5 gate: atomic spans, pronoun resolution, aliases, evidence expansion."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.byos import apply_byos
    from app.corpus import Corpus
    from app.glossary import same_entity
    from app.normalize import query_text, resolve_pronoun, split_compound

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"CLAIM FAIL: {msg}"
        n += 1

    sent = ("Atlas Systems opened its Aurora plant in 2011, and it hired "
            "200 engineers in 2012.")
    parts = split_compound(sent)
    ok(len(parts) == 2, f"compound sentence splits into two ({parts})")
    ok(all(sent[a:b].strip() == p for p, a, b in parts),
       "atomic spans still point at the original sentence")

    resolved = resolve_pronoun("It opened a plant in 2011.", "Atlas Systems")
    ok(resolved.startswith("Atlas Systems"),
       "leading pronoun resolves to the paragraph subject")

    q = query_text("Acme Software reported revenue in 2019.",
                   "Acme", [["Acme", "Acme Software"]])
    ok("Acme Software" in q and "Acme" in q,
       "query carries both short and full alias forms")

    ok(same_entity("Acme", "Acme Software", cooccur=True),
       "short/full forms are the same entity")
    ok(not same_entity("Acme", "Acme Cloud", cooccur=True),
       "cloud subsidiary is a different entity")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "facts.md").write_text(
            "Atlas Systems opened the Aurora plant in 2011.\n\n"
            "The plant employed 1,200 people in 2012.\n", encoding="utf-8")
        corpus = Corpus(root)
        ps = corpus.find_bm25_passages("Aurora plant 2011", top=2)
        ok(ps and "Aurora" in ps[0]["text"],
           "BM25 finds the passage with the fact")
        expanded = corpus.expand_passages(ps[:1], radius=1)
        ok(len(expanded) >= 1,
           "evidence expansion returns a neighbour window")

        from app.extract import extract_claims
        from app.judge import judge
        pc = extract_claims(["It opened the Aurora plant in 2011."])
        pron = next(c for c in pc if c["type"] == "year")
        pron["_query"] = resolve_pronoun(pron["sentence"], "Atlas Systems")
        judge([pron], corpus)
        ok(pron["verdict"] == "supported",
           "a pronoun claim is retrievable after subject resolution")

    claim = {"id": "x", "type": "year", "raw": "1999",
             "sentence": "Nimbus Labs opened a plant in 1999.",
             "para": 0, "verdict": "unverified", "confidence": "low",
             "evidence": [], "suggestion": ""}
    lib = _tiny_library()
    apply_byos([claim], lib, "sources_only")
    ok(claim["verdict"] == "no_source",
       "after retrieval retry, an absent numeric claim is no_source")

    print(f"CLAIM NORMALISATION: PASS ({n} assertions)")
    return 0


def _tiny_library():
    from app.library import Library
    td = tempfile.mkdtemp()
    root = Path(td)
    (root / "facts.md").write_text("Atlas Systems opened a plant in 2011.\n",
                                   encoding="utf-8")
    return Library(root)


if __name__ == "__main__":
    sys.exit(main())
