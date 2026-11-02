"""Hand-query gate: the strings a reader gets in an `unverified` row must be
pasteable — the sentence's facts, its own subject, its figure as written, the
verbatim quote — never entity[0] + two random words."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.corpus import Corpus
    from app.queries import hand_queries

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"QUERIES FAIL: {msg}"
        n += 1

    # 1. the subject named in THIS sentence, not the document's first entity
    ents = ["Kingsoft", "Cai Wu Wei Hotel"]
    c = {"type": "count", "raw": "120 rooms", "value": 120.0,
         "sentence": "The Cai Wu Wei Hotel has 120 rooms in Shenzhen."}
    qs = hand_queries(c, entities=ents)
    ok(qs and qs[0].startswith("Cai Wu Wei Hotel 120"),
       f"own subject leads: {qs}")

    # 2. a year claim carries its year, in the source's own script
    c = {"type": "year", "raw": "1984", "value": 1984.0,
         "sentence": "He graduated in 1984."}
    qs = hand_queries(c, entities=["Kingsoft"], native=lambda _c: ["求伯君"])
    ok(qs and qs[0] == "求伯君 1984", f"native entity·figure leads: {qs}")

    # 3. money keeps the written form a page actually carries
    c = {"type": "amount", "raw": "US$125 million", "value": 125_000_000.0,
         "sentence": "Acme Systems reported revenue of US$125 million in 2019."}
    qs = hand_queries(c, entities=["Acme Systems"])
    ok(qs and "US$125 million" in qs[0], f"written money form: {qs}")
    ok(not any("125000000" in q for q in qs), f"no bare numeric value: {qs}")

    # 4. report-voice words never become keywords
    c = {"type": "event", "raw": "opened a plant", "value": None,
         "sentence": "Acme announced it had additionally opened a plant in "
                     "Bergen in 2011."}
    qs = hand_queries(c, entities=["Acme"])
    blob = " ".join(qs).lower()
    ok("announced" not in blob and "additionally" not in blob,
       f"noise filtered: {qs}")

    # 5. a library still ranks rare terms into the kept set
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "plants.md").write_text(
            "\n".join(["The plant was busy."] * 8), encoding="utf-8")
        (root / "history.md").write_text("Bergen is a city.\n",
                                         encoding="utf-8")
        corpus = Corpus(root)
        c = {"type": "event", "raw": "plant", "value": None,
             "sentence": "The plant opened in Bergen last year."}
        qs = hand_queries(c, corpus=corpus, entities=["Acme"])
        ok(qs and "bergen" in qs[0].lower(), f"rare term kept: {qs}")

    # 6. a quote leads with the document's own script, then the verbatim span
    c = {"type": "quote", "raw": "Qiu Bojun's today is our tomorrow",
         "value": None,
         "sentence": 'His ad read: "Qiu Bojun\'s today is our tomorrow" '
                     "(求伯君的今天就是我们的明天)."}
    qs = hand_queries(c, entities=["Kingsoft"])
    ok(qs and qs[0] == '"求伯君的今天就是我们的明天"',
       f"doc's own script first: {qs}")
    ok(any('"Qiu Bojun' in q for q in qs), f"verbatim quote present: {qs}")

    # 7. never a lone token, never more than the cap, no duplicates
    for q in qs:
        ok(q.startswith('"') or len(q.split()) >= 2, f"multi-term query: {q}")
    ok(len(qs) <= 4, f"capped: {qs}")
    ok(len({q.lower() for q in qs}) == len(qs), f"deduped: {qs}")
    ok(hand_queries({"type": "event", "raw": "", "value": None,
                     "sentence": "It happened."}, entities=["Acme"]) == [],
       "a contentless sentence yields no fake query")

    # 8. deterministic, and the engine's own ladder is a fallback only
    c = {"type": "year", "raw": "2011", "value": 2011.0,
         "sentence": "Acme opened the Bergen plant in 2011."}
    a = hand_queries(c, entities=["Acme"])
    b = hand_queries(c, entities=["Acme"])
    ok(a == b and 1 <= len(a) <= 4, f"deterministic and capped: {a}")
    with_extra = hand_queries(c, entities=["Acme"], extra=["Acme 2011 plant"])
    ok(with_extra[0] in a, f"built query precedes the fallback: {with_extra}")

    # --- reader feedback (2026-11-02): the query must carry ALL the facts ---
    c = {"type": "event",
         "raw": "Zhang Xuanlong proposed funding Qiu Bojun to write a word "
                "processor",
         "sentence": "Zhang Xuanlong proposed funding Qiu Bojun to write a "
                     "word processor."}
    qs = hand_queries(c, entities=["求伯君"])
    blob = " ".join(qs).lower()
    ok("zhang xuanlong" in blob and "qiu bojun" in blob,
       f"both people named: {qs}")
    ok(all(w in blob for w in ("fund", "write", "word")),
       f"fund/write/word facts kept: {qs}")
    ok(len(qs[0].split()) >= 5, f"lead query is the whole fact: {qs[0]}")

    c = {"type": "event", "raw": "determined to displace WordStar",
         "sentence": "He was determined to displace WordStar."}
    qs = hand_queries(c, entities=["Kingsoft"], native=lambda _c: ["求伯君"])
    blob = " ".join(qs).lower()
    ok("determined" not in blob, f"evaluative verb dropped: {qs}")
    ok(qs[0] == "求伯君 displace WordStar",
       f"native subject + object + verb: {qs}")

    c = {"type": "count", "raw": "three times", "value": 3.0,
         "sentence": "His chronic liver disease flared up three times."}
    qs = hand_queries(c, entities=["Kingsoft"], native=lambda _c: ["求伯君"])
    blob = " ".join(qs).lower()
    ok(qs and all(w in blob for w in ("chronic", "liver", "disease")),
       f"medical facts present: {qs}")

    c = {"type": "event", "raw": "had his computer moved into the hospital",
         "sentence": "Even so, he had his computer moved into the hospital "
                     "ward so he could keep coding."}
    qs = hand_queries(c, entities=["Kingsoft"], native=lambda _c: ["求伯君"])
    blob = " ".join(qs).lower()
    ok(qs and all(w in blob for w in ("computer", "hospital", "ward")),
       f"every fact in the sentence: {qs}")

    # 9. the web path must attach those queries to every unverified row, even
    # when the sentence shares no script with the document subject
    from app.enrich import _explain

    class _W:
        raw_entities = ["求伯君"]

        def native_for(self, _c):
            return ["求伯君"]

        @staticmethod
        def _value_str(claim):
            v = claim.get("value")
            return str(int(v)) if v and float(v) == int(v) else ""

        budget = type("B", (), {"exhausted": False})()

    rows = [
        {"id": "q1", "type": "count", "raw": "three times", "value": 3.0,
         "sentence": "his chronic liver disease flared up three times",
         "verdict": "unverified", "_searched": True},
        {"id": "q2", "type": "event", "raw": "moved into the hospital ward",
         "sentence": "Even so, he had his computer moved into the hospital "
                     "ward so he could keep coding.",
         "verdict": "unverified", "_searched": True},
    ]
    _explain(rows, _W())
    ok(all(r.get("manual_checks") for r in rows),
       f"every unverified row keeps a query: {[r.get('manual_checks') for r in rows]}")
    ok(all("Try by hand" in r["suggestion"] for r in rows),
       "the note and the chips come from the same list")

    print(f"QUERY TESTS: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
