"""Hand-search queries for the reader, built the way a person searches.

The engine's own ladders (`enrich._cluster_queries`, `web.verify_number`) are
short, entity-anchored and figure-first (rule 7). What the reader used to get in
an `unverified` row was not: the first five non-stopwords of the sentence in
READING order, prefixed with the document's FIRST entity — "acme systems
reported revenue 125" — or, in a library run, the instruction "Find the source
for: 12.2万行". Neither can be pasted into a search box.

A usable query carries the FACTS of the sentence, not two random words:

1. the subject — the name in THIS sentence (a draft about one company still
   writes sentences about its founder), or the document subject when the
   sentence opens with a pronoun ("He was determined to…");
2. the figure as a page writes it — "US$4.2 billion", "1984", "120 rooms" —
   never "125000000";
3. every distinctive content word the sentence states — names, verbs, objects:
   "Zhang Xuanlong Qiu Bojun funding write word processor", not
   "Zhang Xuanlong Qiu". Rarity in the library decides which words survive a
   long sentence; reading order decides how they read;
4. for a quote, the verbatim span itself, quoted.

Deterministic: no model, no network, no randomness. Ranking metadata only —
these strings are advice for the reader, never evidence.

Honest limit: without a POS tagger this cannot know that "determined" is the
author's framing rather than a fact. A curated lexicon handles the common
evaluative/reporting verbs; anything beyond that needs a model, which this
module deliberately does not call.
"""
import re

from . import textproc as tp

NUMERIC = ("year", "amount", "pct", "count")

# Words that make a search worse. STOP already covers connectives; this is the
# report-voice layer that survives tokenisation because it is the sentence's
# only content: "reported", "announced", "determined", "also".
QUERY_NOISE = {
    "said", "says", "say", "report", "reports", "reported", "reporting",
    "accord", "according", "state", "states", "stated", "note", "notes",
    "noted", "announce", "announces", "announced", "reveal", "reveals",
    "revealed", "show", "shows", "showed", "shown", "claim", "claims",
    "claimed", "add", "adds", "added", "explain", "explains", "explained",
    "propose", "proposes", "proposed", "proposal",
    "however", "moreover", "furthermore", "therefore", "thus", "additionally",
    "meanwhile", "overall", "currently", "recently", "respectively",
    "including", "include", "includes", "based", "approximately", "almost",
    "nearly", "roughly", "around", "various", "several", "certain",
    "last", "next", "past", "today", "now", "later", "soon", "current",
    "prior", "previous",
    # evaluative / mental-state verbs: the author's framing, not a fact
    "determine", "determines", "determined", "decide", "decides", "decided",
    "plan", "plans", "planned", "intend", "intends", "intended",
    "hope", "hopes", "hoped", "want", "wants", "wanted", "wish", "wished",
    "believe", "believes", "believed", "feel", "feels", "felt",
    "think", "thinks", "thought", "realize", "realizes", "realized",
    "try", "tries", "tried", "struggle", "struggles", "struggled",
    "manage", "manages", "managed", "appear", "appears", "appeared",
    # filler predicates: an entity + these is not a query ("Foo happened")
    "happened", "happens", "occurred", "occurs", "occurring", "became",
    "becomes", "seems", "seemed", "remains", "remained", "exists", "existed",
    "times",
    # pronouns: the reader's query names the subject, not "we"
    "we", "our", "us", "you", "your", "i", "my", "me", "him", "them", "their",
    "表示", "指出", "显示", "报道", "据悉", "目前", "此外", "因此", "同时",
    "以及", "但是", "然而", "并且", "已经", "进行", "相关", "方面", "情况",
    "认为", "一個", "一个",
}

_TERM_RX = re.compile(r"[A-Za-z][A-Za-z0-9'\u2019\-]*|[\u4e00-\u9fff]{2,}")
_CJK_RX = re.compile(r"[\u4e00-\u9fff]")
_QUOTED = re.compile(r"\"[^\"]{4,}\"|\u201c[^\u201d]{4,}\u201d|\u300c[^\u300d]{4,}\u300d")
_CLAUSE = re.compile(r"[;,]|\s+(?:and|but|while|yet)\s+", re.I)
# A sentence that opens with a pronoun is about the paragraph subject, not about
# the last name it happens to mention.
_PRONOMINAL = re.compile(
    r"^\s*(?:even so,?\s*|and\s+|but\s+)?"
    r"(?:he|she|it|they|his|her|its|their|the company|the firm|the group)\b",
    re.I)


