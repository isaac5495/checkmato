"""Preflight planner: analyze a document, produce a CUSTOM job plan
(budget + time estimate), and let the user approve it before work starts.

Design rule: the document's needs size the budget — never a fixed time limit
that degrades quality mid-run. Time ceilings exist only as runaway safety
nets, derived from the plan itself (worst case), not as deadlines.
Measured constants: DeepSeek Search ~2.6s avg at 4.2 parallel workers (the old
keyless chain measured the same; the budget shape is unchanged); deep-read
~2.5s at 4; a free-tier LLM call ~6.5s incl. the 3.2s rate-limit gap; each
claim gets 5.6 searches by contract: keyword ladder (3) + planned deep queries
(3, overlap with cache).
"""
import math
from pathlib import Path

PER_CLAIM_SEARCHES = 5.6  # the quality contract, every doc, every claim

SEARCH_S, WORKERS = 2.6, 4.2
PAGE_S, PAGE_W = 2.5, 4.0
LLM_S = 6.5               # per LLM call incl. throttle gap

SANITY_CAPS = {  # only absurd docs hit these; hitting one is reported as <100% coverage
    "max_search": 20000,
    "max_pages": 2000,
    "deep_max_claims": 20000,
    "llm_max_calls": 4000,
}


def analyze(doc_path, corpus_dir=None, names=None):
    """Deterministic pass only (fast, offline). Returns stats for the planner."""
    from .corpus import Corpus
    from .extract import extract_claims, read_doc
    from .judge import judge
    from .names import AliasMap
    from .textproc import count_words
    doc = read_doc(doc_path)
    alias = AliasMap.load(names)
    corpus = Corpus(corpus_dir, aliases=alias)
    claims = extract_claims(doc["paragraphs"])
    judge(claims, corpus)
    from .fx import tag_conversions
    tag_conversions(claims)
    cite_idx = {i for i, p in enumerate(doc["paragraphs"])
                if p.startswith("[footnote ") or p.startswith("[endnote ")}
    from .enrich import mark_narrative
    mark_narrative(claims)  # same eligibility floor as the run: headings/questions
                            # are not pending items in the plan the user approves
    words = count_words(doc["paragraphs"])  # Word-compatible counting
    need = [c for c in claims
            if c["verdict"] in ("unverified", "deferred_web")
            and not (c.get("para") in cite_idx and c["type"] != "url")
            and not c.get("fx_secondary")]
    uniq = len({(c["type"], c["raw"].strip().lower()) for c in need})
    return {"doc": Path(doc_path).name, "words": words,
            "paras": len(doc["paragraphs"]), "claims": len(claims),
            "corpus_lines": len(corpus), "need_web": len(need),
            "uniq_need_web": uniq}


def plan(stats, web=True, llm=True):
    """The job itself, sized to THIS document: what we will do and roughly how
    long it takes. cfg floors are applied in scaled_budgets()."""
    need = max(1, stats["need_web"])
    n = max(1, stats["uniq_need_web"])
    p = {
        "searches": int(need * PER_CLAIM_SEARCHES) + 25,
        "pages": int(n * 1.6) + 8,          # deep-read ~1.6 pages/claim (numbers
                                           # read up to 3; narrative claims 2)
        "deep_checks": n + 4,               # EVERY claim gets sentence-level checks
        "llm_calls": int(n * 1.9) + math.ceil(n / 22)
        + math.ceil(stats.get("paras", 20) / 10) + 8,  # judge+page-judge/plan/semantic/pool
    }
    for k, cap in SANITY_CAPS.items():
        key = {"max_search": "searches", "max_pages": "pages",
               "deep_max_claims": "deep_checks", "llm_max_calls": "llm_calls"}[k]
        if p[key] > cap:
            p[key] = cap
    if not web:
        p["searches"] = p["pages"] = 0
    if not llm:
        p["llm_calls"] = p["deep_checks"] = 0
    det = max(2.0, stats["words"] / 250.0)
    p["sec_typ"] = int(det
                       + (p["searches"] * SEARCH_S / WORKERS if web else 0)
                       + (p["pages"] * PAGE_S / PAGE_W if web else 0)
                       + (p["llm_calls"] * LLM_S if llm else 0))
    p["seconds_typ"] = p["sec_typ"]
    p["seconds_lo"] = int(max(20, p["sec_typ"] * 0.7))
    p["seconds_hi"] = int(p["sec_typ"] * 1.8 + 40)
    return p


def scaled_budgets(stats, cfg, web=True, llm=False):
    """Turn the plan into run budgets (cfg values act as floors, never caps).
    Time ceilings are DERIVED from the plan at pessimistic rates, so a run is
    never cut short — they only stop truly runaway loops."""
    p = plan(stats, web=web, llm=llm)
    b = {
        "max_search": p["searches"],
        "max_pages": p["pages"],
        "deep_max_claims": p["deep_checks"],
        "llm_max_calls": p["llm_calls"],
        # ~2.6k counted tokens/call: the planner/pool prompts run 4-6k REAL
        # tokens in/out (plus a 2000 reserve in LLM.chat), so a 200-word doc
        # needs ~100k+ — the static config floor starved whole deep passes at
        # call 22 (silent 'everything unverified'). Must scale with the doc.
        "llm_max_tokens": p["llm_calls"] * 8000,
    }
    for k in ("max_search", "max_pages", "deep_max_claims", "llm_max_calls",
              "llm_max_tokens"):
        b[k] = max(b[k], int(cfg.get(k, 0)))
    # worst-case ceilings: 6s per search slot w/ fewer workers, 25s per LLM call
    b["web_max_seconds"] = int(b["max_search"] * 6.0 / 3.0
                               + b["max_pages"] * 10.0 / 3.0) + 300
    b["llm_max_seconds"] = b["llm_max_calls"] * 25 + 300
    if not web:
        b["max_search"] = b["web_max_seconds"] = 0
    return b


def estimate(stats, cfg, web=True, llm=False):
    """The preflight quote the user approves before anything starts."""
    p = plan(stats, web=web, llm=llm)
    b = scaled_budgets(stats, cfg, web=web, llm=llm)
    need = stats["need_web"]
    coverage_pct = round(100 * min(1, p["searches"] / max(1, int(need * PER_CLAIM_SEARCHES)))) if web else 100
    rec = None
    if web and coverage_pct < 100:
        rec = (f"Sanity caps reached: {coverage_pct}% of claims get the full "
               f"search depth. Split into sections to keep the 5-6 searches/claim contract.")
    return {"seconds_lo": p["seconds_lo"], "seconds_hi": p["seconds_hi"],
            "seconds_typ": p["seconds_typ"], "plan": p,
            "words": stats["words"], "claims": stats["claims"],
            "need_web": need, "coverage_pct": coverage_pct,
            "recommend": rec, "budgets": b}
