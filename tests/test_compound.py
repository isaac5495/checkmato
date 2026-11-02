"""Compound-sentence splitting: one clause's figure must not hide the other
clause's prose, and every claim keeps a span into the ORIGINAL paragraph."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app import extract as ex
    from app.normalize import split_compound

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"COMPOUND FAIL: {msg}"
        n += 1

    # 1. the splitter's own spans point into the original sentence
    sent = "A opened X in 2011, and B opened Y in 2012."
    parts = split_compound(sent)
    ok(len(parts) == 2, f"two clauses ({parts})")
    for part, start, end in parts:
        ok(part in sent[start:end], f"clause offset is exact ({part!r})")

    # 2. extraction actually calls the splitter (instrumented, not assumed)
    calls = []
    orig = ex.split_compound

    def spy(text):
        calls.append(text)
        return orig(text)

    ex.split_compound = spy
    try:
        claims = ex.extract_claims([sent])
    finally:
        ex.split_compound = orig
    ok(calls == [sent], f"extraction calls split_compound ({calls})")

    # 3. the DoD sentence yields one claim per figure, both anchored
    years = [c for c in claims if c["type"] == "year"]
    ok(sorted(c["raw"] for c in years) == ["2011", "2012"],
       f"both clause figures survive ({[c['raw'] for c in years]})")
    for c in claims:
        s, e = c["span"]
        ok(sent[s:e] == c["raw"],
           f"span points at the original text ({c['raw']!r})")
        ok(c["sentence"] == sent, "the displayed sentence stays the original")

    # 4. one numeric clause + one prose clause: the prose clause is a claim
    s2 = "Acme opened a plant in Bergen, and Acme hired 200 staff in 2011."
    claims2 = ex.extract_claims([s2])
    events = [c for c in claims2 if c["type"] == "event"]
    ok(len(events) == 1, f"the prose clause becomes one event ({events})")
    ev = events[0]
    ok(ev["raw"] == "Acme opened a plant in Bergen",
       f"the event is the clause, not the sentence ({ev['raw']!r})")
    ok(s2[ev["span"][0]:ev["span"][1]] == ev["raw"], "event span is anchored")
    ok(ev["sentence"] == s2, "event keeps the whole sentence for context")

    # 5. a one-clause sentence is unchanged
    s3 = "Acme opened a plant in Bergen."
    c3 = ex.extract_claims([s3])
    ok(len(c3) == 1 and c3[0]["raw"] == s3,
       f"single clause stays whole ({[c['raw'] for c in c3]})")

    print(f"COMPOUND: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
