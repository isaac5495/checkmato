"""Venue/instance guard: a figure on a DIFFERENT instance is not a contradiction.

"Orion Labs opened its Bergen plant in 2011" vs "…its Oslo plant in 2012" is a
different venue; "Orion Labs" vs "Orion Cloud" is a different entity. Both used
to reach the contradiction path because the subject name and the milestone
matched. Synthetic fixtures only.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _judge(sentence, sources, entities):
    from app.extract import extract_claims
    from app.judge import judge
    from app.library import Library

    with tempfile.TemporaryDirectory() as td:
        lib = Path(td) / "lib"
        lib.mkdir()
        for i, text in enumerate(sources):
            (lib / f"s{i}.md").write_text(text + "\n", encoding="utf-8")
        corpus = Library(lib).corpus
        claims = extract_claims([sentence])
        for c in claims:
            c["_doc_entities"] = list(entities)
        judge(claims, corpus)
        return [c["verdict"] for c in claims]


def main():
    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"VENUE GUARD FAIL: {msg}"
        n += 1

    # 1. Same company, same milestone, DIFFERENT venue: not a contradiction.
    v = _judge(
        "Orion Labs opened its Bergen plant in 2011.",
        ["Orion Labs opened its Oslo plant in 2012."],
        ["Orion Labs"])
    ok("contradicted" not in v, f"different venue must not contradict ({v})")
    ok("unverified" in v, f"the claim stays honestly unresolved ({v})")

    # 2. Same milestone, DIFFERENT entity: not a contradiction.
    v = _judge(
        "Orion Labs reported revenue of US$90 million in 2021.",
        ["Orion Cloud reported revenue of US$70 million in 2021."],
        ["Orion Labs", "Orion Cloud"])
    ok("contradicted" not in v, f"different entity must not contradict ({v})")

    # 3. Control: same venue, different year is still a contradiction.
    v = _judge(
        "Orion Labs opened its Bergen plant in 2011.",
        ["Orion Labs opened its Bergen plant in 2012."],
        ["Orion Labs"])
    ok("contradicted" in v, f"same venue + different year contradicts ({v})")

    # 4. Control: same entity, different amount is still a contradiction.
    v = _judge(
        "Orion Labs reported revenue of US$90 million in 2021.",
        ["Orion Labs reported revenue of US$70 million in 2021."],
        ["Orion Labs"])
    ok("contradicted" in v, f"same entity + different amount contradicts ({v})")

    # 5. An attribution the claim lacks is not a different instance.
    v = _judge(
        "Orion Labs opened its Bergen plant in 2011.",
        ["According to Reuters, Orion Labs opened its Bergen plant in 2012."],
        ["Orion Labs"])
    ok("contradicted" in v, f"one-sided attribution still contradicts ({v})")

    print(f"VENUE GUARD: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
