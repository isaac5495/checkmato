import re

from . import textproc as tp


def name_drift(paragraphs, alias=None, threshold=0.5):
    """Same (or near-identical) statement attributed to two people whose names
    are not aliases (e.g. a person silently renamed 老王→小王 across a draft).
    Flagged for review, not judged — legitimate quotes can look similar."""
    from . import textproc as tp2
    mentions = []
    for pidx, p in enumerate(paragraphs):
        for name, sent in tp2.person_mentions(p):
            mentions.append((pidx, name, sent))
    findings, seen = [], set()
    n = 0
    for i in range(len(mentions)):
        for j in range(i + 1, len(mentions)):
            pa, na, sa = mentions[i]
            pb, nb, sb = mentions[j]
            if pa == pb or not tp2.names_conflict(na, nb):
                continue
            if alias and alias.are_aliases(na, nb):
                continue
            ta = {t for t in tp2.tokens(sa) if t not in tp2.STOP}
            tb = {t for t in tp2.tokens(sb) if t not in tp2.STOP}
            if tp2.jaccard(ta, tb) < threshold:
                continue
            key = (na, nb) if na < nb else (nb, na)
            if key in seen:
                continue
            seen.add(key)
            n += 1
            findings.append({
                "id": f"d{n:03d}", "type": "name_drift", "verdict": "needs_fix",
                "raw": f"{na} / {nb}", "confidence": "medium",
                "para": None, "span": [0, 0],
                "evidence": [],
                "sentence": f"¶{pa + 1}: {sa}\n¶{pb + 1}: {sb}",
                "note": f"Said by both '{na}' (¶{pa + 1}) and '{nb}' (¶{pb + 1})",
                "suggestion": (f"The same statement is attributed to '{na}' and "
                               f"'{nb}' — one person renamed, or a real "
                               f"disagreement to resolve?"),
            })
    return findings


def structural_findings(doc, claims):
    """Zero-LLM integrity checks over the document itself."""
    findings = []
    n = 0

    def add(ctype, raw, note, para=None):
        nonlocal n
        n += 1
        findings.append({
            "id": f"s{n:03d}", "type": ctype, "verdict": "structure",
            "raw": raw, "note": note, "sentence": raw, "para": para,
            "evidence": [], "suggestion": note,
        })

    refs = doc["footnote_refs"]
    defs = set(doc["footnote_defs"])
    for r in refs:
        if r not in defs:
            add("footnote_orphan_ref", f"[^{r}]",
                f"Footnote reference [^{r}] has no definition.")
    for d in defs:
        if d not in refs:
            add("footnote_orphan_def", f"[^{d}]",
                f"Footnote definition [^{d}] is never referenced in the body.")

    seen_urls = set()
    for c in claims:
        if c["type"] == "url" and c["raw"] not in seen_urls:
            seen_urls.add(c["raw"])
    # placeholder claims are reported through the claim pipeline, not here.
    return findings


def _match_forms(entity):
    """Forms a sentence may use to refer to an entity: full name or its leading
    word (so 'Nimbus Cloud' also matches a sentence that just says 'Nimbus')."""
    parts = entity.split()
    if len(parts) > 1:
        return [tp.normalize(entity), tp.normalize(parts[0])]
    if CJK_entity(entity):
        return [tp.normalize(entity)]
    return [tp.normalize(entity)]


def CJK_entity(entity):
    return any("一" <= ch <= "鿿" for ch in entity)


def entity_timelines(paragraphs, entities):
    """Per-entity milestone table: {entity: {event: {year: [sentences]}}}."""
    timelines = {}
    for e in entities:
        forms = _match_forms(e)
        tl = {}
        for p in paragraphs:
            pn = tp.normalize(p)
            if not any(f in pn for f in forms):
                continue
            for sent in tp.sentences(p):
                ys = tp.years_in(sent)
                if not ys:
                    continue
                ev = tp.event_of(tp.normalize(sent))
                if not ev:
                    continue
                for y in ys:
                    tl.setdefault(ev, {}).setdefault(y, [])
                    if sent not in tl[ev][y]:
                        tl[ev][y].append(sent)
        timelines[e] = tl
    return timelines


def timeline_conflicts(timelines):
    """Flag entities whose SAME milestone carries different years (F3b)."""
    findings = []
    n = 0
    for ent, tl in timelines.items():
        for ev, by_year in tl.items():
            if len(by_year) < 2:
                continue
            n += 1
            years = sorted(by_year)
            detail = "; ".join(f"{y}: “{by_year[y][0][:80]}”" for y in years)
            findings.append({
                "id": f"t{n:03d}", "type": "timeline", "verdict": "internal_conflict",
                "raw": f"{ent} {ev} {years}", "confidence": "medium",
                "para": None, "span": [0, 0], "sentence": detail,
                "evidence": [],
                "suggestion": (f"Timeline conflict: {ent} is dated to "
                               f"{', '.join(map(str, years))} for the same "
                               f"milestone ({ev}); at most one year is right."),
                "note": detail,
            })
    return findings


