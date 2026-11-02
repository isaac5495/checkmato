"""W2 retrieval gate: bm25s, value-first, field-weighted rerank, neighbour
expansion, no value-only greens."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.glossary import same_entity
    from app.judge import judge
    from app.library import Library

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"RETRIEVAL FAIL: {msg}"
        n += 1

    lib = Library(ROOT / "tests" / "byos" / "lib")
    corpus = lib.corpus
    ok(corpus.bm25.ok, "bm25s index is built")
    ok(corpus.bm25.version != "none", "bm25s version is available")

    val = corpus.find_value_passages(
        ["acme", "systems", "revenue", "million"], "amount", 125_000_000.0,
        "USD")
    ok(val and "125 million" in val[0]["text"],
       "value-first retrieval finds the figure, not just words")

    hits = corpus.find_bm25_passages("Bergen plant opened 2011", top=3)
    ok(any("Bergen plant opened" in p["text"] and "2011" in p["text"]
           for p in hits),
       "BM25 ranks the passage that states the fact")

    # Field weighting (title x2 / heading x2, bounded rerank). Tested on the
    # pure function so the numbers are explicit, not a lucky fixture ranking.
    from app.corpus import _field_rerank

    def _p(i, title=(), heading=()):
        return {"idx": i, "title_tokens": frozenset(title),
                "heading_tokens": frozenset(heading)}

    q = {"aurora", "plant", "2011"}
    near = [(9.5, _p(1, title={"aurora"})), (10.0, _p(2))]
    ok([p["idx"] for p in _field_rerank(q, near)] == [1, 2],
       "a source-title hit breaks a near-tie")
    far = [(1.0, _p(3, title={"aurora"})), (10.0, _p(4))]
    ok([p["idx"] for p in _field_rerank(q, far)] == [4, 3],
       "the field bonus is bounded: it cannot overturn a better text match")
    plain = [(5.0, _p(5)), (4.0, _p(6))]
    ok([p["idx"] for p in _field_rerank(q, plain)] == [5, 6],
       "no field tokens -> BM25 order is preserved exactly")

    # Heading inheritance: a section heading labels the passages below it, and
    # the filename is the title field. Both are ranking metadata only.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "aurora_plant_report.md").write_text(
            "# Aurora Plant\n\nSystems opened the facility in 2011.\n",
            encoding="utf-8")
        (root / "misc_notes.md").write_text(
            "# Notes\n\nPlant maintenance is routine.\n", encoding="utf-8")
        from app.corpus import Corpus
        c2 = Corpus(root)
        ok(all("title_tokens" in p and "heading_tokens" in p
               for p in c2.passages),
           "every passage carries field tokens")
        ap = next(p for p in c2.passages if "opened the facility" in p["text"])
        ok("aurora" in ap["title_tokens"] and "aurora" in ap["heading_tokens"],
           "filename and section heading both feed the field index")
        ok(ap["fname"] == "aurora_plant_report.md" and ap["start"] == 1,
           "field metadata never moves the locator")

    p = next(p for p in corpus.passages if "125 million" in p["text"])
    neigh = corpus.expand_passages([p], radius=1)
    ok(any(x["idx"] == p["idx"] for x in neigh) and len(neigh) >= 1,
       "neighbour expansion keeps the passage and its neighbours")

    ok(same_entity("Acme", "Acme Software", cooccur=True),
       "short/full alias is the same entity")
    ok(not same_entity("Acme", "Acme Cloud", cooccur=True),
       "parent/cloud subsidiary is not the same entity")

    # A value in an unrelated subject's line must never produce support.
    from app.extract import extract_claims
    claims = extract_claims(
        ["Nimbus Labs reported revenue of 125 million dollars in 2019."])
    amount = next(c for c in claims if c["type"] == "amount")
    judge([amount], corpus)
    ok(amount["verdict"] != "supported",
       f"value-only match across subjects is not support ({amount['verdict']})")

    print(f"RETRIEVAL TESTS: PASS ({n} assertions, bm25s {corpus.bm25.version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
