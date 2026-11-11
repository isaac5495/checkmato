"""M0.5 enrichment layer: web evidence + optional LLM assistance.

Runs AFTER the deterministic BYOS pass and only touches claims still `unverified`
(or LLM-proposed semantic claims). Order per claim: BYOS grep > web > LLM-judged
web snippets. Every upgrade must attach the evidence it used; budgets degrade
honestly into a visible note, never into a guess.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from . import corpus as corp
from . import llm as llm_mod
from . import textproc as tp


def mark_narrative(claims, heading_paras=()):
    """Deterministic eligibility floor: a claim carried entirely by a heading or
    a rhetorical QUESTION asserts nothing checkable — a human checker would not
    open an item for it. Mark those 'narrative' (visible, with a reason; never
    searched, never counted as pending).

    `heading_paras` comes from the document reader (docx styles / md '#'), which
    is the only reliable signal for a Word heading: its text has no marker.
    """
    heads = set(heading_paras or ())
    for c in claims:
        if c["verdict"] != "unverified":
            continue
        s = (c.get("sentence") or "").strip()
        if c.get("para") in heads or s.startswith("#") or s.endswith(("?", "？")):
            c["verdict"] = "narrative"
            c["confidence"] = "n/a"
            c["_skip_reason"] = "heading/question text — asserts no checkable fact"
            c["suggestion"] = ("Narrative context (heading, title or question): "
                               "states no fact to search — kept visible for "
                               "transparency.")


_COMMENTARY_RULES = (
    (re.compile(r"我们将|本文将|本章将|本节将|接下来|下面我们|本文旨在|本章旨在"),
     "authorial method/transition"),
    (re.compile(r"(?:\d+年|多年|几十年来|这些年来)[^。！？]{0,24}"
                r"(?:历经|经历|走过|见证)"),
     "temporal summary, not a single checkable event"),
    (re.compile(r"如出一辙|破局轨迹"), "interpretive summary"),
    (re.compile(r"已逐渐凝聚为|凝聚为一种|坚定的信念"), "belief/value statement"),
    (re.compile(r"从来不是[^。！？]{0,30}而是|绝非[^。！？]{0,20}而是"),
     "evaluative contrast"),
    (re.compile(r"深入剖析|系统梳理|试图揭示"), "authorial method/analysis"),
    (re.compile(r"这正是[^。！？]{0,30}(?:期望|局面|设计)"),
     "evaluative conclusion"),
    (re.compile(r"始终未变|没有固守[^。！？]{0,30}而是"),
     "evaluative analysis"),
    (re.compile(r"面临着[^。！？]{0,20}考验|随着[^。！？]{0,20}扩张"
                r"[^。！？]{0,30}考验"), "evaluative summary"),
    (re.compile(r"充满活力与灵气|鲜明的业务风格|务实理性|"
                r"既无[^。！？]{0,20}也无"), "evaluative characterisation"),
    (re.compile(r"本质上是|文化内核|镜像映射|方言表达|底层逻辑|"
                r"战略转折点|自我更新|留给读者"),
     "interpretive/analogical summary"),
    (re.compile(r"以避免[^。！？]{0,30}(?:掩盖|口才)"),
     "design rationale, not an event"),
    (re.compile(r"同一个领袖|两家公司[^。！？]{0,30}(?:分别|战略)"),
     "multi-subject comparison"),
)


def mark_commentary(claims):
    """Deterministic eligibility floor for commentary/analysis.

    A `sources_only` run has no LLM triage, so essay prose such as "38年来…"
    or "我们将深入剖析…" would otherwise be sent to retrieval and reported as
    'unverified'. Mark only clear authorial/interpretive markers as narrative;
    numeric and quote claims are untouched. Conservative by design: a false
    negative is safer than silently dropping a real fact (rule 3).
    """
    for c in claims:
        if c.get("verdict") != "unverified":
            continue
        if c.get("type") not in ("event", "sentence"):
            continue
        s = (c.get("sentence") or "").strip()
        for rx, why in _COMMENTARY_RULES:
            if rx.search(s):
                c["verdict"] = "narrative"
                c["confidence"] = "n/a"
                c["_skip_reason"] = (
                    f"commentary/analysis ({why}) — not searched by design")
                c["suggestion"] = (
                    f"Narrative context (commentary/analysis: {why}): states "
                    "no single checkable fact — kept visible for transparency.")
                break


def classify_prose(llm, claims, progress=None):
    """LLM triage of prose claims: FACTUAL (an outside source could document
    it) vs COMMENT (author's voice: interpretation, emotion, transition).
    Only COMMENT answers change anything — anything missing/failed stays
    unverified-and-searched, so a flaky classifier can never silently drop
    a real fact (rule 3: no silent skipping, ever)."""
    if not (llm and llm.available):
        return
    _p = progress or (lambda e: None)
    todo = [c for c in claims if c["verdict"] == "unverified"
            and c.get("origin") == "sentence"
            and not (c.get("citation") and c["type"] != "url")
            and not c.get("fx_secondary")]
    if not todo:
        return
    _p({"stage": "triage", "claims": len(todo), "item": "classifying prose: facts vs commentary"})
    moved = 0
    for k in range(0, len(todo), 24):
        if llm.exhausted:
            break
        batch = todo[k:k + 24]
        rows = [{"id": c["id"],
                 "text": (c.get("context_sentence") or c["sentence"])[:200]}
                for c in batch]
        raw = llm.chat(
            "You triage sentences from a document for a fact-checker. A sentence "
            "is FACTUAL if it asserts something an outside source could document "
            "(an event, date, quantity, action by a named person, attribution, "
            "a specific practice or policy); it is COMMENT if the MAIN assertion "
            "is the author's voice: interpretation, evaluation, analogy, "
            "rhetorical summary, a statement about a period/trend, or lines about "
            "the case study itself. A sentence that contains both a specific "
            "practice/fact AND an interpretation is FACTUAL — the specific part "
            "is checkable. Only COMMENT when there is no specific checkable "
            "event, figure, person, quote or practice at all. Examples: "
            'COMMENT: "历经近38年的自我更新，金山再次站在战略转折点上" '
            '(period summary). COMMENT: "金山的六脉神剑与小米的八条价值观，'
            '本质上是同一种文化内核" (analogy). FACTUAL: "聚餐、跨部门体育联赛'
            '等文化建设形式..." (specific practices). FACTUAL: "雷军认为这是一场'
            '以十年为维度的战略长征" (attributed position). Return ONLY a JSON '
            'array listing the COMMENT ones: {"id":"<id>","why":"<why nothing is '
            'checkable, max 80 chars>"}. A sentence you do not list is treated as '
            "FACTUAL and WILL be searched — only list clear commentary.\n\n"
            + json.dumps(rows, ensure_ascii=False) + "\n\nJSON:")
        arr = llm_mod.re_json(raw) if raw else []
        for d in arr if isinstance(arr, list) else []:
            cid = str(d.get("id") or "")
            c = next((x for x in batch if x["id"] == cid), None)
            if not c or c["verdict"] != "unverified":
                continue
            c["verdict"] = "narrative"
            c["confidence"] = "n/a"
            c["_skip_reason"] = "commentary/narration (LLM triage) — not searched by design"
            c["suggestion"] = ("Narrative context — " +
                               (str(d.get("why") or "no externally checkable fact")
                                .strip()[:120]) +
                               "; nothing to search.")
            moved += 1
    _p({"stage": "triage_done", "narrative": moved, "checked": len(todo),
        "item": f"{moved} of {len(todo)} prose sentences are commentary, not facts"})


NUMERIC = ("year", "amount", "pct", "count", "quote", "url", "fx", "timeline")


def _demote_snippet_contradiction(claim, note):
    """An LLM verdict of 'contradicted' — snippet OR passage level — never
    stands as fact: free judges ignore the lookalike-entity and tense rules
    they were given (a Kingsoft CLOUD snippet 'refuting' a Kingsoft Corp
    claim), and rule 7 says contradiction has the higher bar than support.
    Only the deterministic guards (corpus judge, _assess_number predicate/
    value/time checks) may conclude 'contradicted' outright. LLM says no?
    Show BOTH camps and let the user decide."""
    claim["verdict"] = "conflicting"
    for e in claim.get("evidence") or []:
        if e.get("kind") == "web" and not e.get("side"):
            e["side"] = "contradict"
    claim["suggestion"] = (note + " — but this is an LLM reading of the "
                           "evidence, not a settled contradiction; review "
                           "both sides and decide.")


def _tier_warn(claim):
    """Academic credibility: an open encyclopedia (Wikipedia/百度百科) alone is
    corroboration, not authority — say so instead of pretending it is equal."""
    web_ev = [e for e in claim.get("evidence") or [] if e.get("kind") == "web"]
    if web_ev and all(e.get("tier") == "open-community" for e in web_ev):
        claim["suggestion"] = (claim.get("suggestion") or "") + \
            " [open-community source only — for academic use, corroborate with a primary/scholarly source]"


def _apply_narrative(claim, web):
    """A descriptive sentence of prose is NEVER quoted verbatim into a search
    (nobody online quotes this article) and is never auto-supported by mere
    word overlap (that manufactures false greens). With an LLM it gets proper
    planned natural-language queries in the deep pass; here (LLM unavailable)
    it gets a topic-anchored probe + the exact query for the user to try."""
    sl = (claim.get("context_sentence") or claim["sentence"]).lower()
    primary = next((e for e in web.raw_entities
                    if e and tp.normalize(e) in tp.normalize(sl)),
                   web.raw_entities[0] if web.raw_entities else "")
    phr = tp.rare_phrase(
        claim.get("raw") or claim.get("context_sentence") or claim["sentence"], 5)
    if not phr.strip():  # no distinctive phrasing = entity-only query;
        # searching "Kingsoft" alone wastes a slot and reads as broken advice
        claim["_skip_reason"] = "no query-able content beyond the entity name"
        claim["suggestion"] = ("Descriptive sentence with no distinctive "
                               "phrasing to search; open a source on the "
                               "subject and compare by hand.")
        return
    q = f"{primary} {phr}".strip()
    if not q:
        claim["_skip_reason"] = "no entity to anchor a narrative search"
        return
    res = web.search_whitelisted(q)
    if res is None:
        claim["_skip_reason"] = ("web budget reached" if web.budget.exhausted
                                 else "search backend unavailable")
        return
    claim["_searched"] = True
    claim["_web_q"] = q
    cands = [r for r in res
             if web._mentions_entity((r.get("body") or "") + " " + (r.get("title") or ""))]
    if cands:
        claim["evidence"] = (claim.get("evidence") or []) + web._snippet_evidence(cands[:2])
        claim["suggestion"] = ("Found topically-related pages; snippets do not prove the "
                               "narration — open the source to confirm.")
    else:
        claim["suggestion"] = "Web searched, nothing topically relevant found."


def _apply_web(claim, web, deep=False):
    claim["_searched"] = False
    if claim.get("citation") and claim["type"] != "url":
        # a footnote/endnote is the SOURCE, not a checkable assertion — do not
        # spend a search proving citations; their URLs still get liveness-probed
        claim["_skip_reason"] = "citation text (footnote) — not fact-checked by design"
        claim["suggestion"] = ("This is source/attribution text from a footnote, "
                               "not a claim to verify. Check the linked work itself.")
        return
    if claim.get("fx_secondary"):
        # "RMB 66 million (about US$13.8 million)" — the second figure is the
        # SAME money restated; judging it against web snippets out of context
        # manufactures fake contradictions (today's rate ≠ 1990's rate).
        # The FX verifier settles the pair arithmetically, after this pass.
        claim["_skip_reason"] = "parenthetical currency conversion — judged by FX arithmetic"
        return
    if deep and claim["type"] in ("event", "name", "timeline"):
        # PROSE claims (no figure to match deterministically) are where the
        # content-level planned-query pass pays off. NUMERIC claims must NOT
        # be reserved for it: the deterministic _assess_number matcher judges
        # "15.68%" against a Baidu-Baike/IR-filing snippet for free and
        # correctly, while the free-tier LLM judge waffled 'unverified' on
        # obvious evidence (the real cause of 'too many unverified').
        claim["_skip_reason"] = "reserved for the sentence-level deep check"
        return
    if claim["type"] == "quote":
        # Zero-risk reuse: a verbatim quote already in this run's pool is the
        # SAME >=0.9 wording match a direct search would apply, and quotes have
        # no contradiction path (`_assess_quote` is support/notfound only).
        # Numbers deliberately do NOT short-circuit here: a skipped direct
        # search could miss the conflicting-value guard.
        reused = web.reuse_pool(claim)
        if reused and reused.get("status") == "supported":
            if _apply_reuse(claim, reused):
                claim["_searched"] = True
                claim["_reuse"] = True
                return
        r = web.verify_quote(claim)
    elif claim["type"] in ("year", "amount", "pct", "count"):
        r = web.verify_number(claim)
    elif claim["type"] == "url":
        claim["_searched"] = True
        st = web.url_status(claim["raw"])
        if st is None:
            claim["_searched"] = False
            claim["_skip_reason"] = "URL liveness not probed (budget)"
            claim["suggestion"] = "URL not checked — web budget reached (retry next run)."
            return
        if isinstance(st, int) and st < 400:
            claim["evidence"] = [{"kind": "web", "ref": claim["raw"],
                                  "quote": f"HTTP {st} — reachable", "precision": "snippet"}]
            claim["verdict"], claim["confidence"] = "supported", "medium"
            claim["suggestion"] = "URL resolves."
        elif isinstance(st, int) and st in (403, 429):
            claim["suggestion"] = f"URL returned {st} (maybe anti-bot; check manually)."
        else:
            claim["verdict"], claim["confidence"] = "needs_fix", "medium"
            claim["suggestion"] = "URL does not resolve (dead link)."
        return
    else:
        if (claim["type"] in ("event", "name", "timeline", "citation", "fx", "number")
                or claim.get("origin") in ("sentence", "llm")):
            _apply_narrative(claim, web)  # prose is not a verbatim quote query
            return
        r = web.verify_quote(claim)  # REAL quotation marks: search the wording itself
    if r.get("query"):
        claim["_web_q"] = r["query"]
    if r.get("queries"):
        claim["_web_queries"] = r["queries"]
    st = r.get("status")
    if st in ("supported", "contradicted", "conflicting", "notfound", "noresults"):
        claim["_searched"] = True
    if st == "budget":
        claim["_skip_reason"] = "web budget reached before this item"
        claim["suggestion"] = "Not checked — web search budget reached this run."
        return
    if st == "unavailable" or st == "noentities":
        claim["_skip_reason"] = ("search backend unavailable" if st == "unavailable"
                                 else "no subject/entity to anchor a search")
        return
    # snippets were topical but did not settle it: DEEP-READ those pages
    # (the human "click the promising result and Ctrl+F" step)
    if st in ("notfound", "noresults") and web.can_pages():
        urls = [e.get("ref", "") for e in r.get("evidence", [])]
        pr = web.read_evidence(claim, urls)
        if pr and pr.get("status") in ("supported", "contradicted", "conflicting"):
            r = pr
            st = pr["status"]
    ev = r.get("evidence", [])
    if st == "conflicting":
        claim["verdict"], claim["confidence"] = "conflicting", "medium"
        claim["evidence"] = (claim.get("evidence") or []) + ev[:4]
        claim["suggestion"] = (
            f"Sources disagree: some support this, at least one states "
            f"{r.get('conflicting', 'a different value')}. Both camps are shown — "
            "needs your call: keep the claim, fix it, or dismiss the flag.")
    elif st == "supported":
        if claim.get("origin") == "llm" and claim["type"] != "quote":
            # narrative free-text events cannot be settled by topical snippets
            # (PRD G2: never assert beyond the evidence shown)
            claim["evidence"] = (claim.get("evidence") or []) + ev[:2]
            claim["suggestion"] = ("Web pages look topically relevant but do not "
                                   "confirm this narrative — review manually.")
            return
        claim["verdict"], claim["confidence"] = "supported", "medium"
        claim["evidence"] = (claim.get("evidence") or []) + ev[:3]
        deep = bool(ev) and ev[0].get("precision") == "passage"
        claim["suggestion"] = ("Full page text states this (deep-read)."
                               if deep else
                               f"Web snippet matches the assertion "
                               f"({min(len(ev), 3)} independent source"
                               f"{'s' if min(len(ev), 3) > 1 else ''}).")
        _tier_warn(claim)
    elif st == "contradicted":
        claim["verdict"], claim["confidence"] = "contradicted", "medium"
        claim["evidence"] = (claim.get("evidence") or []) + ev[:2]
        deep = bool(ev) and ev[0].get("precision") == "passage"
        claim["suggestion"] = (
            f"{'A page read in full' if deep else 'Web source'} states "
            f"{r.get('conflicting', 'a different value')}.")
        _tier_warn(claim)
    else:
        if ev and claim["type"] == "quote" and r.get("ratio", 0) >= corp.PARAPHRASE_CUT:
            claim["verdict"], claim["confidence"] = "paraphrase_flag", "low"
            claim["evidence"] = ev[:1]
            claim["suggestion"] = (f"Nearest web wording differs "
                                   f"({r['ratio']:.0%} similar) — possible embellishment.")
        else:
            claim["suggestion"] = "Web searched, nothing found — leave unverified."


def _apply_reuse(claim, r, _p=None, used=0,
                 note="snippet already retrieved this run (related claim)"):
    """Apply a pool match: support or both-camps conflict, never `contradicted`.

    reuse_pool refuses contradictions by contract, so this can never invent a
    red flag from a page that merely lists many years/figures."""
    st = r.get("status")
    if st not in ("supported", "conflicting"):
        return False
    ev = (r.get("evidence") or [])[:4 if st == "conflicting" else 1]
    if not ev:
        return False
    for e in ev:
        e["note"] = note
    claim.pop("_skip_reason", None)
    if st == "conflicting":
        claim["verdict"], claim["confidence"] = "conflicting", "medium"
        claim["evidence"] = (claim.get("evidence") or []) + ev
        claim["suggestion"] = ("Snippets fetched earlier in this run disagree — "
                               "some support this, one states "
                               f"{r.get('conflicting', 'a different value')}. "
                               "Both camps shown; needs your call.")
    else:
        claim["verdict"], claim["confidence"] = "supported", "medium"
        claim["evidence"] = (claim.get("evidence") or []) + ev
        claim["suggestion"] = ("Confirmed by an evidence snippet fetched earlier "
                               "in this run — nothing extra searched.")
    if _p:
        _p({"stage": "reuse", "id": claim["id"], "used": used,
            "item": claim["raw"][:60]})
    return True


def _reuse_pass(claims, web, _p):
    """One good source settles every claim it literally covers: re-match every
    snippet already fetched this run against still-unverified claims. Local
    matching only — zero extra search budget, same strict guards."""
    for c in claims:
        if c["verdict"] != "unverified":
            continue
        if (c.get("citation") and c["type"] != "url") or c.get("fx_secondary"):
            continue
        r = web.reuse_pool(c)
        if not r:
            continue
        st = r.get("status")
        if st == "contradicted":
            # reuse_pool is support-only by contract; ignore a contradiction
            # defensively so no future caller can re-introduce the year-list
            # false alarm (2026-11-02).
            continue
        _apply_reuse(c, r, _p=_p, used=web.budget.used)


def _claim_rare(c):
    return {tp.normalize(t) for t in tp.rare_raw_tokens(c.get("sentence") or "")
            if len(t) > 2}


_PROP_RX = re.compile(r"\b[A-Z][\w'\u00c0-\u00ff\-]{3,}\b")


def _prop_words(sent, entlow):
    """Words that BEHAVE like proper names: capitalized somewhere in the
    MIDDLE of a sentence ('of the Cai Wu Wei Hotel'), not places, not
    fragments of entities the query already carries. Sentence-initial
    capitals are not names: 'Even so, he…' once produced the query
    'Kingsoft Even'."""
    joined = " ".join(sorted(entlow))
    out = []
    for w in _PROP_RX.findall(sent or ""):
        lw = w.lower().strip("'-.")
        if (len(lw) < 4 or lw in entlow or lw in tp.GENERIC_PLACES
                or lw in joined or lw in out):
            continue
        if not re.search(r"[a-z,'\"]\s+" + re.escape(w) + r"\b", sent or ""):
            continue
        out.append(w)
    return out


def _fig_str(c):
    v = c.get("value")
    if v is None or c["type"] not in ("year", "amount", "pct", "count"):
        return ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    return str(int(v)) if v == int(v) else str(v)


def _source_clusters(claims, web, max_clusters=8):
    """Group claims that ONE article could answer: shared entities and
    vocabulary merge them, so each page gets read once and judged many.
    (A human does not re-Google 60 claims; they find a few good pages.)"""
    ents = [str(e) for e in (web.raw_entities or []) if e]

    def cents(c):
        sl = tp.normalize(c.get("sentence") or "")
        return {e for e in ents if len(e) > 2 and tp.normalize(e) in sl}

    clusters = []
    for c in claims:
        t, ce = _claim_rare(c), cents(c)
        best, score = None, 0
        for cl in clusters:
            if len(cl["claims"]) >= 14:
                continue
            s = len(t & cl["toks"]) + 2 * len(ce & cl["ents"])
            if s > score:
                best, score = cl, s
        if best is not None and score >= 3:
            best["claims"].append(c)
            best["toks"] |= t
            best["ents"] |= ce
        else:
            clusters.append({"claims": [c], "toks": t, "ents": ce})
    clusters.sort(key=lambda cl: -len(cl["claims"]))
    return clusters[:max_clusters]


def _cluster_queries(cl, web):
    """The queries a human would type for this batch. Shape matters: short,
    entity-anchored, figures FIRST (decimals like '15.68%' are self-anchoring;
    '100000000' never appears in an article, 'US$100 million' does), the
    subject's NATIVE script even when the document is in Latin letters, and
    proper nouns from the sentences instead of random word soup.
    One entity·figure query PER figure (rule 7): '求伯君 1984' and '求伯君 501'
    are two different human searches — a single multi-figure query silently
    starves every number not in its first two slots."""
    lat = [e for e in sorted(cl["ents"]) if e.isascii()][:3]
    nat = [e for e in sorted(cl["ents"]) if not e.isascii()]
    if not nat:
        # the doc may name everyone in Latin script (Kingsoft) while the
        # facts live in Chinese articles (金山软件) — the subject's native
        # alias was resolved by resolve_subject; use it regardless
        nat = [str(e) for e in web.raw_entities
               if e and not str(e).isascii()][:2]
    if not lat and web.raw_entities:
        lat = [str(e) for e in web.raw_entities if str(e).isascii()][:1]
    figs = []
    for c in sorted(cl["claims"],
                    key=lambda x: "." not in (x.get("raw") or "")):
        if c["type"] == "amount":
            fg = (c.get("raw") or "").strip() or _fig_str(c)
        elif c["type"] in ("year", "pct", "count"):
            fg = _fig_str(c)  # digits travel: 'twenty-four' never appears on a CJK page
        else:
            fg = ""
        if fg and 2 <= len(fg) <= 24 and fg not in figs:
            figs.append(fg)
        if len(figs) >= 6:
            break
    entlow = {str(x).lower() for x in lat + nat}
    props = []
    for c in cl["claims"]:
        for w in _prop_words(c.get("sentence") or "", entlow):
            if w not in props:
                props.append(w)
            if len(props) >= 2:
                break
        if len(props) >= 2:
            break
    qs = []
    for c in cl["claims"]:
        if c["type"] == "amount":
            fg = (c.get("raw") or "").strip() or _fig_str(c)
        elif c["type"] in ("year", "pct", "count"):
            fg = _fig_str(c)
        else:
            fg = ""
        if not fg:
            continue
        head = next(iter(web.native_for(c)), nat[0] if nat else "")
        if head and len(fg) >= 2:
            qs.append(f"{head} {fg}")
    # the document's OWN Chinese phrases (a slogan beside its translation) are
    # verbatim strings real sources carry — quote them; never mixed-script soup
    for c in cl["claims"]:
        for run in tp.cjk_runs(c.get("sentence") or "")[:1]:
            if len(run) >= 6:
                qs.append(f'"{run}"')
    if lat:
        latin = " ".join([lat[0]] + props[:2] + figs[:1]).strip()
        if latin != lat[0]:  # entity alone is not a query
            qs.append(latin)
    return [q for q in dict.fromkeys(qs) if 5 <= len(q) < 90][:8]


def _page_passages(web, claims, urls, cap=20):
    """Full-text Ctrl+F across the pages: sentence windows scored by which
    claims' figures and rare words they carry — whole-page evidence for the
    whole cluster at once, replacing snippet confetti."""
    want = []
    for c in claims:
        fig = _fig_str(c)
        toks = _claim_rare(c)
        if fig or toks:
            want.append((fig, toks))
    out = []
    for u in urls:
        page = web.page_text(u)
        if not page:
            continue
        sents = [s.strip() for s in re.split(r"(?<=[.!?。！？;])\s+", page["text"])
                 if len(s.strip()) > 15]
        scored = []
        for i, s in enumerate(sents):
            ns = tp.normalize(s)
            nd = ns.replace(".", "").replace(",", "")  # 15.68% survives digit-strip
            sc = 0
            for fig, toks in want:
                if fig and (fig in ns or fig.replace(".", "") in nd):
                    sc += 10
                sc += min(3, sum(1 for t in toks if t in ns))
            if sc:
                scored.append((sc, i))
        scored.sort(key=lambda t: (-t[0], t[1]))
        # MERGE, don't skip: a rival window must never delete a scored
        # sentence (one run lost '15.68%' because the '2007' window touched it)
        picks = set()
        for _, i in scored[:10]:
            picks.update(range(max(0, i - 1), min(len(sents), i + 2)))
        run = []

        def flush(run):
            if not run:
                return None
            out.append({"ref": page["url"],
                        "text": " ".join(sents[k] for k in run)[:600]})
            return len(out) >= cap

        for i in sorted(picks):
            if run and i != run[-1] + 1:
                if flush(run):
                    return out
                run = []
            run.append(i)
        if flush(run):
            return out
    return out


def _apply_assessment(c, r, note):
    st = r.get("status")
    if st not in ("supported", "contradicted", "conflicting"):
        return False
    ev = (r.get("evidence") or [])[:4 if st == "conflicting" else 2]
    if not ev:
        return False
    for e in ev:
        e.setdefault("note", note)
    c["verdict"] = st
    c["confidence"] = "medium"
    c["evidence"] = (c.get("evidence") or []) + ev
    if st == "supported":
        c["suggestion"] = f"Evidence {note.lower()} confirms this figure."
    elif st == "conflicting":
        c["suggestion"] = (f"Sources disagree ({note.lower()}): one states "
                           f"{r.get('conflicting', 'a different value')} — "
                           "both camps shown; needs your call.")
    else:
        other = r.get("conflicting", "a different value")
        c["suggestion"] = f"Source states {other} ({note.lower()})."
    _tier_warn(c)
    return True


def _read_and_judge(cl, web, llm, _p, _cx, upgraded):
    """The source-led unit: search the cluster one query per figure (short,
    native-first), read up to
    three pages once, judge every number deterministically and every prose
    claim in ONE batched LLM call — with the verbatim-quote guard."""
    cs = cl["claims"]
    urls, seen, tried_qs = [], set(), []
    for q in _cluster_queries(cl, web):
        if web.budget.exhausted or _cx():
            break
        tried_qs.append(q)
        _p({"stage": "readsrc_q", "used": web.budget.used, "item": q[:80]})
        for r in (web.search_whitelisted(q) or []):
            href = r.get("href") or ""
            blob = ((r.get("body") or "") + " " + (r.get("title") or "")).strip()
            if href and href not in seen and web._mentions_entity(blob):
                seen.add(href)
                urls.append(href)
    urls = list(dict.fromkeys(urls))
    # Every claim in a VISITED cluster is honestly marked as attempted —
    # even when the cluster found no pages. Leaving the old
    # 'reserved for the sentence-level deep check' reason on them told users
    # a lie ('reserved' when nothing was ever reserved to run it).
    for c in cs:
        c["_readsrc"] = True
        c["_searched"] = True
        if c.get("_skip_reason") == "reserved for the sentence-level deep check":
            c.pop("_skip_reason", None)
        if tried_qs and not c.get("_web_queries"):
            c["_web_queries"] = tried_qs[:2]
    if not urls or _cx():
        return upgraded
    passages = _page_passages(web, cs, urls[:3])
    if not passages:
        return upgraded
    web.add_passage_pool(passages)  # read pages are pool material for EVERY
    # claim, not just this cluster's — the page proving one figure often
    # carries another claim's anecdote verbatim (pool judge settles it later)
    _p({"stage": "readsrc_pages", "used": web.budget.used,
        "pages": len({p["ref"] for p in passages}),
        "item": f"{len(passages)} passages from {len({p['ref'] for p in passages})} "
                f"pages, judging {len(cs)} claims"})
    pseudo = [{"href": p["ref"], "title": "", "body": p["text"]} for p in passages]
    for c in cs:
        if c["verdict"] == "unverified" and c["type"] in ("year", "amount", "pct",
                                                          "count"):
            if _apply_assessment(c, web._assess_number(c, pseudo,
                                                       query=" | ".join(tried_qs)),
                                 "found while reading a source page in full"):
                upgraded += 1
    prose = [c for c in cs if c["verdict"] == "unverified"]
    if llm.available and prose and not llm.exhausted and not _cx():
        for v in llm_mod.judge_pool(llm, prose[:22], passages):
            c = next((x for x in prose if x["id"] == v["id"]), None)
            if not c or c["verdict"] != "unverified":
                continue
            p = passages[v["ev"] - 1]
            c["verdict"] = v["verdict"]
            c["confidence"] = "low" if v["verdict"] == "supported" else "medium"
            c["evidence"] = (c.get("evidence") or []) + [{
                "kind": "web", "ref": p["ref"], "quote": corp.clip(p["text"], 320),
                "precision": "passage",
                "note": "LLM judged vs a full page read for this topic — "
                        "open source to confirm"}]
            c["suggestion"] = ((v.get("note") or "") +
                               " (full-page evidence for this claim's cluster)")
            if v["verdict"] == "contradicted":
                _demote_snippet_contradiction(
                    c, (v.get("note") or "A page passage says otherwise") +
                    " (full page read)")
            upgraded += 1
    return upgraded


def _pool_judge(claims, web, llm, _p, cancel=None):
    """The cross-proof step: re-judge every still-unverified claim against the
    WHOLE snippet pool of this run (one batched LLM call). Handles cases the
    literal matchers cannot: a Chinese snippet proving an English claim."""
    if not (llm and llm.available and not llm.exhausted and web._pool):
        return
    _cx = cancel or (lambda: False)
    todo = [c for c in claims if c["verdict"] == "unverified"
            and not (c.get("citation") and c["type"] != "url")
            and not c.get("fx_secondary")]
    if not todo:
        return
    ev, best = [], {}
    for r in web._pool:
        href = r.get("href") or ""
        body = ((r.get("body") or "") + " " + (r.get("title") or "")).strip()
        if not href or not body:
            continue
        # one entry per source, and if that source contributed both a search
        # snippet and a deep-read passage, judge the RICHER text
        if href not in best or len(body) > len(best[href]):
            best[href] = body
    ev = [{"ref": h, "text": t} for h, t in
          sorted(best.items(), key=lambda kv: -len(kv[1]))[:40]]
    if not ev:
        return
    _p({"stage": "pooljudge", "claims": len(todo), "snippets": len(ev),
        "used": web.budget.used, "item": f"{len(todo)} claims x {len(ev)} snippets"})
    found = 0
    for k in range(0, len(todo), 22):  # 22 claims/batch (matches llm.judge_pool cap)
        if llm.exhausted or _cx():
            break
        batch = todo[k:k + 22]
        for v in llm_mod.judge_pool(llm, batch, ev):
            c = next((x for x in batch if x["id"] == v["id"]), None)
            if not c or c["verdict"] != "unverified":
                continue
            e = ev[v["ev"] - 1]
            c["verdict"] = v["verdict"]
            c["confidence"] = "low" if v["verdict"] == "supported" else "medium"
            evd = {"kind": "web", "ref": e["ref"], "quote": corp.clip(e["text"], 320),
                   "precision": "snippet",
                   "note": "LLM judged vs this run's evidence pool — open source to confirm"}
            c["evidence"] = (c.get("evidence") or []) + [evd]
            c["suggestion"] = ((v.get("note") or "") +
                               " (evidence was fetched for another claim this run)")
            if v["verdict"] == "contradicted":
                _demote_snippet_contradiction(
                    c, (v.get("note") or "Evidence says otherwise") +
                    " (snippet pool)")
            found += 1
    _p({"stage": "pooljudge_done", "settled": found, "used": web.budget.used})


def _explain(claims, web, corpus=None):
    """No claim may end the run as a bare 'unverified': say WHY, and hand the
    user concrete queries to check by hand (evidence or honesty, never silence).

    The queries come from `queries.hand_queries`, which builds the shape the
    engine itself searches with (own subject · figure · rarest terms), instead
    of the first five non-stopwords in reading order prefixed with entity[0].
    """
    from .queries import hand_queries
    ents = web.raw_entities or []
    native = getattr(web, "native_for", None)
    for c in claims:
        if c["verdict"] not in ("unverified", "deferred_web") or c.get("_dup_of"):
            continue
        if str(c.get("_skip_reason", "")).startswith("citation"):
            continue  # keeps its own, clearer "this is a footnote" note
        if c.get("_partial") or c.get("_multi_entity"):
            # W1.4 already wrote the specific partial/multi-subject note; a
            # generic "unverified" sentence would erase it.
            continue
        engine_qs = [q for q in (c.get("_planned_queries") or [])[:2]]
        if not engine_qs:
            engine_qs = [q for q in (c.get("_web_queries") or []) if q][:2]
        if not engine_qs and c.get("_web_q"):
            engine_qs = [c["_web_q"]]
        qs = hand_queries(c, corpus=corpus, entities=ents, native=native,
                          extra=engine_qs, limit=4)
        if c.get("_searched"):
            why = "searched, but no snippet convincingly carried this value/wording"
        elif c.get("_skip_reason"):
            why = f"not searched this run ({c['_skip_reason']})"
        elif web.budget.exhausted:
            why = "not searched — web budget spent earlier in this run"
        else:
            why = "not web-searched this run"
        if c["type"] == "url":
            tail = " Open the link or search its page title by hand."
        else:
            _show = [q if q.startswith('"') else f'"{q}"' for q in qs[:2]]
            tail = (" Try by hand: " + "  |  ".join(_show)) if _show else ""
        c["suggestion"] = f"Unverified — {why}.{tail}"
        if qs:
            c["manual_checks"] = qs


def _dup_groups(claims):
    """Claims identical in type+value+sentence (repeated table rows, recurring
    boilerplate) share ONE search: first is the searcher, rest copy the result."""
    groups = {}
    for c in claims:
        key = (c["type"], c["raw"].strip().lower(),
               tp.normalize(c["sentence"]))
        groups.setdefault(key, []).append(c)
    return [g for g in groups.values() if len(g) > 1]


def _share_result(group):
    lead = group[0]
    for c in group[1:]:
        if lead["verdict"] != "unverified":
            c["verdict"] = lead["verdict"]
            c["confidence"] = lead["confidence"]
            if lead.get("evidence"):
                c["evidence"] = list(lead["evidence"])
            c["suggestion"] = (f"Same statement as {lead['id']} (checked once): "
                               f"{lead.get('suggestion', '')}")
        else:
            c["_searched"] = lead.get("_searched")
            c["_skip_reason"] = lead.get("_skip_reason")
            c["_web_queries"] = lead.get("_web_queries")
            c["_planned_queries"] = lead.get("_planned_queries")
            c["manual_checks"] = list(lead.get("manual_checks") or [])
        c["_dup_of"] = lead["id"]


def enrich(claims, web, llm, progress=None, context=None, cancel=None,
           corpus=None, semantic=False):
    _p = progress or (lambda e: None)
    _cx = cancel or (lambda: False)
    deep = bool(web and llm and llm.available)
    upgraded = 0
    groups = _dup_groups(claims) if web else []
    in_group = {id(c) for g in groups for c in g[1:]}
    if web:
        todo = [c for c in claims
                if c["verdict"] in ("unverified", "deferred_web")
                and id(c) not in in_group
                and not c.get("fx_secondary")]

        def _web_unit(c):
            if _cx():
                c["_skip_reason"] = "cancelled by user"
                return
            if not (c.get("citation") and c["type"] != "url"):
                _p({"stage": "web", "id": c["id"], "used": web.budget.used,
                    "budget": web.budget.max, "item": c["raw"][:70]})
            _apply_web(c, web, deep=deep)

        # claims are independent: parallel search cuts the token pass ~4x
        if todo:
            with ThreadPoolExecutor(max_workers=min(5, len(todo))) as ex:
                list(ex.map(_web_unit, todo))
        _p({"stage": "webpass_done", "used": web.budget.used,
            "budget": web.budget.max})
    # ---- source-led deep pass: cluster related claims, READ whole pages,
    # judge numbers deterministically and prose in one batch per cluster.
    # (The old flow — per-claim planned queries + a 20-snippet LLM confetti
    # judge — was slow AND weak: the pages hold the facts, the snippets
    # barely quote them, and the free judge waved everything 'unverified'.)
    if deep:
        cand = [c for c in claims if c["verdict"] == "unverified"
                and id(c) not in in_group
                and not c.get("fx_secondary")
                and not (c.get("citation") and c["type"] != "url")]
        cand.sort(key=lambda c: (0 if c.get("origin") == "llm" else 1, c["id"]))
        # rule 9: budgets scale, caps are sanity-only. Every claim is
        # clustered and the VISIT LOOP is bounded by the search budget itself
        # (breaks on exhausted/cancel) — a static cluster count once left 110
        # of 159 paid-for searches idle while claims went unattempted.
        cand = cand[:500]  # memory/time wall for huge docs, nothing more
        clusters = _source_clusters(cand, web, max_clusters=max(len(cand), 1))
        _p({"stage": "readsrc", "done": 0, "batches": len(clusters),
            "item": f"reading sources for {min(len(cand), sum(len(c['claims']) for c in clusters))} claims in {len(clusters)} topic clusters",
            "used": web.budget.used, "budget": web.budget.max})
        for n, cl in enumerate(clusters, 1):
            if _cx() or web.budget.exhausted:
                break
            _p({"stage": "readsrc", "done": n, "batches": len(clusters),
                "used": web.budget.used, "budget": web.budget.max,
                "item": f"cluster {n}/{len(clusters)}: {len(cl['claims'])} claims "
                        f"({' + '.join(sorted(cl['ents'])[:3]) or 'mixed topic'})"})
            upgraded = _read_and_judge(cl, web, llm, _p, _cx, upgraded)
        for c in cand:
            if (c.get("_skip_reason")
                    == "reserved for the sentence-level deep check"):
                # the deep pass never reserved anything for it: clear the lie;
                # _explain then tells the true why (budget spent / cancelled)
                c.pop("_skip_reason", None)
        # coverage guarantee: numeric claims never searched at all (backend
        # degraded/budget) get their keyword ladder NOW — a fact may be
        # unverified, but it must never be silently skipped
        left = [c for c in claims
                if c["verdict"] == "unverified" and not c.get("_searched")
                and c["type"] in ("year", "amount", "pct", "count")
                and not c.get("_dup_of") and not c.get("fx_secondary")
                and not (c.get("citation") and c["type"] != "url")
                and not web.budget.exhausted]
        if left and _cx():
            for c in left:
                c["_skip_reason"] = "cancelled by user"
        elif left:
            def _retry(c):
                _p({"stage": "web", "id": c["id"], "used": web.budget.used,
                    "item": c["raw"][:70]})
                _apply_web(c, web, deep=False)

            with ThreadPoolExecutor(max_workers=min(5, len(left))) as ex:
                list(ex.map(_retry, left))
    if web:
        _reuse_pass(claims, web, _p)
        _pool_judge(claims, web, llm, _p, cancel=_cx)
        # W1.4 runs AFTER the pool judge on purpose: the pool judge may surface
        # a conflicting source, and a support-first pass would hide it. Only
        # claims still unverified are eligible; the NLI contract is support-only.
        if semantic and llm and llm.available and not _cx():
            from . import nli
            nli.judge(llm, claims, corpus=corpus, web=web, progress=_p)
        for g in groups:
            _share_result(g)
        _explain(claims, web, corpus=corpus)
    return claims, upgraded
