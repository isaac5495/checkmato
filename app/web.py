"""Web evidence module: DeepSeek Search (default) or Brave.

DeepSeek Search (`POST /v1/tools/search`) is DeepSeek's in-house index, billed
per successful request and returning structured results with a long `summary`
and an authority tier. Brave remains an explicit option for its monthly free
credit. There is no auto chain and no keyless fallback: the selected engine is
the only one that runs, and an unavailable engine is reported, never silently
replaced.

Everything is conservative: snippets must literally contain the asserted
wording/value or the verdict stays `unverified`. Three hard budgets so a run
can never crawl: search COUNT, page-fetch COUNT (deep-read), and wall-clock
SECONDS; when any is spent the run completes and flags web-dependent claims
as budget-limited (degraded mode).
"""
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import corpus as corp
from . import textproc as tp
from .searchcache import SearchCache, normalize_query

UA = "Mozilla/5.0 (compatible; CheckMato/0.1; fact-check research)"
SEARCH_TIMEOUT = 8  # seconds per search request (fail fast; budget degrades)
PAGE_TIMEOUT = 6  # seconds per full-page deep-read
PAGE_MAX_BYTES = 400_000
# hard wall-clock caps PER CALL: a search client's own timeout covers socket
# ops but NOT its internal retry loop — a half-open h2 connection could hold
# a worker hostage for an hour (observed: run frozen at deep check 10-20).
# Timeouts must kill the WAIT, not merely the socket.
SEARCH_DEADLINE = int(os.environ.get("CHECKMATO_SEARCH_DEADLINE", "25"))
PAGE_DEADLINE = int(os.environ.get("CHECKMATO_PAGE_DEADLINE", "25"))
# min seconds between ANY two searches (all workers), a courtesy pace that
# keeps the keyed APIs well inside their per-account QPS limits.
SEARCH_PACE_S = float(os.environ.get("CHECKMATO_SEARCH_PACE", "0.7"))