def _norm(s):
    return tp.normalize(s or "")


def _has_cjk(s):
    return bool(_CJK_RX.search(s or ""))


def _anchors(claim, entities, native):
    """(primary, alternates) — the subject THIS claim is about.

    Order of evidence: a leading pronoun means the document subject (the
    sentence does not name it); otherwise the first proper name IN the sentence;
    otherwise the document subject. A numeric claim takes the subject's
    native-script form, because digits travel and translated names do not.
    """
    sent = claim.get("sentence") or ""
    ents = [str(e).strip() for e in (entities or []) if str(e).strip()]
    nat = ([str(x).strip() for x in native(claim) if str(x).strip()]
           if callable(native) else [str(x).strip() for x in (native or [])
                                     if str(x).strip()])
    doc_subj = nat[0] if nat else (ents[0] if ents else "")
    names = [str(e).strip() for e in tp.detect_entities([sent]) if str(e).strip()]
    # upgrade a detected short form to the document's full entity when it is a
    # substring ("Cai Wu Wei" -> "Cai Wu Wei Hotel")
    for i, nm in enumerate(names):
        full = [e for e in ents
                if _norm(nm) and _norm(nm) in _norm(e) and _norm(e) in _norm(sent)]
        if full:
            names[i] = max(full, key=len)
    if _PRONOMINAL.match(sent) and doc_subj:
        head = doc_subj
    elif names:
        head = names[0]
    else:
        head = doc_subj
    if claim.get("type") in NUMERIC and nat:
        head = nat[0]                       # 金山软件 1984, not Kingsoft 1984
    if not head and ents:
        head = ents[0]
    seen = {_norm(head)}
    pcore = tp.tokens(head)
    pool = nat + ents + names
    # an alternate anchor must be a VARIANT of the subject (native script or a
    # shared-token alias), never a different entity from the sentence
    alt = [e for e in pool if _norm(e) not in seen
           and (_has_cjk(e) or (pcore and tp.tokens(e) & pcore))]
    return ([head] if head else []), alt[:2]


def _figure(claim):
    """The figure as it appears on a real page, not its numeric value."""
    typ = claim.get("type")
    raw = (claim.get("raw") or "").strip()
    val = claim.get("value")
    digits = ""
    try:
        if val is not None:
            f = float(val)
            digits = str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        digits = ""
    if typ == "amount":
        return raw if any(c.isdigit() for c in raw) else digits
    if typ in ("year", "pct", "count"):
        if raw and any(c.isdigit() for c in raw) and len(raw) <= 24:
            return raw
        return digits
    # prose: a stated year is the cheapest anchor a reader would add
    m = re.search(r"\b(?:19|20)\d{2}\b", claim.get("sentence") or "")
    return m.group() if m else ""


def _df(corpus, word):
    """Library frequency of a term; 0 = absent from the library."""
    if corpus is None or not getattr(corpus, "df", None):
        return 0
    return sum(corpus.df.get(t, 0) for t in tp.tokens(word))


def _rank_key(corpus, word, i):
    """Rarest first. An ABSENT capitalised word is probably a name the library
    does not use (useful: 'Bergen'); an absent lowercase word is more likely a
    different inflection of something already indexed (not useful)."""
    df = _df(corpus, word)
    if df == 0:
        return (0 if any(ch.isupper() for ch in word) else 10 ** 6, i)
    return (df, i)


def _candidates(claim, exclude):
    """[(char_offset, word)] — content words outside quotes, in reading order."""
    text = _QUOTED.sub(" ", claim.get("sentence") or "")
    seen, out = set(), []
    for m in _TERM_RX.finditer(text):
        w = m.group().strip("'\u2019-")
        lw = w.lower()
        if not lw or lw.isdigit() or lw in seen or lw in QUERY_NOISE:
            continue
        core = tp.tokens(lw)
        if not core or core & exclude or core <= tp.STOP:
            continue
        seen.add(lw)
        out.append((m.start(), w if any(ch.isupper() for ch in w) else lw))
    return out


