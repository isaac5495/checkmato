import logging
from pathlib import Path

from . import textproc as tp
from .retrieval import BM25Index

log = logging.getLogger("checkmato.corpus")

VERBATIM_CUT = 0.98
PARAPHRASE_CUT = 0.62
MAX_FILE_BYTES = 40 * 1024 * 1024      # skip runaway single files
MAX_LINES_PER_FILE = 200_000           # hard memory guard

# Field weighting, borrowed from pith's index (title x2, tags x2, content x0.5)
# and mapped onto what a CheckMato source actually has: its filename and the
# section heading above the passage. Applied as a BOUNDED rerank of the BM25
# candidate pool, so a title/heading hit can break a near-tie but can never
# outrank a passage whose text matches far better. Ranking only: evidence still
# comes from the original line/page, so locators and verdicts are unchanged.
FIELD_TITLE_WEIGHT = 2.0
FIELD_HEADING_WEIGHT = 2.0
FIELD_BONUS_CAP = 0.5                  # final score <= base * 1.5
BM25_POOL_FACTOR = 4                   # search wider than `top`, then rerank


def clip(text, n=280):
    """Evidence display clip: verbatim quote, elided with marker if too long."""
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + " …[line clipped]"


def _windowed_ratio(short, long):
    """Best char similarity between `short` and any same-length window of `long`.
    Lets a verbatim quote match even when the source line adds attribution."""
    import difflib as _d
    if not short or not long:
        return 0.0  # an EMPTY snippet must never ratio 1.0 against a quote
    if len(long) < len(short):
        short, long = long, short
    L = len(short)
    if not L:
        return 0.0
    best = 0.0
    for i in range(0, len(long) - L + 1, 2):
        r = _d.SequenceMatcher(None, short, long[i:i + L]).ratio()
        if r > best:
            best = r
    return best


def _longest_common_phrase(a, b, min_len=3, max_len=12):
    """Length of the longest shared CJK/Latin phrase (>= min_len).

    A bag of rare bigrams can still rank a paragraph that merely shares many
    common pieces. A contiguous 4-6 character phrase is the thing a human
    Ctrl+F actually matches, so it gets its own bounded bonus.
    """
    a, b = tp.normalize(a), tp.normalize(b)
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    for n in range(min(max_len, len(a)), min_len - 1, -1):
        for i in range(len(a) - n + 1):
            s = a[i:i + n]
            if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff"
                       for ch in s):
                continue
            if s in b:
                return n
    return 0


def sniff_bytes(raw):
    """Decode bytes robustly: strict UTF-8 first, then charset detection
    (real-world .txt sources are GBK/Big5/latin-1), finally lossy UTF-8."""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best is not None:
            return str(best)
    except Exception as e:
        log.debug("charset detection unavailable: %s", e)
    return raw.decode("utf-8", errors="replace")


def _field_tokens(name):
    """Filename -> title tokens: 'acme_2025_results.pdf' -> {acme,2025,result}."""
    stem = Path(name).stem
    for ch in "_-.":
        stem = stem.replace(ch, " ")
    return tp.tokens(stem)


def _field_rerank(qtokens, pool):
    """Reorder BM25 hits by a bounded title/heading bonus (deterministic).

    `pool` is [(bm25_score, passage), ...] already in BM25 order. The bonus is
    capped by FIELD_BONUS_CAP, so a field hit lifts a close competitor but
    cannot beat a passage that matches the text much better. Passages without a
    field hit keep their score exactly; equal scores keep BM25 order (stable
    sort), so results never depend on dict/set iteration order.
    """
    if not qtokens:
        return [p for _s, p in pool]
    span = FIELD_TITLE_WEIGHT + FIELD_HEADING_WEIGHT
    scored = []
    for score, p in pool:
        hits = (FIELD_TITLE_WEIGHT
                * len(qtokens & (p.get("title_tokens") or frozenset()))
                + FIELD_HEADING_WEIGHT
                * len(qtokens & (p.get("heading_tokens") or frozenset())))
        norm = hits / (span * len(qtokens))     # 0..1
        scored.append((float(score) * (1.0 + FIELD_BONUS_CAP * norm), p))
    scored.sort(key=lambda r: (-r[0], r[1].get("fname") or "",
                               r[1].get("start") or 0))
    return [p for _s, p in scored]