def _call_capped(fn, seconds):
    """Run fn in a daemon thread; raise TimeoutError if it outlives `seconds`.
    The zombie thread dies with the process; the RUN never waits for it."""
    box = {}

    def run():
        try:
            box["out"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(seconds)
    if th.is_alive():
        raise TimeoutError(f"call exceeded {seconds}s")
    if "err" in box:
        raise box["err"]
    return box.get("out")

class WebBudget:
    def __init__(self, max_searches=60, max_seconds=90, max_pages=8,
                 pace_s=None):
        self.max = max_searches
        self.max_seconds = max_seconds
        self.max_pages = max_pages
        self.start = time.monotonic()
        self.used = 0
        self.used_pages = 0
        self._lock = threading.Lock()
        # global pacing: bursts of parallel searches are exactly what earns
        # ddgs/surrogate CAPTCHA suspensions (the "2 hours of empties" failure)
        self.pace_s = SEARCH_PACE_S if pace_s is None else pace_s
        self._next = 0.0

    def wait_turn(self):
        """Sleep until this run's next paced search slot (thread-safe)."""
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.pace_s
        if wait:
            time.sleep(wait)

    def spend(self):
        """Reserve one search slot (thread-safe). Returns False if budget gone."""
        with self._lock:
            if self.used >= self.max or self.spent_time():
                return False
            self.used += 1
            return True

    def spend_page(self):
        """Reserve one deep-read page fetch (thread-safe)."""
        with self._lock:
            if self.used_pages >= self.max_pages or self.spent_time():
                return False
            self.used_pages += 1
            return True

    def spent_time(self):
        return time.monotonic() - self.start > self.max_seconds

    @property
    def exhausted(self):
        return self.used >= self.max or self.spent_time()


class BraveSearch:
    """Brave Search API: independent index (no Google/Bing scraping), free tier
    2,000 queries/month. BRAVEX_API_KEY in .env enables it; absent = chain
    unchanged (still $0). Freshness-free: plain web search, CJK hinted via
    search_lang (Brave geo-poisons by IP otherwise)."""

    URL = "https://api.search.brave.com/res/v1/web/search"

    @property
    def key(self):
        return os.environ.get("BRAVEX_API_KEY")

    @property
    def usable(self):
        if not self.key:
            return False
        from . import quota
        return quota.brave_left() > 0

    def text(self, query, max_results=6):
        from urllib.parse import urlencode
        from . import quota
        params = {"q": query, "count": min(20, max_results)}
        if any("\u4e00" <= ch <= "\u9fff" for ch in query):
            params["search_lang"] = "zh-hans"
            params["country"] = "CN"
        else:
            params["search_lang"] = "en"
        req = urllib.request.Request(
            f"{self.URL}?{urlencode(params)}",
            headers={"X-Subscription-Token": self.key,
                     "Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                left = quota.brave_left()
                if left:
                    quota.brave_spend(left)
            raise
        quota.brave_spend(1)
        web = data.get("web") or {}
        out = []
        # current Brave schema uses web.results[] (url/description); the older
        # one used web.value[] (link/snippet) — accept both
        for it in web.get("results") or web.get("value") or []:
            body = it.get("description") or it.get("snippet") or ""
            extra = it.get("extra_snippets") or []
            if extra:
                body = (body + " " + " ".join(extra))[:700]
            out.append({"title": it.get("title") or "",
                        "href": it.get("url") or it.get("link") or "",
                        "body": body})
        return out


class DeepSeekSearch:
    """DeepSeek Search API (POST /v1/tools/search): DeepSeek's in-house index,
    bearer-key auth, returns structured results with a 600-800 char summary
    meant for a model to read. DEEPSEEK_API_KEY enables it; absent = chain
    unchanged.

    Billing is per SUCCESSFUL request (empty result sets are not billed), so an
    empty set is genuinely free to fall through. `summary` is used as the body,
    not `snippet`: this engine judges figures against passages, and the 100-200
    char snippet is exactly the text that drops the qualifying clause.
    """

    URL = "https://api.deepseek.com/v1/tools/search"

    @property
    def key(self):
        return os.environ.get("DEEPSEEK_API_KEY")

    @property
    def usable(self):
        return bool(self.key)

    def text(self, query, max_results=6):
        body = json.dumps({"query": query,
                           "count": max(1, min(10, max_results)),
                           "need_content": False}).encode()
        req = urllib.request.Request(
            self.URL, data=body,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "Authorization": f"Bearer {self.key}",
                     "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        out = []
        for it in data.get("results") or []:
            text = it.get("summary") or it.get("snippet") or ""
            if not text:
                text = it.get("content") or ""
            href = it.get("url") or ""
            if not href or not text:
                continue  # a hit with no link or no text is not evidence
            out.append({"title": it.get("title") or "",
                        "href": href,
                        "body": text[:900]})
        return out


class WebEvidence:
    def __init__(self, budget=None, site_whitelist=None, entities=None,
                 entity_pairs=None, doc_paras=None, backends="deepseek",
                 cache_path=None, cache_days=14, cache_enabled=True,
                 refresh_cache=False):
        self.budget = budget or WebBudget()
        self.whitelist = site_whitelist or []
        self.raw_entities = list(entities or [])
        self.entities = [tp.normalize(e) for e in (entities or [])]
        self.entity_pairs = [(str(a), str(b)) for a, b in (entity_pairs or [])
                             if a and b]
        self.doc_paras = list(doc_paras or [])
        allp = " ".join(tp.normalize(p) for p in self.doc_paras)
        self._lat_hits = {tp.normalize(a): allp.count(tp.normalize(a))
                          for a, _n in self.entity_pairs}
        self.brave = BraveSearch()
        self.deepseek = DeepSeekSearch()
        # One selected engine, never an auto chain. If the selection has no
        # usable key, the other keyed engine takes over; with neither key the
        # run is honestly "web unavailable" rather than a silent fallback.
        self.only = (backends or "deepseek").strip().lower()
        if self.only not in ("deepseek", "brave"):
            self.only = "deepseek"
        if self.only == "brave" and not self.brave.usable:
            self.only = "deepseek"
        elif self.only == "deepseek" and not self.deepseek.usable:
            self.only = "brave" if self.brave.usable else "deepseek"
        self.available = self.brave.usable or self.deepseek.usable
        self._cache = {}
        self._pages = {}
        self._lock = threading.Lock()
        self._pool = []  # every snippet retrieved this run (for cross-claims)
        self.cache = SearchCache(path=cache_path, days=cache_days,
                                 enabled=cache_enabled)
        self.refresh_cache = bool(refresh_cache)


    def _mentions_entity(self, blob):
        """A snippet is only trusted if it names one of the document's entities.
        Blocks generic pages (e.g. '2023 in public domain') matching a bare year."""
        if not self.entities:
            return False
        nb = tp.normalize(blob)
        return any(e in nb for e in self.entities)

    def native_for(self, claim):
        """Native-script spellings of the entities THIS claim talks about
        (Qiu Bojun -> 求伯君). Checked against the sentence AND its paragraph:
        pronoun sentences ('He had graduated…') name nobody on their own.
        A Latin-letter doc about a Chinese subject is exactly the case where
        the facts live on Chinese pages — the entity·figure query must be
        typed in the language of the sources."""
        if not self.entity_pairs:
            return []
        sl = tp.normalize(claim.get("sentence") or "")
        para = ""
        p = claim.get("para")
        if isinstance(p, int) and 0 <= p < len(self.doc_paras):
            para = tp.normalize(self.doc_paras[p])
        out, late = [], []
        for lat, nat in self.entity_pairs:
            n = tp.normalize(lat)
            if not n:
                continue
            if n in sl:  # named by THIS sentence: strongest anchor — nearest first
                out.append((sl.find(n), nat))
            elif n in para:
                # pronoun sentences ('He graduated…') inherit the paragraph's
                # entities, but the DOCUMENT subject should lead, not whoever
                # happens to be named first — rank by global mention count
                late.append((-self._lat_hits.get(n, 0), nat))
        late = [nat for _k, nat in sorted(late)]
        return [nat for _pos, nat in sorted(out)] + list(dict.fromkeys(late))

    # ---- low-level ----

    def _engine_ok(self, name):
        """Only the selected engine runs. There is no auto chain and no
        always-on keyless rung: a run uses DeepSeek Search or Brave, and the
        report says which one actually ran."""
        return name == self.only

    def _backend(self, query, max_results):
        """One selected engine, never a chain.

        DeepSeek Search is the default (in-house index, billed per successful
        request); Brave remains an explicit option for its monthly free credit.
        An engine without a key is replaced at construction time by the other
        keyed engine, so this only returns [] when NEITHER key is configured —
        an honest "not searched", never a silent fallback to another vendor.
        """
        if self.only == "brave" and self.brave.usable:
            return _call_capped(
                lambda: self.brave.text(query, max_results), SEARCH_DEADLINE)
        if self.only == "deepseek" and self.deepseek.usable:
            return _call_capped(
                lambda: self.deepseek.text(query, max_results), SEARCH_DEADLINE)
        return []

    def add_passage_pool(self, passages):
        """Full-page passages the deep pass READ belong in the evidence pool
        as much as snippets do — richer text, already paid for: the page that
        proves one claim's figure often carries another claim's anecdote."""
        with self._lock:
            for p in passages:
                self._pool.append({"href": p["ref"], "title": "",
                                   "body": p["text"]})

    def search(self, query, max_results=6):
        if not self.available:
            return None  # caller must handle degraded mode explicitly
        qk = (normalize_query(query) or query, int(max_results))
        with self._lock:
            if qk in self._cache:
                return self._cache[qk]
        # A paid-for SERP is free the second time. Consult the persistent
        # cache BEFORE the budget check: hits cost nothing, so they can still
        # settle a claim after the paid budget is spent.
        if not self.refresh_cache:
            cached = self.cache.get(self.only, query, max_results)
            if cached is not None:
                with self._lock:
                    # A cached SERP is still evidence: it must join this run's
                    # pool exactly like a fresh one, or cross-claim reuse and
                    # pool-judge silently lose pages they had in run 1.
                    self._pool.extend(cached)
                    self._cache.setdefault(qk, cached)
                    return self._cache[qk]
        if self.budget.exhausted:
            return None
        if not self.budget.spend():
            return None
        self.budget.wait_turn()  # paced globally: bursts = CAPTCHA storms
        try:
            res = self._backend(query, max_results)
        except Exception:
            res = []
        # One chokepoint cleanup: SERP chrome (the 'Missing words' echo etc.)
        # must never reach the anchor, the matchers, the pool or the UI.
        cleaned = []
        for x in res:
            r = dict(x)
            r["title"] = tp.clean_snippet(r.get("title") or "")
            r["body"] = tp.clean_snippet(r.get("body") or "")
            if r["title"] or r["body"]:
                cleaned.append(r)
        res = cleaned
        with self._lock:
            self._pool.extend(res)
            self._cache.setdefault(qk, res)
            out = self._cache[qk]
        self.cache.put(self.only, query, max_results, res)
        return out

    # ---- deep read: snippets hint, pages decide ----

    def page_text(self, url):
        """Fetch one search-result page (budgeted, cached) and return readable
        text. Automates 'click the promising result and Ctrl+F' — the step
        snippet-only checking was missing."""
        with self._lock:
            if url in self._pages:
                return self._pages[url]
        if not self.budget.spend_page():
            return None

        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                if "html" not in ctype and "text" not in ctype:
                    return None
                return r.read(PAGE_MAX_BYTES).decode("utf-8", "replace")

        try:
            blob = _call_capped(_fetch, PAGE_DEADLINE)  # slow-drip servers too
        except Exception:
            return None
        if blob is None:
            return None
        text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", blob)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", text)))
        page = {"url": url, "text": text}
        with self._lock:
            self._pages[url] = page
        return page

    def search_whitelisted(self, query):
        """Try site-restricted queries first (authoritative), then open search."""
        for site in self.whitelist:
            res = self.search(f'{query} site:{site}')
            if res:
                return res
        return self.search(query)

    def can_pages(self):
        """Deep-read allowed? (fresh budget, not out of wall-clock)."""
        return (self.available and not self.budget.spent_time()
                and self.budget.used_pages < self.budget.max_pages)

    def url_status(self, url):
        """Liveness probe, free tier-safe (HEAD, short timeout)."""
        if self.budget.exhausted:
            return None
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=6) as r:
                return r.status
        except Exception as e:
            code = getattr(e, "code", None)
            return code if code else "dead"

    # ---- claim-level verification ----

    def _assess_quote(self, claim, res, query=None):
        """Strict scoring of retrieved results for a quote claim (no search)."""
        q = claim["raw"]
        scored = []
        for r in res:
            body = ((r.get("body") or "") + " " + (r.get("title") or "")).strip()
            if not body:
                continue  # junk row (no snippet text) can never prove anything
            ratio = corp._windowed_ratio(tp.normalize(q), tp.normalize(body))
            # a near-verbatim snippet wins even without an entity hit (the wording
            # itself is the fingerprint); weaker matches must name the subject
            if ratio < 0.9 and not self._mentions_entity(body):
                continue
            scored.append((ratio, r))
        scored.sort(key=lambda t: -t[0])
        top = self._distinct(scored)
        if top and top[0][0] >= 0.9 and (top[0][1].get("href") or top[0][1].get("body")):
            return {"status": "supported",
                    "evidence": [self._ev(r) for _, r in top[:3]],
                    "ratio": top[0][0]}
        res = [r for _, r in scored] or res
        return {"status": "notfound" if res else "noresults",
                "evidence": self._snippet_evidence(
                    [r for _, r in self._distinct([(0.0, r) for r in res])][:2]),
                "ratio": top[0][0] if top else 0.0}

    @staticmethod
    def _distinct(scored):
        seen, out = set(), []
        for ratio, r in scored:
            href = r.get("href", "")
            if href and href in seen:
                continue
            seen.add(href)
            out.append((ratio, r))
        return out

    _MIN_PRE = re.compile(r"(over|more than|greater than|exceeding|at least|"
                          r"超过|逾|至少)\s*$", re.I)
    _APX_PRE = re.compile(r"(about|approximately|approx|roughly|around|nearly|almost|"
                          r"约|近)\s*$", re.I)

    def _modifier(self, claim):
        return modifier(claim)

    # words that prove NOTHING about same-predicate: units, currency names,
    # count nouns and hedges shared by every financial snippet on the web
    UNIT_NOISE = {"million", "billion", "trillion", "thousand", "yuan", "usd",
                  "rmb", "hkd", "cny", "元", "美元", "港元", "percent", "pct",
                  "copies", "copy", "units", "over", "about", "approximately",
                  "roughly", "around", "nearly", "more", "than", "less"}

    def _num_matches(self, claim, v, mod):
        return num_matches(claim, v, mod)

    def _num_conflicts(self, claim, v, mod):
        return num_conflicts(claim, v, mod)

    @staticmethod
    def _near(body, a, b, win=60):
        """True if figure b appears within `win` chars of a mention of a."""
        i = body.find(a)
        while i >= 0:
            j = body.find(b, max(0, i - win), i + len(a) + win)
            if j >= 0:
                return True
            i = body.find(a, i + 1)
        return False

    _SKIP_IN_WINDOW = set(" .,:·、。()（）[]【】\"'“”‘’-*—~")

    @staticmethod
    def _cjk_near(body, fig):
        """True if some occurrence of `fig` touches CJK characters directly
        (skipping only punctuation/space): a Chinese page writes '1984年',
        '24岁', '122000行'; an echoed SERP chrome writes 'room 501' or
        '28日 · Address: Room 501' where the number belongs to Latin text.
        Anything in between that is a LETTER disqualifies the occurrence."""
        b = WebEvidence._SKIP_IN_WINDOW
        i = body.find(fig)
        while i >= 0:
            j = i - 1
            while j >= 0 and body[j] in b:
                j -= 1
            k = i + len(fig)
            while k < len(body) and body[k] in b:
                k += 1
            before = j >= 0 and tp.CJK.match(body[j]) is not None
            after = k < len(body) and tp.CJK.match(body[k]) is not None
            if before or after:
                return True
            i = body.find(fig, i + 1)
        return False

    def _assess_number(self, claim, res, strict_contradict=False, query=""):
        """Strict scoring of retrieved results for a number claim (no search).
        Both support and contradiction need an entity-anchored snippet whose
        predicate agrees with the claim's sentence. strict_contradict=True for
        snippets fetched on ANOTHER claim's behalf: a contradiction then needs
        an explicitly-valued figure (currency present), never a bare number.
        Cross-script relaxation: a query that already carries THIS claim's
        figure (entity·figure shape, '求伯君 1984') whose CJK snippet names the
        subject AND states the figure counts as predicate agreement — token
        overlap was structurally impossible between an English claim and the
        Chinese page that holds the fact. Contradiction keeps its heavy guards."""
        ctoks = set(tp.rare_raw_tokens(claim["sentence"]))
        claim_names = tp.name_tokens(claim["sentence"])
        claim_event = tp.event_of(tp.normalize(claim["sentence"]))
        enttoks = set()
        for e in self.entities:
            enttoks |= tp.tokens(e)
        mod = self._modifier(claim)
        qv = self._value_str(claim)
        hits, near = [], []
        for r in res:
            body = (r.get("body") or "") + " " + (r.get("title") or "")
            if not self._mentions_entity(body):
                continue
            blobtoks = tp.tokens(body)
            pred = len((ctoks - enttoks) & blobtoks) >= 2
            xscript = False
            if not pred and qv and query and qv in query and tp.CJK.search(body):
                # Cross-script support (an English claim answered by the
                # Chinese page that holds the fact) needs the query's own
                # entity stated RIGHT NEXT TO the figure ("1984年，求伯君毕业",
                # the figure touching CJK directly — 'room 501' chrome does
                # not), AND a SECOND distinct document entity co-occurring:
                # a lone name match can be a lookalike stranger (the real
                # 张旭龙 pages that 'supported' a Kingsoft date with nothing
                # but a borrowed name). Corroboration is the CJK stand-in for
                # predicate tokens. Contradiction keeps its heavy guards.
                nb = tp.normalize(body)
                nq = tp.normalize(query)  # match the query the SAME way the
                # snippet is matched: entities are t2s-normalized, so comparing
                # '松下电器' against a raw '松下電器' query (traditional) misses.
                present = {tp.normalize(str(e)) for e in self.raw_entities
                           if e and len(tp.normalize(str(e))) >= 2
                           and tp.normalize(str(e)) in nb}
                # corroboration (user decision 2026-09-07, after two audited
                # false greens): the figure must be tied to TWO distinct
                # document entities. Subject-alone + year is trivially
                # satisfiable on any page of the company ('Kingsoft…2021…'
                # stock news 'supporting' a 2021 dinner anecdote) and a lone
                # person name is a lookalike risk (the 张旭龙 pages). Cost,
                # accepted: company-only milestone years ('founded 1918')
                # fall to unverified unless a second entity co-occurs.
                corr = len(present) >= 2
                for e in self.raw_entities:
                    ne = tp.normalize(str(e))
                    if corr and ne and len(ne) >= 2 and ne in nq and ne in nb \
                            and self._near(nb, ne, qv) \
                            and self._cjk_near(nb, qv):
                        pred = True
                        xscript = True
                        break
            if claim["type"] == "year" and pred and not xscript:
                yfact = tp.year_fact_tokens(
                    claim["sentence"], claim.get("raw") or claim.get("value"))
                yfact -= enttoks
                ev_ok = (claim_event is not None
                         and claim_event == tp.event_of(tp.normalize(body)))
                if yfact and not ev_ok and not (yfact & blobtoks):
                    pred = False
            vals = tp.extract_values(body)
            same = [v for v in vals if v["kind"] == claim["type"] and
                    (claim["type"] != "amount" or
                     tp.currency_compatible(claim["currency"], v["currency"]))]
            if (not pred and same and distinctive_value(claim)
                    and any(self._num_matches(claim, v, mod) for v in same)):
                pred = True  # self-anchoring exact figure (see distinctive_value)
            if pred and same:
                # modifier-aware agreement: "over 90%" is SUPPORTED by 95%,
                # "about US$14m" is supported within 15%
                if any(self._num_matches(claim, v, mod) for v in same):
                    hits.append(r)
                    continue
                cf = [v for v in same if self._num_conflicts(claim, v, mod)]
                if not cf:
                    continue
                # an IDF label (room 501) is never denied by a non-IDF figure
                # ('24-year-old'): they share only the type, never the fact
                if tp.IDF_LABEL.search(claim.get("raw") or "") and not any(
                        tp.IDF_LABEL.search(str(v.get("raw") or "")) for v in cf):
                    continue
                # Rule 5 generalized: an UNDATED figure never contradicts a
                # DATED claim (today's share price HK$24.56 does not refute
                # 'fell back to HK$2.70' in July 2011 — different points on
                # the same curve). A dated claim needs a dated source.
                if claim["type"] in ("amount", "pct", "count"):
                    cy = tp.years_in(claim["sentence"])
                    by = tp.years_in(body)
                    if cy and set(cy) != set(by) and not (set(cy) & set(by)):
                        continue
                # '22.89% of the voting rights' and '15.68% shareholding' are
                # DIFFERENT percentages, not a contradiction — a pct claim is
                # only refuted by a source measuring the same base quantity.
                if claim["type"] == "pct":
                    ca = _pct_base(claim["sentence"], claim.get("raw", ""))
                    cb = _pct_base(body, cf[0].get("raw", ""))
                    if ca and cb and not (ca & cb):
                        continue
                # CONTRADICTION is a heavier claim than SUPPORT: it needs the
                # SAME event, or >=3 shared non-name content words. A bare
                # number never overturns a revenue claim; a year never
                # contradicts on event mismatch (annual 1990 vs cumulative 1993).
                if claim["type"] == "amount" and not all(v["currency"] for v in cf):
                    continue
                shared2 = ((ctoks - enttoks) & blobtoks) - claim_names \
                    - tp.name_tokens(body) - self.UNIT_NOISE
                shared2 = {tp.stem(t) for t in shared2} - self.UNIT_NOISE
                ev_ok = (claim_event is not None
                         and claim_event == tp.event_of(tp.normalize(body)))
                if claim["type"] == "year":
                    if not ev_ok or len(shared2) < (3 if strict_contradict else 2):
                        continue
                elif not ev_ok and len(shared2) < (4 if strict_contradict else 3):
                    continue
                near.append((r, cf))
        if hits and near:
            # REAL source conflict (e.g. lego.com vs Wikipedia on the naming
            # year): neither side may silently win — show the user both camps
            # and let them decide (`conflicting` verdict).
            sup = self._distinct([(1.0, h) for h in hits])
            con = self._distinct([(1.0, h[0]) for h in near])
            r0, same0 = near[0]
            return {"status": "conflicting",
                    "evidence": ([self._ev(u[1], side="support") for u in sup[:2]]
                                 + [self._ev(r0, side="contradict")]
                                 + [self._ev(u[1], side="contradict")
                                    for u in con[1:2]]),
                    "conflicting": ", ".join(sorted({v["raw"] for v in same0}))}
        if hits:
            uniq = self._distinct([(1.0, h) for h in hits])
            return {"status": "supported",
                    "evidence": [self._ev(u[1]) for u in uniq[:3]]}
        if near:
            uniq = self._distinct([(1.0, h[0]) for h in near])
            r0, same0 = near[0]
            return {"status": "contradicted", "evidence": [self._ev(r0)] +
                    [self._ev(u[1]) for u in uniq[1:2]],
                    "conflicting": ", ".join(sorted({v["raw"] for v in same0}))}
        return {"status": "notfound" if res else "noresults",
                "evidence": self._snippet_evidence(res[:2])}

    def reuse_pool(self, claim):
        """Match snippets ALREADY fetched this run (e.g. searches for sibling
        claims in the same sentence) against this claim. Same strict guards,
        zero extra search budget — one good source can settle many assertions.

        SUPPORT ONLY. A snippet the engine did not search for THIS claim may
        confirm it, but never contradict it: a press retrospective that lists
        a dozen years (or a price list with a dozen figures) would otherwise
        "refute" any single value by proximity. Direct searches keep the full
        contradiction guards; reuse gives the reader a lead, not a red flag.
        """
        if not self._pool:
            return None
        if claim["type"] == "quote":
            return self._assess_quote(claim, self._pool)
        if claim["type"] in ("year", "amount", "pct", "count"):
            if not self.entities:
                return None
            out = self._assess_number(claim, self._pool, strict_contradict=True)
            if out and out.get("status") == "contradicted":
                return None
            return out
        return None

    def _snippet_evidence(self, res):
        out = []
        for r in res[:5]:
            body = r.get("body") or r.get("snippet") or ""
            if body:
                out.append({"kind": "web", "ref": r.get("href", ""),
                            "quote": corp.clip(body, 320), "precision": "snippet",
                            "tier": self._tier(r)})
        return out

    # ---- query ladder: try 2-3 human-like phrasings before giving up ----

    def _ladder_ok(self):
        """Escalation allowed? Keep >=40% of the search budget in reserve for
        the sentence-level deep pass — early keyword retries must not starve
        every later claim."""
        return (self.budget.used <= int(self.budget.max * 0.6)
                and not self.budget.spent_time())

    def _run_ladder(self, claim, queries, assess):
        tried, best = [], None
        for k, query in enumerate(queries[:3]):  # hard cap 3 variants/claim
            if k and not self._ladder_ok():
                break
            res = self.search_whitelisted(query)
            tried.append(query)
            if res is None:
                return {"status": "budget" if self.budget.exhausted else "unavailable",
                        "queries": tried}
            out = assess(claim, res, query=query)
            out["query"] = query
            out["queries"] = tried
            if out["status"] in ("supported", "conflicting"):
                # both camps in hand is a SETTLED answer (for the user), not
                # a reason to search more (rule 7: early-stop > more searches)
                return out
            if best is None or (best["status"] == "noresults"
                                and out["status"] != "noresults"):
                best = out
            # escalate ONLY when the query returned nothing at all, OR (for a
            # distinctive exact figure) when results came back but none carried
            # it: an entity+figure query like '金山软件 15.68%' is a SHARPER
            # retrieval, not a sloppier variant, so it does not raise the
            # odds of a coincidental match the way more prose variants would.
            # escalate ONLY when the query returned nothing at all, OR (for a
            # distinctive exact figure or a verbatim QUOTE) when results came
            # back but none carried it: an entity+figure query like
            # '金山软件 15.68%' is a SHARPER retrieval, not a sloppier variant,
            # and every rung of a quote ladder is the same fingerprint in a
            # different wrapper — a miss on one says nothing about the next.
            if out["status"] != "noresults" and not (
                    out["status"] == "notfound"
                    and (distinctive_value(claim) or claim["type"] == "quote")):
                break
            if self.budget.exhausted:
                break
        # the human's LAST rung: every variant returned ZERO results (not
        # "wrong results") — the query was too long, not the fact absent.
        # Retry ONE tightest-core query (entity + figure + rarest words).
        if (best is None or best["status"] in ("noresults", "notfound")) \
                and not self.budget.exhausted:
            for core in compact_queries(claim, self.raw_entities,
                                        self.native_for(claim)):
                if core.lower() in " ".join(tried).lower():
                    continue
                res = self.search_whitelisted(core)
                if res is None:
                    break
                out = assess(claim, res, query=core)
                out["query"] = core
                out["queries"] = tried + [core]
                if best is None or out["status"] not in ("noresults",):
                    best = out
                if out["status"] not in ("noresults", "notfound"):
                    break  # a verdict-level answer: stop here
                # (no match is NOT 'information' across DIFFERENT anchors:
                #  '金山软件 1984' returning junk says nothing about
                #  '求伯君 1984' — the sharper entity query is the one a human
                #  would type next, so keep walking the compact cores)
                if self.budget.exhausted:
                    break
            return best
        return best

    def _value_str(self, claim):
        try:
            v = claim.get("value")
            return str(int(v)) if v is not None and float(v) == int(v) else str(v)
        except Exception:
            return ""

    def verify_quote(self, claim):
        """Returns status dict: {status, evidence, ratio, query, queries}."""
        q = claim["raw"]
        subject = tp.rare_phrase(claim["sentence"], 4)
        alt = next((e for e in self.raw_entities
                    if e and tp.normalize(e) not in subject.lower()), "")
        queries = self._ladder([f'"{q[:120]}" {subject}',
                                f'"{q[:80]}"',
                                f'"{q[:100]}" {alt}' if alt else ""])
        # The document's OWN native-script rendering (a Chinese slogan in
        # parentheses beside its translation) is the verbatim string real
        # sources quote — it is the one query machine translation must never
        # replace, so quote it and search it too.
        for run in tp.cjk_runs(claim["sentence"])[:1]:
            queries.insert(1, f'"{run}"')
        return self._run_ladder(claim, queries, self._assess_quote)

    def verify_number(self, claim):
        """Returns {status, evidence, conflicting, query, queries}. Requires an
        entity-anchored snippet — a page that never mentions the document's
        subject cannot confirm or deny a number."""
        if not self.entities:
            return {"status": "noentities"}
        subject = tp.rare_phrase(claim["sentence"], 4)
        sl = claim["sentence"].lower()
        primary = next((e for e in self.raw_entities if tp.normalize(e) in tp.normalize(sl)),
                       self.raw_entities[0] if self.raw_entities else "")
        unit = claim.get("raw", "")
        vd = self._value_str(claim)
        alt = next((e for e in self.raw_entities if e != primary), "")
        nats = self.native_for(claim)
        nf = (unit if any(ch.isdigit() for ch in unit) else vd) if vd else ""
        queries = self._ladder([f"{primary} {subject} {unit}",
                                f"{nats[0]} {nf}" if nats and nf else "",
                                f"{primary} {subject} {vd}" if vd and vd != unit else "",
                                f"{primary} {unit or vd}",
                                f"{alt} {subject} {unit}" if alt else ""])
        return self._run_ladder(claim, queries, self._assess_number)

    @staticmethod
    def _ladder(qs):
        return [q for q in dict.fromkeys(qs) if q and len(q.strip()) > 4]

    # ---- deep read: turn promising snippets into passage-level evidence ----

    def _windows(self, claim, page, radius=1):
        """Sentences of the fetched page that carry the claim's value/entity,
        widened by `radius` neighbours — returned in the same result-schema as
        search snippets so the SAME strict assessors apply to full-page text."""
        sents = [s.strip() for s in re.split(r"(?<=[.!?。！？;])\s+", page["text"])
                 if len(s.strip()) > 15]
        if not sents:
            return []
        picks = []
        if claim["type"] == "quote":
            qn = tp.normalize(claim["raw"])
            scored = sorted(((corp._windowed_ratio(qn, tp.normalize(s)), i)
                             for i, s in enumerate(sents)), reverse=True)
            picks = [i for r, i in scored[:4] if r > 0.35]
        else:
            keys = [k for k in (self._value_str(claim),
                                tp.normalize(claim.get("raw", ""))) if k and len(k) > 1]
            rare = {tp.normalize(t) for t in tp.rare_raw_tokens(
                claim.get("sentence", "")) if len(t) > 2}
            scored = []
            for i, s in enumerate(sents):
                ns = tp.normalize(s)
                vhit = any(k in ns for k in keys)
                ohit = sum(1 for t in rare if t in ns)
                if vhit:
                    scored.append((1000 + ohit, i))      # the figure itself wins
                elif ohit:
                    scored.append((ohit, i))             # rare-word overlap: Ctrl+F
                elif any(e in ns for e in self.entities):
                    scored.append((0.5, i))              # entity lead-ins last
            scored.sort(reverse=True)
            picks = [i for _, i in scored[:6]]
        out, used = [], []
        for i in picks:
            lo, hi = max(0, i - radius), min(len(sents), i + radius + 1)
            if any(max(lo, a) < min(hi, b) for a, b in used):
                continue
            used.append((lo, hi))
            out.append({"href": page["url"], "title": "",
                        "body": " ".join(sents[lo:hi])[:700]})
        return out

    def read_evidence(self, claim, urls):
        """Deep-read the top pages already surfaced by searches and re-run the
        same strict guards on passage windows. precision='passage' everywhere."""
        if claim["type"] not in ("quote", "year", "amount", "pct", "count"):
            return None
        if claim["type"] != "quote" and not self.entities:
            return None
        pseudo = []
        for u in [u for u in dict.fromkeys(urls) if u][:3]:
            page = self.page_text(u)
            if page:
                pseudo += self._windows(claim, page)
        if not pseudo:
            return None
        out = (self._assess_quote(claim, pseudo) if claim["type"] == "quote"
               else self._assess_number(claim, pseudo, strict_contradict=True))
        for e in out.get("evidence", []):
            e["precision"] = "passage"
            e["note"] = "full page read (deep-read)"
        return out

    def narrative_passages(self, claim, urls):
        """The Ctrl+F equivalent for a PROSE claim: fetch the promising pages
        already surfaced and hand back entity-carrying sentence windows, so the
        LLM judge can read the article BODY (a fact buried below the snippet is
        still findable — the human 'click the result' step). Number/quote
        claims use the stricter arithmetic assessor in read_evidence instead."""
        if not self.entities:
            return []
        pseudo = []
        for u in [u for u in dict.fromkeys(urls) if u][:2]:
            page = self.page_text(u)
            if page:
                pseudo += self._windows(claim, page, radius=2)
        return [{"kind": "web", "ref": w["href"], "quote": corp.clip(w["body"], 320),
                 "precision": "passage"} for w in pseudo]

    def search_raw(self, query, max_results=5):
        """Raw retrieval for LLM judging (no local verdict): returns snippets."""
        res = self.search(query, max_results=max_results)
        if not res:
            return []
        return [{"kind": "web", "ref": r.get("href", ""),
                 "quote": corp.clip((r.get("body") or "") + " " + (r.get("title") or ""), 320),
                 "precision": "snippet"} for r in res]

    # open/community-tier domains: fine as corroboration, weak alone for academic work
    COMMUNITY_DOMAINS = ("wikipedia.org", "wikidata.org", "baike.baidu.com", "quora.com", "reddit.com",
                         "fandom.com", "blogspot.", "medium.com", "pinterest.")

    @classmethod
    def _tier(cls, r):
        host = (r.get("href") or "").lower()
        return "open-community" if any(d in host for d in cls.COMMUNITY_DOMAINS) else "published"

    def _ev(self, r, side=None):
        body = ((r.get("body") or "") + " " + (r.get("title") or "")).strip()
        ev = {"kind": "web", "ref": r.get("href", ""),
              "quote": corp.clip(body, 320), "precision": "snippet",
              "tier": self._tier(r)}
        if side:
            ev["side"] = side
        return ev


