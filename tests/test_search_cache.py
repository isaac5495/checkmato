"""Persistent SERP cache + quote pool-first.

Guards the cost fix against quality drift:
- the same query is never paid for twice;
- a miss still sends the original query unchanged;
- empty SERPs are never cached (a transient miss must not freeze a claim);
- verdicts are never cached;
- quotes may reuse a verbatim pool match; numbers still search (the direct
  search is the only path that can surface a conflicting value).
"""
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.enrich import _apply_web  # noqa: E402
from app.searchcache import normalize_query  # noqa: E402
from app.web import WebBudget, WebEvidence  # noqa: E402

SERP = [{"title": "Nimbus Cloud timeline",
         "href": "https://example.com/nimbus",
         "body": "Nimbus Cloud went public in 2023 after a HK$900 million raise."}]

QUOTE = "We build infrastructure for people, not for quick profits."


def make_web(tmp, calls, **kw):
    w = WebEvidence(WebBudget(10, 60, 0, 0),
                    entities=["Nimbus Cloud"],
                    cache_path=str(Path(tmp) / "cache.sqlite"), **kw)
    w.available = True
    w.only = "deepseek"

    def _backend(q, n):
        calls.append(q)
        return [dict(r) for r in SERP]

    w._backend = _backend
    return w


def close_all(*webs):
    for w in webs:
        w.cache.close()


def test_hit_and_normalization():
    with tempfile.TemporaryDirectory() as tmp:
        calls = []
        w = make_web(tmp, calls)
        r1 = w.search("Nimbus Cloud 2023")
        assert r1 == SERP and w.budget.used == 1
        assert w.cache.writes == 1

        w2 = make_web(tmp, calls)
        r2 = w2.search("  nimbus   cloud 2023 ")
        assert r2 == r1, "case/whitespace variants must hit the same entry"
        assert len(calls) == 1, "a cache hit must not call the backend"
        assert w2.budget.used == 0, "a cache hit must not spend search budget"
        assert w2.cache.hits == 1
        assert w2._pool and w2._pool[0]["href"] == SERP[0]["href"], (
            "a cached SERP must still join the run's cross-claim evidence pool")
        close_all(w, w2)
    assert normalize_query('"Exact Phrase"') != normalize_query("Exact Phrase"), (
        "punctuation is meaning-bearing and must stay in the key")


def test_ttl_expiry():
    with tempfile.TemporaryDirectory() as tmp:
        calls = []
        w = make_web(tmp, calls)
        w.search("Nimbus Cloud 2023")
        w.cache.close()
        conn = sqlite3.connect(str(Path(tmp) / "cache.sqlite"))
        conn.execute("UPDATE serp_cache SET created_at=?",
                     (time.time() - 15 * 86400,))
        conn.commit()
        conn.close()
        w2 = make_web(tmp, calls)
        w2.search("Nimbus Cloud 2023")
        assert len(calls) == 2, "an expired entry must be re-fetched"
        close_all(w2)


def test_empty_not_cached():
    with tempfile.TemporaryDirectory() as tmp:
        calls = []
        w = make_web(tmp, calls)

        def empty(q, n):
            calls.append(q)
            return []

        w._backend = empty
        assert w.search("Nimbus Cloud 2099") == []
        w2 = make_web(tmp, calls)
        w2._backend = empty
        assert w2.search("Nimbus Cloud 2099") == []
        assert len(calls) == 2, "an empty SERP must not be frozen for 14 days"
        close_all(w, w2)


def test_refresh_and_disable():
    with tempfile.TemporaryDirectory() as tmp:
        calls = []
        w = make_web(tmp, calls)
        w.search("Nimbus Cloud 2023")
        w2 = make_web(tmp, calls, refresh_cache=True)
        w2.search("Nimbus Cloud 2023")
        assert len(calls) == 2, "--refresh-search must bypass the read"
        assert w2.cache.hits == 0
        close_all(w, w2)

        calls2 = []
        w3 = make_web(tmp, calls2, cache_enabled=False)
        w3.search("Nimbus Cloud 2023")
        w4 = make_web(tmp, calls2, cache_enabled=False)
        w4.search("Nimbus Cloud 2023")
        assert len(calls2) == 2, "cache_enabled=False must never read or write"
        close_all(w3, w4)


def test_quote_reuses_pool_without_search():
    with tempfile.TemporaryDirectory() as tmp:
        w = make_web(tmp, [])
        w._pool = [{"title": "Interview", "href": "https://example.com/q",
                    "body": QUOTE}]
        fired = []
        w.verify_quote = lambda claim: (fired.append(claim["id"])
                                        or {"status": "notfound"})
        c = {"id": "c1", "type": "quote", "raw": QUOTE,
             "sentence": 'Ada Chen said: "' + QUOTE + '"',
             "verdict": "unverified", "evidence": [], "confidence": "low"}
        _apply_web(c, w, deep=False)
        assert c["verdict"] == "supported"
        assert c["confidence"] == "medium"
        assert c["_searched"] is True and c["_reuse"] is True
        assert not fired, "a verbatim pool quote must not spend a search"
        close_all(w)


def test_number_still_searches():
    with tempfile.TemporaryDirectory() as tmp:
        w = make_web(tmp, [])
        w._pool = [{"title": "Nimbus Cloud timeline",
                    "href": "https://example.com/n",
                    "body": "Nimbus Cloud went public in 2023."}]
        fired = []
        w.verify_number = lambda claim: (fired.append(claim["id"])
                                         or {"status": "notfound", "evidence": []})
        c = {"id": "c2", "type": "year", "raw": "2023", "value": 2023.0,
             "sentence": "Nimbus Cloud went public in 2023.",
             "verdict": "unverified", "evidence": [], "confidence": "low"}
        _apply_web(c, w, deep=False)
        assert fired, ("numeric claims must keep the direct search: only it "
                       "can surface a conflicting value")
        close_all(w)


def main():
    test_hit_and_normalization()
    test_ttl_expiry()
    test_empty_not_cached()
    test_refresh_and_disable()
    test_quote_reuses_pool_without_search()
    test_number_still_searches()
    print("SEARCH CACHE PASS: same query = no second bill; empty SERPs and "
          "numeric contradiction checks are never short-circuited")


if __name__ == "__main__":
    main()