def _facts(claim, exclude, corpus, limit=8):
    """Every distinctive content word the sentence states, in READING order.

    Rarity selects which words survive a long sentence; it never reorders them,
    because "Qiu Bojun funding write word processor" is a query and "write
    funding processor Bojun Qiu" is word soup.
    """
    cand = _candidates(claim, exclude)
    ranked = sorted(enumerate(cand), key=lambda p: _rank_key(corpus, p[1][1], p[0]))
    keep = {i for i, _p in ranked[:limit]}
    return [w for i, (_at, w) in enumerate(cand) if i in keep]


def _near_facts(claim, figure, exclude, limit=2):
    """The words nearest the figure, inside its own clause.

    A numeric claim is one fact, not the whole sentence: "…employed 400 people
    by 2015, and the founder said …" must not hand the reader the quote's words
    as keywords for 2015.
    """
    text = _QUOTED.sub(" ", claim.get("sentence") or "")
    pos = _norm(text).find(_norm(figure)) if figure else -1
    if pos >= 0:
        # char offsets differ after normalisation; use the raw figure offset
        pos = text.find(figure)
    if pos >= 0:
        cut = [m for m in _CLAUSE.finditer(text)]
        lo, hi = 0, len(text)
        for m in cut:
            if m.end() <= pos:
                lo = m.end()
            elif m.start() >= pos:
                hi = m.start()
                break
        text = text[lo:hi]
    cand = _candidates({"sentence": text}, exclude)
    if pos >= 0 and cand:
        base = pos - lo
        nearest = sorted(cand, key=lambda p: abs(p[0] - base))[:limit]
        keep_at = {p[0] for p in nearest}
        return [w for at, w in cand if at in keep_at]
    return [w for _at, w in cand[:limit]]


def _quote_core(text, n=90):
    """A quotable span: cut on a word boundary, never mid-token."""
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t.strip(' .,;:!?')
    cut = t[:n].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut.strip(' .,;:!?')


def hand_queries(claim, corpus=None, entities=None, native=None, extra=None,
                 limit=4):
    """Up to `limit` pasteable queries for one claim. Deterministic."""
    typ = claim.get("type") or "sentence"
    sent = claim.get("sentence") or ""
    raw = (claim.get("raw") or "").strip()
    prim, alt = _anchors(claim, entities, native)
    head = prim[0] if prim else ""
    figure = _figure(claim)
    raw_has_digit = any(c.isdigit() for c in raw)

    exclude = set()
    for a in prim + alt:
        exclude |= tp.tokens(a)
    if figure and raw_has_digit:
        exclude |= tp.tokens(figure)
    is_numeric = typ in NUMERIC and raw_has_digit
    facts = _facts(claim, exclude, corpus) if not is_numeric else []
    near = _near_facts(claim, figure, exclude) if is_numeric else []

    out, seen = [], set()

    def add(q):
        q = " ".join(str(q or "").split())
        if len(q) < 5 or len(q) > 120:
            return
        if len(q.split()) < 2 and not q.startswith('"'):
            return  # a lone entity name is not a checkable query
        k = _norm(q)
        if not k or k in seen:
            return
        seen.add(k)
        out.append(q)

    if typ == "quote":
        for run in tp.cjk_runs(sent)[:1]:
            add(f'"{run}"')          # the doc's own script travels verbatim
        core = _quote_core(raw or sent)
        if core:
            add(f'"{core}"')
        for q in extra or []:
            add(q)
        return out[:limit]           # a quote is searched as itself, not by year

    # A fixture is only pasted first when the claim actually states digits;
    # "three times" becomes "chronic liver disease flared", not "subject 3".
    if is_numeric:
        if head and figure:
            add(f"{head} {figure}")
        if head and near:
            add(f"{head} {' '.join(near[:2])} {figure}")
            add(f"{head} {' '.join(near[:2])}")
        if near:
            add(f"{' '.join(near[:2])} {figure}")
    else:
        if head and facts:
            add(f"{head} {' '.join(facts[:6])}")      # subject + the whole fact
        if facts:
            add(" ".join(facts[:8]))                  # the sentence's own facts
        if head and figure:
            add(f"{head} {figure}")
        if head and facts:
            add(f"{head} {' '.join(facts[:2])}")      # a narrower retry
        if alt and facts:
            add(f"{alt[0]} {' '.join(facts[:3])}")
    for q in extra or []:
        add(q)                    # the engine's own ladder, as a fallback
    return out[:limit]
