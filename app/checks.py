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


_MONTHS = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "spring", "summer", "autumn", "winter",
}
_DOC_TITLE_WORDS = (
    "collection", "essay", "appendix", "case study", "biography",
    "history", "evolution", "draft", "notes", "report", "chapter",
)
_GENERIC_ENTS = {"chinese", "english", "anniversary", "company", "group"}


def _timeline_entity(e):
    """A month, a document title or a generic adjective is not a subject."""
    n = tp.normalize(e)
    if not n or n in _MONTHS or n in _GENERIC_ENTS:
        return False
    if any(w in n for w in _DOC_TITLE_WORDS):
        return False
    if len(n) < 3 and not CJK_entity(e):
        return False
    return True


def entity_timelines(paragraphs, entities):
    """Per-entity milestone table: {entity: {event: {year: [sentences]}}}.

    Match the entity in the SENTENCE, not merely the paragraph: a paragraph
    that mentions Kingsoft Cloud must not file every neighbouring sentence
    under Kingsoft. For a multi-word Latin name, require the full name; and
    skip a sentence for the shorter entity when a longer sibling is present
    ('Kingsoft Cloud' is not 'Kingsoft').
    """
    norms = [(e, tp.normalize(e)) for e in entities if _timeline_entity(e)]
    timelines = {}
    for e, en in norms:
        siblings = [n for (_o, n) in norms
                    if n != en and n.startswith(en + " ")]
        tl = {}
        for p in paragraphs:
            for sent in tp.sentences(p):
                sn = tp.normalize(sent)
                if en not in sn:
                    continue
                if any(sib in sn for sib in siblings):
                    continue
                ys = tp.years_in(sent)
                if not ys:
                    continue
                ev = tp.event_of(sn)
                if not ev:
                    continue
                for y in ys:
                    tl.setdefault(ev, {}).setdefault(y, [])
                    if sent not in tl[ev][y]:
                        tl[ev][y].append(sent)
        timelines[e] = tl
    return timelines


_VERSION_RX = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,20})\s*"
    r"([0-9]+(?:\.[0-9]+)?)(?![0-9])")
_VERSION_SKIP = set(tp.STOP) | {
    "pp", "p", "vol", "no", "room", "floor", "page", "chapter", "figure",
    "table", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december", "spring",
    "summer", "autumn", "winter",
}


def _version_key(sentence):
    """Product/version token in a sentence ('WPS 97', 'Office 2000').

    Two launch years for DIFFERENT versions are not a conflict. Dates and
    locators ('September 1989', 'room 501', 'page 12') are skipped so this
    only splits on product-like tokens.
    """
    for m in _VERSION_RX.finditer(sentence or ""):
        word = m.group(1).lower()
        if word in _VERSION_SKIP:
            continue
        return f"{word} {m.group(2)}"
    return ""


def _timeline_sim(a, b):
    ta = {t for t in tp.tokens(a) if t not in tp.STOP and len(t) > 1}
    tb = {t for t in tp.tokens(b) if t not in tp.STOP and len(t) > 1}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _timeline_clusters(by_year):
    """Years whose first sentences describe the same event (Jaccard >= 0.30).

    Two different subsidiaries' IPOs share 'listed' and 'Kingsoft' but little
    else; two dates for the SAME milestone share most of the sentence. Only a
    connected cluster of two or more years is a candidate conflict.
    """
    years = sorted(by_year)
    parent = {y: y for y in years}

    def find(y):
        while parent[y] != y:
            parent[y] = parent[parent[y]]
            y = parent[y]
        return y

    for i, y1 in enumerate(years):
        for y2 in years[i + 1:]:
            if _timeline_sim(by_year[y1][0], by_year[y2][0]) >= 0.30:
                ra, rb = find(y1), find(y2)
                if ra != rb:
                    parent[rb] = ra
    groups = {}
    for y in years:
        groups.setdefault(find(y), []).append(y)
    return [sorted(g) for g in groups.values() if len(g) >= 2]