def _pct_complement(claim):
    """What a percentage is a percentage OF ('20% of the studio's shares' ->
    {share, studio}; '80% of the debt' -> {debt}). Two pct claims measure the
    SAME quantity only if these overlap — 'buy 20% of shares' and '22.89% of
    the voting rights' and '80% of the debt' are three different facts."""
    num = re.escape((claim.get("raw") or "").strip().rstrip("%").strip())
    m = re.search(num + r"\s*%?\s+(?:of|from|in|to)\s+(?:the\s+)?([A-Za-z][A-Za-z\s']{1,40})",
                  claim.get("sentence") or "")
    if not m:
        return set()
    words = [t for t in tp.tokens(m.group(1)) if t not in tp.STOP][:4]
    return {tp.stem(w) for w in words}


_MEASURE = re.compile("(" + "|".join([
    "\u5c81", "\u540d", "\u4eba", "\u5957", "\u884c", "\u90e8", "\u53f0",
    "\u4e2a", "\u5bb6", "\u4e07\u5143", "\u4ebf\u5143", "\u4e07", "\u4ebf",
    "%"]) + ")")


def _measure(raw):
    """The unit a count is expressed in (age vs staff vs copies vs lines).

    Two numbers in different units are different metrics, not a conflict.
    """
    m = _MEASURE.search(str(raw or ""))
    return m.group(1) if m else ""


def _near(sentence, raw):
    """Content words around a number, excluding names and pure digits."""
    i = (sentence or "").find(str(raw or ""))
    if i < 0:
        return set()
    window = sentence[max(0, i - 14): i + len(str(raw)) + 10]
    return {t for t in tp.tokens(window)
            if len(t) > 1 and not t.isdigit() and t not in tp.STOP
            and t not in tp.name_tokens(sentence)}


def internal_conflicts(claims):
    """Same-kind values stated differently for the SAME fact (e.g. founding
    year given twice as 1988 and 1993). Deliberately conservative:
    - shared context is counted WITHOUT entity/name words (two sentences about
      'Qiu Bojun' share his name, that is not the same FACT);
    - amounts conflict only in the SAME currency (US$483m vs RMB 200m are two
      different figures, not a contradiction);
    - years conflict only for the SAME milestone (event anchor must match);
    - percentages conflict only about the same base quantity ('of the shares'
      vs 'of the debt' are different facts, even near each other);
    - no transitive chaining: every member must directly share >=2 context
      words with the ANCHOR claim, or a 2007 price chains to a 2014 price."""
    num = [c for c in claims if c["type"] in ("count", "pct", "amount", "year")]

    def context(c):
        return set(tp.rare_raw_tokens(c["sentence"])) - tp.name_tokens(c["sentence"])

    def links(a, b, anchor_ctx):
        if a["type"] != b["type"] or a["sentence"] == b["sentence"]:
            return False
        # identifiers (room 501, WPS 1.0, floor 12) are labels, not quantities:
        # an age and a room number can never "contradict"
        if tp.IDF_LABEL.search(a["raw"]) or tp.IDF_LABEL.search(b["raw"]):
            return False
        if tp.values_equal(a["value"], b["value"], kind=a["type"]):
            return False
        # Local restatements only: a 14,000-word study repeats metrics across
        # chapters and business lines; those are different facts, not a
        # contradiction. Counts must also share a unit (age vs staff vs lines).
        if a["type"] in ("count", "amount", "pct"):
            pa, pb = a.get("para"), b.get("para")
            if pa is not None and pb is not None and abs(pa - pb) > 3:
                return False
        if a["type"] == "count" and _measure(a["raw"]) != _measure(b["raw"]):
            return False
        if a["type"] in ("count", "amount", "pct"):
            # Same metric, not merely the same currency: "revenue 2亿" and
            # "cost 3.7亿" in adjacent sentences are different facts.
            if not (_near(a["sentence"], a["raw"])
                    & _near(b["sentence"], b["raw"])):
                return False
        if a["type"] == "amount":
            if not a["currency"] or not b["currency"] or a["currency"] != b["currency"]:
                return False
        if a["type"] == "year":
            ea = tp.event_of(tp.normalize(a["sentence"]))
            eb = tp.event_of(tp.normalize(b["sentence"]))
            if ea is None or ea != eb:
                return False
        if a["type"] == "pct":
            # percentages only conflict about the SAME base quantity
            ca, cb = _pct_complement(a), _pct_complement(b)
            if ca and cb and not (ca & cb):
                return False
        ya, yb = set(tp.years_in(a["sentence"])), set(tp.years_in(b["sentence"]))
        if ya and yb and not (ya & yb):
            return False  # TIME SERIES: different years, different values is normal
        need = 3 if a["type"] in ("year", "count") else 2
        return len(context(b) & anchor_ctx) >= need

    results, used = [], [False] * len(num)
    for i, a in enumerate(num):
        if used[i]:
            continue
        ctx = context(a)
        members = [j for j in range(i + 1, len(num)) if links(a, num[j], ctx)]
        if not members:
            continue
        used[i] = True
        for j in members:
            used[j] = True
        cs = [a] + [num[j] for j in members]
        parts = ", ".join(f"{c['raw']} (¶{c['para'] + 1})" for c in cs)
        comp = sorted({w for c in cs for w in _pct_complement(c)})
        subj = (", ".join(comp) if comp
                else ", ".join(sorted(ctx, key=len, reverse=True)[:3]) or "same kind")
        results.append((cs, f"Inconsistent values stated in the document for the "
                            f"same subject ({subj}): {parts}"))
    return results
