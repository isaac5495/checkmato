"""W1.1 prose-retrieval gate: rare-token + BM25 + exact-substring lanes.

Synthetic only (no private case material). Each fixture is designed so the
first 8 tokens are generic and the distinguishing word comes later — the
failure mode the old `tokens(sentence)[:8]` lead used.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.byos import apply_byos
    from app.corpus import Corpus
    from app.library import Library

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"PROSE RETRIEVAL FAIL: {msg}"
        n += 1

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "aurora_history.md").write_text(
            "# Aurora history\n\n"
            "The founder's chronic liver illness recurred three times.\n"
            "He moved his computer into the hospital room and kept coding.\n\n"
            "The canteen served four meals a day until midnight.\n"
            "The night-shift cook always added a fried egg.\n\n"
            "The annual meeting was held in the canteen.\n"
            "The founders wore chef coats and served the staff.\n",
            encoding="utf-8")
        (root / "unrelated_notes.md").write_text(
            "# Unrelated notes\n\n"
            "The company moved into a six-storey building in 1998.\n"
            "The canteen was renovated in 2019.\n",
            encoding="utf-8")

        corpus = Corpus(root)

        hits = corpus.find_prose_candidates(
            "His chronic liver illness came back three times.", top=3)
        ok(hits and "liver illness" in hits[0]["text"],
           f"rare keyword finds the right passage ({hits[0]['text'][:60] if hits else 'none'})")
        ok(all("six-storey" not in h["text"] for h in hits[:1]),
           "the decoy building passage does not outrank the fact")

        hits = corpus.find_prose_candidates(
            "The canteen served four meals a day.", top=3)
        ok(hits and "four meals" in hits[0]["text"],
           "a distinguishing phrase beats the generic 'canteen' line")
        ok(all("renovated" not in h["text"] for h in hits[:1]),
           "the renovated-canteen decoy is not the lead")

        hits = corpus.find_prose_candidates(
            "The founders wore chef coats at the annual meeting.", top=3)
        ok(hits and "chef coats" in hits[0]["text"],
           "a later rare phrase is found even when the opening is generic")

        hits = corpus.find_prose_candidates(
            "In 1998 the company moved into a six-storey building.", top=3)
        ok(hits and "six-storey" in hits[0]["text"],
           "a numeric/rare phrase in the tail is not lost to the first 8 tokens")

        lib = Library(root)
        claim = {
            "id": "p1", "type": "event", "raw": "chef coats",
            "sentence": "The founders wore chef coats at the annual meeting.",
            "verdict": "unverified", "confidence": "low",
            "evidence": [], "suggestion": "",
        }
        apply_byos([claim], lib, "sources_only")
        ok(claim["verdict"] == "unverified",
           "prose stays unverified (no deterministic checker)")
        ok("aurora_history.md" in claim["suggestion"],
           f"the lead points at the right source ({claim['suggestion'][:80]})")
        ok("Prose claim" in claim["suggestion"],
           "the suggestion still says this is a lead, not proof")

    print(f"PROSE RETRIEVAL TESTS: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
