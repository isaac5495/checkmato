"""W1.4 semantic prose gate — support-only, verbatim-quote guarded.

Offline and synthetic (fictional Nimbus Cloud). The fake LLM lets us pin the
contract: a model may only produce `supported`; invented quotes are rejected;
contradictions are ignored; numbers never enter this lane.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASSAGE = ("Nimbus Cloud opened its Singapore office in 2019, its first "
           "overseas base, and hired twelve engineers there.")
CLAIM_TEXT = "Nimbus Cloud opened its Singapore office in 2019, its first overseas base."


class FakeCorpus:
    def __init__(self, passages):
        self.passages = passages

    def find_prose_candidates(self, text, top=3):
        return self.passages[:top]


class FakeWeb:
    def __init__(self, pool):
        self._pool = pool
        self.entities = ["Nimbus Cloud"]

    def _mentions_entity(self, blob):
        return "nimbus cloud" in (blob or "").lower()


class FakeLLM:
    available = True

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []
        self.exhausted = False

    def chat(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "[]"


def claim(**kw):
    c = {"id": "c1", "type": "event", "verdict": "unverified",
         "raw": CLAIM_TEXT, "sentence": "opened its Singapore office in 2019.",
         "sentence_context": CLAIM_TEXT, "context_sentence": CLAIM_TEXT,
         "origin": "sentence", "evidence": [], "confidence": "low",
         "suggestion": ""}
    c.update(kw)
    return c


def main():
    from app import nli

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"NLI FAIL: {msg}"
        n += 1

    corpus = FakeCorpus([{"fname": "nimbus.md", "start": 3, "end": 3,
                          "text": PASSAGE}])

    # 1. A verbatim proof supports the FULL sentence, capped at medium.
    c = claim()
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "supported",
        "quote": "opened its Singapore office in 2019", "note": "matches"}])])
    got = nli.judge(llm, [c], corpus=corpus)
    ok(got == 1 and c["verdict"] == "supported", "a verbatim passage supports")
    ok(c["confidence"] == "medium", "semantic support is capped at medium")
    ok(c.get("_semantic") is True, "the semantic origin is recorded")
    ok(c["evidence"] and c["evidence"][0]["kind"] == "local", "local evidence attached")
    ok(CLAIM_TEXT in llm.prompts[0], "the judge reads sentence_context, not the fragment")

    # 2. A paraphrased/invented quote is rejected.
    c = claim()
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "supported",
        "quote": "the company definitely opened an office there", "note": "guess"}])])
    got = nli.judge(llm, [c], corpus=corpus)
    ok(got == 0 and c["verdict"] == "unverified", "invented proof is rejected")

    # 3. A model contradiction is ignored (deterministic guards only).
    c = claim()
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "contradicted",
        "quote": "opened its Singapore office in 2019", "note": "no"}])])
    got = nli.judge(llm, [c], corpus=corpus)
    ok(got == 0 and c["verdict"] == "unverified",
       "a model contradiction must never become a verdict")

    # 4. Numbers never enter the semantic lane.
    c = claim(type="year", raw="2019")
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "supported",
        "quote": "opened its Singapore office in 2019"}])])
    got = nli.judge(llm, [c], corpus=corpus)
    ok(got == 0 and not llm.prompts, "numeric claims keep their deterministic check")

    # 5. No evidence -> no call, no verdict change.
    c = claim()
    llm = FakeLLM([])
    got = nli.judge(llm, [c], corpus=FakeCorpus([]), web=None)
    ok(got == 0 and not llm.prompts and c["verdict"] == "unverified",
       "no evidence means no semantic call")

    # 6. Web evidence works when the library has no passage.
    c = claim()
    web = FakeWeb([{"href": "https://example.com/nimbus",
                    "title": "Nimbus Cloud history", "body": PASSAGE}])
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "supported",
        "quote": "opened its Singapore office in 2019"}])])
    got = nli.judge(llm, [c], corpus=FakeCorpus([]), web=web)
    ok(got == 1 and c["evidence"][0]["kind"] == "web", "web evidence is used")

    # 7. An unavailable LLM is a no-op.
    c = claim()
    llm = FakeLLM([])
    llm.available = False
    ok(nli.judge(llm, [c], corpus=corpus) == 0 and c["verdict"] == "unverified",
       "no LLM -> no semantic verdict")

    print(f"NLI TESTS: PASS ({n} assertions)")


if __name__ == "__main__":
    main()
