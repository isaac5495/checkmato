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

    # 8. Partial support: 3 of 4 listed elements found -> unverified + note,
    # never a green (user decision A).
    c = claim(raw="产品包括华光一、华光二、华光三、华光四。",
              sentence="产品包括华光一、华光二、华光三、华光四。",
              sentence_context="产品包括华光一、华光二、华光三、华光四。",
              context_sentence="产品包括华光一、华光二、华光三、华光四。")
    partial = "产品包括华光一、华光二、华光三。"
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "supported",
        "quote": partial, "note": "three products" }])])
    got = nli.judge(llm, [c], corpus=FakeCorpus([
        {"fname": "products.md", "start": 1, "end": 1, "text": partial}]))
    ok(got == 0 and c["verdict"] == "unverified", "partial is not a green")
    ok(c.get("_partial") and c["_partial"]["missing"] == ["华光四"],
       f"partial names the missing element ({c.get('_partial')})")
    ok("3/4" in c.get("suggestion", ""), "partial note states the count")

    # 8b. The full candidate passage may contain the 4th element, but the
    # MODEL'S QUOTE does not; the reader only sees the quote, so it is partial.
    c = claim(raw="产品包括华光一、华光二、华光三、华光四。",
              sentence="产品包括华光一、华光二、华光三、华光四。",
              sentence_context="产品包括华光一、华光二、华光三、华光四。",
              context_sentence="产品包括华光一、华光二、华光三、华光四。")
    full = "产品包括华光一、华光二、华光三、华光四。"
    short = "产品包括华光一、华光二、华光三。"
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "supported",
        "quote": short, "note": "three products" }])])
    got = nli.judge(llm, [c], corpus=FakeCorpus([
        {"fname": "products.md", "start": 1, "end": 1, "text": full}]))
    ok(got == 0 and c["verdict"] == "unverified",
       "a short quote cannot prove a longer list")
    ok(c.get("_partial") and c["_partial"]["missing"] == ["华光四"],
       "partial checks the quote, not the unquoted passage")

    # 9. Multi-subject: evidence covers Acme, sentence also names Orion ->
    # not one checkable subject.
    c = claim(raw="华光科技与恒宇科技签署了合作协议。",
              sentence="华光科技与恒宇科技签署了合作协议。",
              sentence_context="华光科技与恒宇科技签署了合作协议。",
              context_sentence="华光科技与恒宇科技签署了合作协议。")
    evidence = "华光科技签署了合作协议。"
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "supported",
        "quote": evidence, "note": "one company" }])])
    got = nli.judge(llm, [c], corpus=FakeCorpus([
        {"fname": "deal.md", "start": 1, "end": 1, "text": evidence}]))
    ok(got == 0 and c["verdict"] == "unverified", "one-subject evidence is not a green")
    ok(c.get("_multi_entity"), "multi-subject diagnosis is kept")

    # 10. A heading/title match is not attributed speech.
    c = claim(raw="他强调：Acme motto",
              sentence="他强调：Acme motto",
              sentence_context="他强调：Acme motto",
              context_sentence="他强调：Acme motto")
    heading = "##### “Acme motto”\nA factual line follows."
    llm = FakeLLM([json.dumps([{
        "id": "c1", "ev": 1, "verdict": "supported",
        "quote": "Acme motto", "note": "heading" }])])
    got = nli.judge(llm, [c], corpus=FakeCorpus([
        {"fname": "source.md", "start": 1, "end": 1, "text": heading}]))
    ok(got == 0 and c["verdict"] == "unverified",
       "a heading is not a quote")

    print(f"NLI TESTS: PASS ({n} assertions)")


if __name__ == "__main__":
    main()