_MIN_PRE = re.compile(r"(over|more than|greater than|exceeding|at least|"
                      r"超过|逾|至少)\s*$", re.I)
_APX_PRE = re.compile(r"(about|approximately|approx|roughly|around|nearly|almost|"
                      r"约|近)\s*$", re.I)


def compact_queries(claim, raw_entities, nat_pref=()):
    """The core of a claim as SHORT queries. Long keyword chains AND to zero
    on wiki-style search engines; humans narrow instead of adding words.
    For a claim with a figure, the native-script entity + figure variant
    ('金山软件 15.68%') is included FIRST — it is the query that reaches
    articles in the subject's own language, immune to any planner typo.
    nat_pref = this claim's own entities in native script (求伯君 for a
    Qiu Bojun sentence) — they come before generic subject natives, and
    the CJK rungs carry the DIGIT form ('24', not 'twenty-four'): Chinese
    pages never write Latin word-numbers."""
    out = []
    sl = claim.get("sentence") or ""
    val = (claim.get("raw") or "").strip()
    vd = ""
    if claim.get("value") is not None and claim["type"] in (
            "year", "amount", "pct", "count"):
        v = claim["value"]
        vd = str(int(v)) if v == int(v) else str(v)
    nat = list(dict.fromkeys(
        [e for e in nat_pref if e]
        + [e for e in raw_entities if e and any(
            "\u4e00" <= ch <= "\u9fff" for ch in str(e))]))
    if claim["type"] in ("year", "count") and vd:
        fig = vd
    elif val and any(ch.isdigit() for ch in val):
        fig = val
    else:
        fig = vd or val
    if fig:
        for e in nat[:2]:
            q = f"{e} {fig}".strip()
            if len(q) > 4:
                out.append(q)
    ent = next((e for e in raw_entities
                if e and tp.normalize(e) in tp.normalize(sl)),
               raw_entities[0] if raw_entities else "")
    keep = {tp.normalize(val)} if val else set()
    toks = [t for t in tp.rare_raw_tokens(sl) if t.isascii()
            if t not in keep and tp.normalize(t) not in tp.normalize(ent)][-2:]
    parts = [p for p in dict.fromkeys(x for x in (ent, val or vd) + tuple(toks) if x)]
    q = " ".join(parts).strip()
    if len(q) > 6 and len(parts) >= 2:
        out.append(q)
    return list(dict.fromkeys(out))[:3]


