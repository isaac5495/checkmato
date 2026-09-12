import logging
from pathlib import Path

from . import textproc as tp

log = logging.getLogger("checkmato.corpus")

VERBATIM_CUT = 0.98
PARAPHRASE_CUT = 0.62
MAX_FILE_BYTES = 40 * 1024 * 1024      # skip runaway single files
MAX_LINES_PER_FILE = 200_000           # hard memory guard


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


class Corpus:
    """BYOS (bring-your-own-sources) line index over .md/.txt/.csv plus PDF and
    DOCX extraction (pdf→page precision, docx→paragraph precision).

    Retrieval: inverted token index -> line scoring -> difflib quote matching.
    Deterministic and order-stable; evidence clipped for display, refs precise.
    """

    def __init__(self, root, aliases=None):
        self.root = Path(root) if root else None
        self.aliases = aliases  # names.AliasMap or None
        self.lines = []          # (file, lineno, raw, token_set, precision)
        self.posting = {}        # token -> [line_index, ...]
        self.files = []
        self.df = {}
        if self.root and self.root.exists():
            for p in sorted(self.root.rglob("*")):
                self._ingest_any(p)

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
