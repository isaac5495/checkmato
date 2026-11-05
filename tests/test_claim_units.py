"""W1.3 claim-unit gate: sentence ids, slots, fragment joins, structure.

Synthetic only (fictional 华光), no private case material. The per-figure
verdicts must stay intact; this gate only checks grouping/context metadata.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.extract import extract_claims

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"CLAIM UNIT FAIL: {msg}"
        n += 1

    # 1) one sentence with several figures = one sentence_id, several slots
    claims = extract_claims(
        ["Acme reported revenue of 125 million dollars in 2019, up 20% from 2018."])
    sids = {c["sentence_id"] for c in claims}
    ok(len(sids) == 1, f"one sentence has one sentence_id (got {sids})")
    ok(all(c["sentence_claim_count"] == len(claims) for c in claims),
       "every slot reports the sentence's claim count")
    ok(sum(1 for c in claims if c["is_primary"]) == 1,
       "exactly one primary claim per sentence")
    ok(all(c["slot_kind"] == "number" for c in claims),
       f"figures are slots, not events ({[c['slot_kind'] for c in claims]})")

    # 2) a closing quote must not split the sentence; `时，...` rejoins it
    claims = extract_claims(
        ["华光在思考「为何同行相继消亡」时，总结出了六个关键词：韧性、专注。"])
    sentences = {c["sentence"] for c in claims}
    ok(any("华光在思考" in s and "时，总结出了" in s for s in sentences),
       f"quote-closer continuation is one sentence ({sentences})")
    ok(not any(s.strip().startswith("时，") for s in sentences),
       "no claim starts at the orphaned `时，` fragment")

    # 3) a true fragment after a full stop is attached to the previous sentence
    claims = extract_claims(
        ["华光在2023年召开了会议。时，总结出了六个关键词：兄弟文化、技术立业、快乐工作、韧性。"])
    frags = [c for c in claims
             if c["type"] == "event" and "时，总结" in c["sentence"]]
    ok(frags, "the orphan fragment is still visible")
    if frags:
        f = frags[0]
        ok(f["fragment_of_previous"],
           "the fragment is marked as continuing the previous sentence")
        ok("华光在2023年召开了会议" in (f.get("parent_sentence") or ""),
           f"the parent sentence is kept ({f.get('parent_sentence')})")
        prev = [c for c in claims
                if "华光在2023年召开了会议" in c["sentence"]
                and c["sentence_id"] == f["sentence_id"]]
        ok(prev, "the fragment shares the previous sentence's id")

    # 4) URLs/placeholders are structure, not sentence claims
    claims = extract_claims(["See https://example.com/report for details."])
    urls = [c for c in claims if c["type"] == "url"]
    ok(urls and urls[0]["slot_kind"] == "structure",
       f"URL is structure ({urls[0]['slot_kind'] if urls else 'missing'})")

    print(f"CLAIM UNIT TESTS: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