class Corpus:
    """BYOS (bring-your-own-sources) line index over .md/.txt/.csv plus PDF and
    DOCX extraction (pdf→page precision, docx→paragraph precision).

    Retrieval: inverted token index -> line scoring -> difflib quote matching.
    Deterministic and order-stable; evidence clipped for display, refs precise.
    """

    def __init__(self, root, aliases=None, skip=None, include_paths=None):
        self.root = Path(root) if root else None
        self.aliases = aliases  # names.AliasMap or None
        self.lines = []          # (file, lineno, raw, token_set, precision)
        self.posting = {}        # token -> [line_index, ...]
        self.files = []
        self.df = {}
        if self.root and self.root.exists():
            if include_paths is not None:
                # manifest mode: ingest exactly these files, wherever they live
                for p in sorted({Path(x) for x in include_paths}):
                    if skip and skip(p):
                        continue
                    self._ingest_any(p)
            else:
                for p in sorted(self.root.rglob("*")):
                    if skip and skip(p):
                        continue
                    self._ingest_any(p)
        # normalized line text for the literal (Ctrl+F) lane; built once so a
        # document with hundreds of prose claims does not re-normalize 6k lines
        # per claim
        self.norm_lines = [tp.normalize(line[2]) for line in self.lines]
        # per-file token vocabulary: a soft source-topic prior. A claim about
        # games should prefer the game-history file even when the exact wording
        # is absent; this is content-based, never a filename whitelist.
        self.file_tokens = {}
        for fname, _lineno, _raw, toks, _prec in self.lines:
            self.file_tokens.setdefault(fname, set()).update(toks)
        self.passages = []
        self._build_passages()
        self.value_index = {}
        for i, line in enumerate(self.lines):
            for v in tp.extract_values(line[2]):
                key = (v["kind"], round(float(v["value"]), 6),
                       v.get("currency") if v["kind"] == "amount" else None)
                self.value_index.setdefault(key, []).append(i)
        self.passage_value_index = {}
        for i, p in enumerate(self.passages):
            for v in tp.extract_values(p["text"]):
                key = (v["kind"], round(float(v["value"]), 6),
                       v.get("currency") if v["kind"] == "amount" else None)
                self.passage_value_index.setdefault(key, []).append(i)
        self.bm25 = BM25Index(self.passages)

    def find_value_lines(self, keywords, kind, value, currency=None, top=20):
        """Lines that state THIS value, intersected with the subject keywords.

        Word-first retrieval cannot find "12.2万行" when the source says
        "122,000"; the value index can, and it keeps the subject gate so a
        number in an unrelated paragraph is not promoted.
        """
        key = (kind, round(float(value), 6),
               currency if kind == "amount" else None)
        keys = [key]
        if kind == "amount":
            keys.append((kind, round(float(value), 6), None))
        vids = set()
        for k in keys:
            vids.update(self.value_index.get(k, ()))
        if not vids:
            return []
        kws = set(keywords)
        kids = set()
        for t in kws:
            kids.update(self.posting.get(t, ()))
        cand = vids & kids
        scored = []
        for idx in cand:
            fname, lineno, raw, toks, precision = self.lines[idx]
            if kind == "amount" and currency:
                vals = [v for v in tp.extract_values(raw)
                        if v["kind"] == "amount"
                        and round(float(v["value"]), 6) == round(float(value), 6)]
                if vals and not any(tp.currency_compatible(currency,
                                                           v.get("currency"))
                                    for v in vals):
                    continue
            shared = kws & toks
            if shared:
                scored.append((len(shared), fname, lineno, raw, shared,
                               precision))
        scored.sort(key=lambda r: (-r[0], r[1], r[2]))
        return scored[:top]

    def find_value_passages(self, keywords, kind, value, currency=None, top=8):
        """Passages that state this value AND share at least two subject words."""
        keys = [(kind, round(float(value), 6),
                 currency if kind == "amount" else None)]
        if kind == "amount":
            keys.append((kind, round(float(value), 6), None))
        idxs = []
        for k in keys:
            idxs.extend(self.passage_value_index.get(k, ()))
        kws = set(keywords)
        scored = []
        for i in dict.fromkeys(idxs):
            p = self.passages[i]
            shared = kws & p["tokens"]
            if len(shared) >= 2:
                scored.append((len(shared), p))
        scored.sort(key=lambda r: (-r[0], r[1]["fname"], r[1]["start"]))
        return [p for _n, p in scored[:top]]

    def find_bm25_passages(self, query, top=8):
        """BM25 passages, reranked by a bounded source-title / section-heading
        bonus (see `_field_rerank`). Every returned passage is a real passage
        object, so `fname`/`start` locators are untouched."""
        if not query:
            return []
        pool = self.bm25.search(query, top=max(top * BM25_POOL_FACTOR, top))
        if not pool:
            return []
        return _field_rerank(set(tp.tokens(query)), pool)[:top]

    def expand_passages(self, passages, radius=1):
        """Neighbouring passages, for facts that straddle a chunk boundary."""
        seen, out = set(), []
        for p in passages:
            i = p.get("idx")
            if i is None:
                continue
            for j in range(max(0, i - radius),
                           min(len(self.passages), i + radius + 1)):
                if j not in seen:
                    seen.add(j)
                    out.append(self.passages[j])
        return out

    def _build_passages(self, target=600, hard=900):
        """Merge adjacent lines so a fact split across lines is still found.

        Never merges across a heading: the heading starts the next passage, so
        the passage carries its section context. Single-line facts still yield
        a passage of one line.
        """
        by_file = {}
        for fname, lineno, raw, _toks, _prec in self.lines:
            by_file.setdefault(fname, []).append((lineno, raw))
        for fname, rows in by_file.items():
            title = _field_tokens(fname)
            heading = ""            # section heading in force for the passage
            buf, start, end = [], None, None

            def flush():
                nonlocal buf, start, end
                if not buf:
                    return
                text = "\n".join(buf)
                self.passages.append({
                    "idx": len(self.passages),
                    "fname": fname, "start": start, "end": end,
                    "text": text, "tokens": tp.tokens(text),
                    # field tokens are for ranking only; they never become
                    # evidence and never change the locator above
                    "title_tokens": title,
                    "heading_tokens": tp.tokens(heading)})
                buf, start, end = [], None, None

            for lineno, raw in rows:
                if raw.startswith("#"):
                    # a heading starts a passage AND labels every passage below
                    # it, so the section is searchable even when a later
                    # paragraph never repeats its subject word
                    if buf:
                        flush()
                    heading = raw.lstrip("#").strip()
                if start is None:
                    start = lineno
                size = sum(len(x) + 1 for x in buf)
                if buf and size + len(raw) > hard:
                    flush()
                    start = lineno
                buf.append(raw)
                end = lineno
                if sum(len(x) + 1 for x in buf) >= target:
                    flush()
            flush()

    def find_passages(self, keywords, min_shared=2, top=8):
        kws = set(keywords)
        scored = []
        for p in self.passages:
            shared = kws & p["tokens"]
            if len(shared) >= min_shared:
                scored.append((len(shared), p))
        scored.sort(key=lambda r: (-r[0], r[1]["fname"], r[1]["start"]))
        return [p for _n, p in scored[:top]]

    def _ingest_any(self, path):
        if not path.is_file():
            return
        ext = path.suffix.lower()
        if ext in (".md", ".txt", ".csv"):
            self.files.append(path.name)
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    return
                self._ingest(sniff_bytes(path.read_bytes()), path.name, "line")
            except OSError:
                return
        elif ext == ".pdf":
            self._ingest_pdf(path)
        elif ext == ".docx":
            self._ingest_docx(path)

    def _ingest(self, text, name, precision, page=None):
        for i, line in enumerate(text.splitlines()[:MAX_LINES_PER_FILE], 1):
            if not line.strip():
                continue
            toks = tp.tokens(line)
            ref = f"{name} p.{page}" if page is not None else name
            idx = len(self.lines)
            self.lines.append((ref, i, line.strip(), toks, precision))
            for t in toks:
                self.df[t] = self.df.get(t, 0) + 1
                self.posting.setdefault(t, []).append(idx)

    def _ingest_pdf(self, path):
        try:
            import pymupdf
        except ImportError:
            return  # degraded: skip PDFs silently, web/BYOS-text still work
        self.files.append(path.name)
        try:
            with pymupdf.open(str(path)) as doc:
                for pno, page in enumerate(doc, 1):
                    self._ingest(page.get_text(), path.name, "page", page=pno)
        except Exception:
            return

    def _ingest_docx(self, path):
        try:
            from docx import Document
        except ImportError:
            return
        self.files.append(path.name)
        try:
            d = Document(str(path))
        except Exception:
            return
        self._ingest("\n".join(p.text for p in d.paragraphs), path.name, "para")

    def __len__(self):
        return len(self.lines)

    def rare_tokens(self, text, k=8):
        """Subject keywords for search, restricted to tokens present in corpus,
        ranked rarest-first; expanded across alias maps (EN claim -> ZH source).
        k=8: a top-4 budget let descriptive words crowd out entity words in
        topic-rich docs (found by the blind LEGO test)."""
        toks = tp.tokens(text)
        if self.aliases:
            toks = self.aliases.expand_tokens(toks)
        cand = [t for t in toks
                if t not in tp.STOP and not t.isdigit() and len(t) > 1
                and self.df.get(t, 0) > 0]
        cand.sort(key=lambda t: (self.df[t], -len(t), t))
        return cand[:k]

    def find_lines(self, keywords, min_shared=1, top=12):
        if not keywords:
            return []
        kws = set(keywords)
        cand_ids = set()
        for t in kws:
            cand_ids.update(self.posting.get(t, ()))
        scored = []
        for idx in cand_ids:
            fname, lineno, raw, toks, precision = self.lines[idx]
            shared = kws & toks
            if len(shared) >= min_shared:
                scored.append((len(shared), fname, lineno, raw, sorted(shared), precision))
        scored.sort(key=lambda r: (-r[0], r[1], r[2]))
        return scored[:top]

    def find_literal_lines(self, terms, top=20):
        """Exact substring lane: the Ctrl+F a human would run.

        Token search splits CJK into bigrams, so a phrase like
        "文化不是虚无缥缈" can be missed when its pieces are common. This lane
        checks the normalized line text for each term verbatim, ranks by
        rarity x length, and is deterministic/offline. It is a *lead*
        retriever only; it never produces a verdict.
        """
        terms = [tp.normalize(t) for t in dict.fromkeys(terms or ()) if t]
        terms = [t for t in terms if len(t) >= 2]
        if not terms:
            return []
        cand = set()
        for t in terms:
            cand.update(self.posting.get(t, ()))
        ids = cand if cand else range(len(self.lines))
        scored = []
        for idx in ids:
            fname, lineno, raw, _toks, precision = self.lines[idx]
            norm = self.norm_lines[idx]
            hits = [t for t in terms if t in norm]
            if not hits:
                continue
            score = sum((1.0 / max(1, self.df.get(t, 1))) * min(len(t), 8)
                        for t in hits)
            scored.append((score, fname, lineno, raw, hits, precision))
        scored.sort(key=lambda r: (-r[0], r[1], r[2]))
        return scored[:top]

    def _passage_for_line(self, fname, lineno):
        for p in self.passages:
            if (p["fname"] == fname
                    and p["start"] <= lineno <= p["end"]):
                return p
        return None

    def _source_file_scores(self, text):
        """Top two source files by content overlap (soft topic prior).

        Uses the claim's content tokens and inverse document frequency; the
        final score is length-normalised so a huge file cannot win by size
        alone. This is a retrieval signal, never evidence.
        """
        qt = {t for t in tp.tokens(text)
              if t not in tp.STOP and len(t) > 1}
        if not qt or not self.file_tokens:
            return []
        vals = []
        for fname, ftoks in self.file_tokens.items():
            shared = qt & ftoks
            if not shared:
                continue
            raw = sum(1.0 / max(1, self.df.get(t, 1)) for t in shared)
            vals.append((raw / (len(ftoks) ** 0.5 or 1.0), fname))
        vals.sort(key=lambda x: (-x[0], x[1]))
        return [fname for _score, fname in vals[:2]]

    def find_prose_candidates(self, text, top=5):
        """Rank passages/lines for a prose claim (a lead, never a verdict).

        Three lanes merged, because each fails differently:
        - BM25 passages: word overlap, but common words dilute the query;
        - rare-token passages: subject keywords, not the first 8 tokens;
        - exact substring lines: the Ctrl+F lane (names, quotes, slogans).
        Exact/rare evidence is weighted above BM25; every returned item keeps
        its original fname/start/end, so evidence locators never move.
        """
        text = (text or "").strip()
        if not text:
            return []
        rare = self.rare_tokens(text, k=12)
        clues = tp.clue_terms(text)
        top_files = self._source_file_scores(text)
        if not rare and not clues:
            return []

        pool, seen = [], set()

        def add(base, p, lane):
            key = (p.get("fname"), p.get("start"))
            if key in seen:
                return
            seen.add(key)
            pool.append((float(base), p, lane))

        if self.bm25.ok:
            bm_pool = self.bm25.search(text, top=max(top * 8, 24))
            # use the same bounded filename/heading rerank as find_bm25_passages;
            # a source whose title names the claim's subject should win a
            # near-tie against a better-worded but off-subject paragraph
            bm_scores = {id(p): s for s, p in bm_pool}
            for p in _field_rerank(set(tp.tokens(text)), bm_pool):
                add(bm_scores.get(id(p), 0.0), p, "bm25")
        for p in self.find_passages(rare, min_shared=2, top=12):
            add(0.0, p, "rare")
        for _s, fname, lineno, raw, _hits, precision in self.find_literal_lines(
                rare, top=24):
            p = self._passage_for_line(fname, lineno)
            if p is not None:
                add(0.0, p, "literal")
            else:
                add(0.0, {"fname": fname, "start": lineno, "end": lineno,
                          "text": raw, "tokens": tp.tokens(raw),
                          "precision": precision}, "literal")
        # Clue lane: figures with units ('28元', '3.2英寸'), quoted phrases,
        # all-caps names/codes and CJK runs. This is the Ctrl+F a reader would
        # run; it must survive even when the generic rare-token ranking loses
        # the exact line.
        for clue in clues:
            for _s, fname, lineno, raw, _hits, precision in self.find_literal_lines(
                    [clue], top=8):
                p = self._passage_for_line(fname, lineno)
                if p is not None:
                    add(0.0, p, "clue")
                else:
                    add(0.0, {"fname": fname, "start": lineno, "end": lineno,
                              "text": raw, "tokens": tp.tokens(raw),
                              "precision": precision}, "clue")

        claim_norm = tp.normalize(text)
        scored = []
        for base, p, lane in pool:
            ptoks = p.get("tokens") or set()
            ptext = tp.normalize(p.get("text") or "")
            rare_hits = [t for t in rare if t in ptoks]
            lit_hits = [t for t in rare if len(t) >= 2 and t in ptext]
            rare_score = sum(1.0 / max(1, self.df.get(t, 1))
                             for t in rare_hits)
            lit_score = sum(1.0 / max(1, self.df.get(t, 1))
                            for t in lit_hits)
            # A term that occurs once in the whole library is the closest
            # thing to the reader's Ctrl+F word ("肝病", "分貝儀"). A generic
            # term ("公司") must not get the same treatment.
            unique_hits = [t for t in rare_hits if self.df.get(t, 0) == 1]
            # Multi-term coverage: the awards/canteen sentence shares
            # "保安" AND "食堂"; a paragraph that shares only one common
            # word should not win.
            coverage = len(set(rare_hits))
            phrase_len = _longest_common_phrase(claim_norm, ptext)
            clue_hits = [c for c in clues if tp.normalize(c) in ptext]
            clue_score = sum(1.0 / max(1, self.df.get(t, 1))
                             for c in clue_hits for t in tp.tokens(c))
            fname = p.get("fname") or ""
            src_rank = top_files.index(fname) if fname in top_files else -1
            src_bonus = 8.0 if src_rank == 0 else 4.0 if src_rank == 1 else 0.0
            # A source whose filename names the claim's subject (金山) is a
            # better lead than a same-topic paragraph from another company
            # (西山志). Soft bonus only: it can break a near-tie, not invent
            # evidence, and it never changes fname/start.
            title_tokens = p.get("title_tokens") or _field_tokens(
                p.get("fname") or "")
            title_hits = list(set(tp.tokens(text)) & set(title_tokens))
            # exact phrase > unique term > multi-term coverage > title match
            # > BM25 base. All are retrieval signals, never evidence.
            score = (base + 4.0 * rare_score + 8.0 * lit_score
                     + 18.0 * len(unique_hits) + 3.0 * min(coverage, 6)
                     + 6.0 * len(title_hits)
                     + 40.0 * len(clue_hits) + 10.0 * clue_score
                     + src_bonus
                     + 0.5 * phrase_len * phrase_len)
            item = dict(p)
            item["score"] = round(score, 6)
            item["why"] = {"lane": lane, "rare": rare_hits[:6],
                           "literal": lit_hits[:6], "unique": unique_hits[:4],
                           "coverage": coverage, "title": title_hits[:4],
                           "clue": clue_hits[:4], "source": fname if src_rank >= 0 else "",
                           "phrase": phrase_len}
            scored.append(item)
        scored.sort(key=lambda p: (-p["score"], p.get("fname") or "",
                                   p.get("start") or 0))
        return scored[:top]

    def best_quote_match(self, quote):
        """(ratio, file, lineno, line, precision) of the most similar corpus line."""
        qn = tp.normalize(quote).rstrip(".!?").strip()
        qtoks = tp.tokens(quote)
        kws = self.rare_tokens(quote, k=3)
        cands = list(self.find_lines(kws, 1, top=20))
        if not cands:
            cands = [(0, f, n, r, [], p) for f, n, r, t, p in self.lines]
        best = (0.0, None, None, None, "line")
        qcore = {t for t in qtoks if len(t) > 2 or not t.isascii()}
        for _, fname, lineno, raw, _shared, precision in cands:
            # A section heading/title is not a spoken quote. The exact wording
            # can be a title and still be "verbatim"; supporting it as a quote
            # is a false green (e.g. '不怕死的决心和向死而生的勇气').
            if str(raw).lstrip().startswith("#"):
                continue
            # candidate must share some substance with the quote (avoid junk)
            if qcore and not (set(tp.tokens(raw)) & qcore):
                continue
            ln = tp.normalize(raw).rstrip(".!?").strip()
            if qn and qn in ln:
                ratio = 1.0
            else:
                ratio = _windowed_ratio(qn, ln) if qn and ln else 0.0
            if ratio > best[0]:
                best = (ratio, fname, lineno, raw, precision)
        return best