def timeline_conflicts(timelines):
    """Flag entities whose SAME milestone carries different years (F3b).

    Precision-first: sentences are matched to the entity (and not to a
    longer sibling), split by product/version, date-range endpoints are
    ignored, and only years whose sentences describe the same event
    (Jaccard >= 0.30) are compared. WPS 1.0 (1989), WPS 97 (1997) and
    WPS 2000 (2000) are three launches, not one contradictory launch.
    """
    findings = []
    n = 0
    for ent, tl in timelines.items():
        for ev, by_year in tl.items():
            groups = {}
            for y, sents in by_year.items():
                for s in sents:
                    groups.setdefault(_version_key(s), {}).setdefault(y, []).append(s)
            for ver, g in groups.items():
                clean = {
                    y: sents for y, sents in g.items()
                    if not _in_date_range({"sentence": sents[0], "raw": str(y)})
                }
                for years in _timeline_clusters(clean):
                    n += 1
                    detail = "; ".join(
                        f"{y}: “{clean[y][0][:80]}”" for y in years)
                    ev_label = f"{ev} ({ver})" if ver else ev
                    findings.append({
                        "id": f"t{n:03d}", "type": "timeline",
                        "verdict": "internal_conflict",
                        "raw": f"{ent} {ev_label} {years}", "confidence": "medium",
                        "para": None, "span": [0, 0], "sentence": detail,
                        "evidence": [],
                        "suggestion": (f"Timeline conflict: {ent} is dated to "
                                       f"{', '.join(map(str, years))} for the same "
                                       f"milestone ({ev_label}); at most one year is right."),
                        "note": detail,
                    })
    return findings


def _pct_complement(claim):
    """What a percentage is a percentage OF ('20% of the studio's shares' ->
    {share, studio}; '80% of the debt' -> {debt}). Two pct claims measure the
    SAME quantity only if these overlap — 'buy 20% of shares' and '22.89% of
    the voting rights' and '80% of the debt' are three different facts."""
    return _pct_base(claim)


# Metric families: two figures in the same paragraph are only a restatement of
# the same fact when they measure the SAME thing. Revenue vs gross profit vs
# net profit are not a contradiction; neither are shares vs voting rights.
_METRIC_GROUPS = (
    ("revenue", ("营业收入", "营收", "收入", "销售额", "营业额",
                 "revenue", "sales", "turnover")),
    ("gross_profit", ("毛利率", "毛利", "gross profit", "gross margin")),
    ("profit", ("净利润", "净利", "利润", "亏损", "盈利",
                "net profit", "net income", "profit", "earnings", "loss")),
    ("valuation", ("估值", "市值", "valuation", "market cap")),
    ("funding", ("融资额", "融资", "募资", "funding", "financing", "raised")),
    ("gmv", ("交易额", "流水", "gmv", "transaction volume")),
    ("bonus", ("奖金", "分红", "bonus")),
    ("target", ("目标", "指标", "target")),
    ("reserve", ("储备", "现金储备", "reserve")),
    ("cost", ("研发投入", "成本", "支出", "投入", "费用",
              "cost", "expense", "spending")),
    ("ownership", ("股权", "股份", "持股", "shares", "stake", "equity")),
    ("voting", ("投票权", "表决权", "voting rights", "voting power")),
)

_PCT_BASES = (
    ("shares", ("股权", "股份", "持股", "shares", "share", "stake", "equity")),
    ("voting", ("投票权", "表决权", "voting rights")),
    ("debt", ("债务", "负债", "debt")),
    ("revenue", ("收入", "营收", "营业额", "revenue", "sales")),
    ("market", ("市场份额", "市场占有率", "份额", "market share")),
)


def _metric(sentence, raw):
    """The metric word closest to this figure (revenue/profit/ownership/...).

    Returns "" when no known metric is nearby, so the caller keeps the old
    conservative behaviour instead of guessing. Longer phrases win over their
    substrings ('gross profit' is not just 'profit').
    """
    s, r = sentence or "", str(raw or "")
    i = s.find(r)
    if i < 0:
        return ""
    lo, hi = max(0, i - 40), i + len(r) + 40
    window = s[lo:hi].lower()
    matches = []
    for group, words in _METRIC_GROUPS:
        for w in words:
            j = window.find(w)
            while j >= 0:
                matches.append((lo + j, lo + j + len(w), group))
                j = window.find(w, j + 1)
    # Drop a match fully contained in a longer one: 'profit' inside
    # 'gross profit' must not steal the group from the longer phrase.
    matches.sort(key=lambda m: m[1] - m[0], reverse=True)
    kept = []
    for m in matches:
        if any(k[0] <= m[0] and m[1] <= k[1] for k in kept):
            continue
        kept.append(m)
    if not kept:
        return ""
    best = min(kept, key=lambda m: abs(m[0] - i))
    return best[2]


