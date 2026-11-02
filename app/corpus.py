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
    scored.sort(key=lambda r: -r[0])
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
        cand.sort(key=lambda t: (self.df[t], -len(t)))
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
