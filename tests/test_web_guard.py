"""Regression guard: web evidence must NOT be trusted unless a snippet names
one of the document's entities. Prevents the fake-'Nimbus'-matches-'public
domain 2023' false positives seen in the first live run."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.web import WebBudget, WebEvidence  # noqa: E402

JUNK = [{"title": "2023 in public domain - Wikipedia",
         "body": "works that entered the public domain in the United States in 2023",
         "href": "https://en.wikipedia.org/wiki/2023_in_public_domain"}]
REAL = [{"title": "Nimbus Cloud IPO",
         "body": "Nimbus Cloud went public in 2023 after a HK$900 million raise",
         "href": "https://example.com/nimbus-ipo"}]
AGAINST = [{"title": "Nimbus Cloud milestones",
            "body": "Nimbus Cloud went public in 2021 after its HK$900 million raise",
            "href": "https://example.com/nimbus-history"}]

claim = {"type": "year", "raw": "2023", "value": 2023.0, "currency": None,
         "sentence": "The company went public in 2023."}


def run_with(results):
    w = WebEvidence(WebBudget(50), entities=["Nimbus Cloud", "Ada Chen"])
    w.search_whitelisted = lambda q: results
    return w.verify_number(claim)


def main():
    junk = run_with(JUNK)
    assert junk["status"] != "supported", "JUNK snippet anchored to no entity must not support"
    real = run_with(REAL)
    assert real["status"] == "supported", "entity-anchored snippet should support"
    w2 = WebEvidence(WebBudget(50), entities=[])
    w2.search_whitelisted = lambda q: REAL
    assert w2.verify_number(claim)["status"] == "noentities", "no entities -> no web number check"
    # support AND contradiction in one query's results must surface BOTH camps
    # for the user to decide — never silently one-sided, never bare unverified
    cf = run_with(REAL + AGAINST)
    assert cf["status"] == "conflicting", (
        f"conflicting sources must yield `conflicting`, got {cf['status']}")
    sides = {e.get("side") for e in cf["evidence"]}
    assert sides == {"support", "contradict"}, "conflicting must carry both evidence camps"
    assert cf.get("conflicting") == "2021", "the contradicting value must be named"

    # Reuse is SUPPORT-ONLY: a snippet fetched for another claim may confirm,
    # never contradict. The 1997 Sword Heroes Fate false alarm (2026-11-02):
    # a WPS retrospective listing 1988/1989/1993/1995/1996/2010 "refuted" a
    # 1997 launch claim even though it never named that product.
    claim2 = {"type": "year", "raw": "1997", "value": 1997.0,
              "sentence": "Lingxi Quest launched in 1997 as China's first PC "
                          "role-playing game."}
    against2 = [{"title": "Kingsoft retrospective",
                 "body": "Lingxi Quest launched in 1996 as the studio's first "
                         "PC role-playing game; Kingsoft shipped WPS in 1988.",
                 "href": "https://example.com/retro"}]
    w3 = WebEvidence(WebBudget(50), entities=["Kingsoft", "金山软件"])
    w3._pool = against2
    r3 = w3.reuse_pool(claim2)
    assert r3 is None or r3["status"] != "contradicted", (
        f"reuse must never contradict, got {r3 and r3['status']}")
    support2 = [{"title": "Kingsoft timeline",
                 "body": "Kingsoft's Lingxi Quest launched in 1997 as China's "
                         "first PC role-playing game.",
                 "href": "https://example.com/timeline"}]
    w4 = WebEvidence(WebBudget(50), entities=["Kingsoft", "金山软件"])
    w4._pool = support2
    r4 = w4.reuse_pool(claim2)
    assert r4 and r4["status"] == "supported", "reuse still supports a real match"

    print("WEB GUARD PASS: unanchored snippets cannot flip number verdicts; "
          "source conflicts surface as `conflicting` with both camps; "
          "cross-claim reuse is support-only")


if __name__ == "__main__":
    main()