def _pct_base(claim):
    """What a percentage is a percentage OF, as a small family label.

    Chinese is handled explicitly (`20%的股权` vs `22.89%的投票权` are different
    facts); English falls back to the existing `of/from/in/to` tokens. The raw
    string is located first so a number inside a year ('2020') cannot be
    mistaken for the percentage.
    """
    s = claim.get("sentence") or ""
    raw = (claim.get("raw") or "").strip()
    pos = s.find(raw)
    if pos >= 0:
        end = pos + len(raw)
    else:
        stem = raw.rstrip("%").strip()
        if not stem:
            return set()
        m0 = re.search(r"(?<![\d.])" + re.escape(stem) + r"(?![\d.])\s*%?", s)
        if not m0:
            return set()
        end = m0.end()
    tail = s[end:end + 40]
    m = re.match(r"\s*(?:的)?\s*"
                 r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z\s'\-]{0,24})", tail)
    if not m:
        return set()
    frag = m.group(1)
    low = frag.lower()
    for group, words in _PCT_BASES:
        if any(w in low for w in words):
            return {group}
    words = [t for t in tp.tokens(frag) if t not in tp.STOP][:4]
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


_UNIT_WORDS = (
    "研发一部", "研发部", "部门", "事业部", "子公司", "分公司", "团队",
    "业务线", "分部", "工作室", "项目组",
    "unit", "division", "department", "team", "subsidiary",
)

# Bonus amounts need a specific shared subject: two different people's bonuses
# share only the generic words below and must not be called a contradiction.
_BONUS_GENERIC = {
    "奖金", "年终奖", "分红", "万元", "亿元", "美元", "万美元", "人民币",
    "年", "团队", "公司", "员工", "他", "她", "的奖", "金仅",
}


def _scope(sentence, raw):
    """Company-level vs unit-level: a department's revenue is not the group's.

    Only the presence of a unit word near the figure is recorded; a company
    sentence has no unit word, so comparing a unit figure with a group figure
    is blocked while two group figures still compare.
    """
    s, r = sentence or "", str(raw or "")
    i = s.find(r)
    if i < 0:
        return ""
    window = s[max(0, i - 40):i + len(r) + 40].lower()
    return "unit" if any(w in window for w in _UNIT_WORDS) else ""


def _in_date_range(claim):
    """True when this year is an endpoint of a range ('2017年12月至2018年1月').

    A range endpoint is not a standalone date: comparing the 2018 endpoint with
    a sentence that says 2017 is not a contradiction, it is the same event.
    """
    s = claim.get("sentence") or ""
    raw = (claim.get("raw") or "").strip()
    if not raw.isdigit():
        return False
    pat = r"(?<!\d)" + re.escape(raw) + r"(?!\d)"
    for m in re.finditer(pat, s):
        before = s[max(0, m.start() - 10):m.start()]
        after = s[m.end():m.end() + 10]
        if (re.search(r"(?:至|到|—|–|-|~|to)\s*$", before, re.I)
                or re.match(r"\s*(?:至|到|—|–|-|~|to|and)\b", after, re.I)):
            return True
    return False


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
            # "cost 3.7亿" in adjacent sentences are different facts. The
            # metric word closest to each figure must agree when both are
            # known; an unknown metric keeps the old conservative fallback.
            ma = _metric(a["sentence"], a["raw"])
            mb = _metric(b["sentence"], b["raw"])
            if ma and mb and ma != mb:
                return False
            if _scope(a["sentence"], a["raw"]) != _scope(b["sentence"], b["raw"]):
                return False  # department vs group, not the same fact
            if ma == "bonus" and mb == "bonus":
                ca = {t for t in context(a) if t not in _BONUS_GENERIC}
                cb = {t for t in context(b) if t not in _BONUS_GENERIC}
                if len(ca & cb) < 2:
                    return False  # different people's bonuses
            if not (_near(a["sentence"], a["raw"])
                    & _near(b["sentence"], b["raw"])):
                return False
        if a["type"] == "amount":
            if not a["currency"] or not b["currency"] or a["currency"] != b["currency"]:
                return False
        if a["type"] == "year":
            if _in_date_range(a) or _in_date_range(b):
                return False
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