def _pct_base(sentence, raw):
    """What a stated percentage is a percentage OF ('22.89% of the voting
    rights' -> {vot, right}); empty if the phrasing carries no base."""
    num = re.escape((raw or "").strip().rstrip("%").strip())
    if not num:
        return set()
    m = re.search(num + r"(?:\s*%)?\s+(?:of\s+)?(?:the\s+)?([A-Za-z][A-Za-z\s']{1,30})",
                  sentence or "", re.I)
    if not m:
        return set()
    words = [t for t in tp.tokens(m.group(1)) if t not in tp.STOP][:3]
    return {tp.stem(t) for t in words}


def distinctive_value(claim):
    """Figures with decimals or 3+ significant digits (15.68%, 22.89%,
    122,000, HK$2.70) do not appear BY ACCIDENT in a snippet about the
    subject — the number itself is the predicate. Round numbers (20%, 80%)
    are common words of art and keep the stricter shared-context bar."""
    v = claim.get("value")
    if v is None:
        return False
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    if claim["type"] in ("pct", "amount"):
        return v != int(v)
    if claim["type"] == "count":
        if tp.IDF_LABEL.search(claim.get("raw") or ""):
            # 'Room 501' is a LABEL, not a quantity: hundreds of company
            # filings list office addresses 'Room 501, Block A…' — that is
            # coincidence, never self-anchoring proof of a hotel room.
            return False
        return abs(v) >= 100 and str(int(abs(v))).rstrip("0").__len__() >= 3
    return False


def modifier(claim):
    """Words directly BEFORE a figure: 'over 90%' / 'about US$14m' change what
    counts as agreement — 95% SUPPORTS 'over 90%', it must not be reported as
    contradicting it. Shared by web assessors and the BYOS corpus judge."""
    sp = claim.get("span") or [0]
    pre = claim.get("sentence", "")[:sp[0]].lower()[-18:]
    if _MIN_PRE.search(pre):
        return "min"
    if _APX_PRE.search(pre):
        return "approx"
    return None


def num_matches(claim, v, mod):
    if claim.get("value") is None or v.get("value") is None:
        return False
    if tp.values_equal(claim["value"], v["value"], kind=claim["type"]):
        return True
    if mod == "min" and v["value"] >= claim["value"]:
        return True
    if mod == "approx" and claim["value"] and \
            abs(v["value"] - claim["value"]) <= 0.15 * max(claim["value"], v["value"]):
        return True
    return False


def num_conflicts(claim, v, mod):
    if num_matches(claim, v, mod):
        return False
    if mod == "min":
        return v["value"] < claim["value"]
    if mod == "approx":
        return bool(claim["value"]) and \
            abs(v["value"] - claim["value"]) > 0.3 * claim["value"]
    return True
