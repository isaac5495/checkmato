"""BYOS source library: manifest + line/page locators.

A library is a folder plus a `library.toml` describing what each file IS. The
verdict engine needs two things the old corpus did not carry: which SOURCE a
line came from, and which PAGE it sits on. Both are stored here and attached to
the existing `Corpus` index, so `judge.py` keeps its line-level matching.

No case data lives in this module: discovery, suffixes and language detection
are generic. Everything source-specific belongs in the manifest the user edits.
"""
import json
import logging
import re
import tomllib
from pathlib import Path

from . import textproc as tp
from .corpus import Corpus, sniff_bytes

log = logging.getLogger("checkmato.library")

SKIP_DIRS = {".venv", "archive", "__pycache__", ".git", "node_modules",
             "reports", "logs"}
SOURCE_EXTS = {".md", ".txt", ".csv", ".pdf", ".docx"}
MIN_PAGE_CHARS = 10          # below this a PDF page has no usable text layer
MAX_LINE_MAP = 60            # chars of a line used to find its PDF page


def _slug(name):
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", Path(name).stem).strip("-")
    return s.lower() or "source"


def _language(text):
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if cjk >= max(10, latin // 4):
        return "zh"
    return "en" if latin else "unknown"


def _kind(path, size):
    n = path.name.lower()
    if "press" in n or "release" in n or "announce" in n:
        return "report"
    if "meeting" in n or "notes" in n or "interview" in n or "summary" in n:
        return "notes"
    return "book" if size > 100_000 else "report"


def _quote(v):
    return json.dumps(str(v), ensure_ascii=False)


class Library:
    """Sources + their locators. Build from a folder, or load a manifest."""

    def __init__(self, path, skip_hidden=True):
        self.path = Path(path)
        self.sources = []
        self.corpus = None
        self.page_map = {}            # (filename, lineno) -> page number | None
        self.no_text_layer = []       # [{"source_id", "path", "pages"}]
        self.manifest_path = None
        self.stats = {"sources": 0, "lines": 0}
        self._skip_hidden = skip_hidden
        if self.path.is_file():
            self.manifest_path = self.path
            self.root = self.path.parent
            self._load_manifest()
        elif self.path.is_dir():
            self.root = self.path
            guess = self.root / "library.toml"
            if guess.exists():
                self.manifest_path = guess
                self._load_manifest()
            else:
                self._discover()
        else:
            raise FileNotFoundError(f"library not found: {path}")
        self._build()

    # ---- manifest ----
    def _skip(self, p):
        if any(part in SKIP_DIRS for part in p.parts):
            return True
        if self._skip_hidden and p.name.startswith("."):
            return True
        return False

    def _discover(self):
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or self._skip(p):
                continue
            if p.suffix.lower() not in SOURCE_EXTS:
                continue
            if p.name.lower().startswith("library."):
                continue
            size = p.stat().st_size
            rel = p.relative_to(self.root).as_posix()
            self.sources.append({
                "id": _slug(rel.replace(".", "-")),
                "path": rel,
                "kind": _kind(p, size),
                "title": p.stem,
                "author": "",
                "year": 0,
                "language": "",
                "locator": "page" if p.suffix.lower() == ".pdf" else "line",
                "paired_path": self._paired(p),
                "derived_from": "",
            })

    def _paired(self, p):
        if p.suffix.lower() == ".pdf":
            for ext in (".md", ".txt", ".docx"):
                q = p.with_suffix(ext)
                if q.exists():
                    return q.relative_to(self.root).as_posix()
            return ""
        for ext in (".pdf",):
            q = p.with_suffix(ext)
            if q.exists():
                return q.relative_to(self.root).as_posix()
        return ""

    def _load_manifest(self):
        try:
            data = tomllib.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"could not parse {self.manifest_path}: {e}")
        for s in data.get("source", []):
            row = {
                "id": str(s.get("id") or _slug(s.get("path", "source"))),
                "path": str(s.get("path") or ""),
                "kind": str(s.get("kind") or "report"),
                "title": str(s.get("title") or Path(str(s.get("path"))).stem),
                "author": str(s.get("author") or ""),
                "year": int(s.get("year") or 0),
                "language": str(s.get("language") or ""),
                "locator": str(s.get("locator") or "line"),
                "paired_path": str(s.get("paired_path") or ""),
                "derived_from": str(s.get("derived_from") or ""),
            }
            if row["path"]:
                self.sources.append(row)

    def write_manifest(self, out):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = ["[library]",
                 f"id = {_quote(self.root.name)}",
                 f"name = {_quote(self.root.name)}",
                 "created = \"\""]
        for s in self.sources:
            lines += ["", "[[source]]"]
            for k in ("id", "path", "kind", "title", "author", "language",
                      "locator", "paired_path", "derived_from"):
                lines.append(f"{k} = {_quote(s.get(k, ''))}")
            lines.append(f"year = {int(s.get('year') or 0)}")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    def verify(self):
        """Check that every manifest path exists; report missing files."""
        missing, present = [], []
        for s in self.sources:
            p = self.root / s["path"]
            (present if p.exists() else missing).append(s["path"])
        return {"present": len(present), "missing": missing}

    def import_converted(self, converted, derived_from, out=None):
        """Register an externally converted copy of a scanned PDF.

        The converted file is the searchable text; `derived_from` keeps the
        provenance so a citation can say where the text really came from. The
        original PDF is never read or modified.
        """
        conv = Path(converted)
        if not conv.exists():
            raise FileNotFoundError(converted)
        path = conv.resolve().as_posix()
        for s in self.sources:
            if s["path"] == path:
                return s
        src = {
            "id": _slug(f"{conv.stem}-{conv.suffix.lstrip('.')}"),
            "path": path,
            "kind": "report",
            "title": conv.stem,
            "author": "",
            "year": 0,
            "language": _language(conv.read_text(encoding="utf-8",
                                                 errors="replace")[:20000])
            if conv.suffix.lower() in (".md", ".txt") else "",
            "locator": "line",
            "paired_path": "",
            "derived_from": Path(derived_from).resolve().as_posix(),
        }
        self.sources.append(src)
        target = Path(out) if out else (
            self.manifest_path or (self.root / "library.toml"))
        self.write_manifest(target)
        self.manifest_path = target
        return src

    # ---- index ----
    def _build(self):
        present = [s for s in self.sources if (self.root / s["path"]).exists()]
        self.sources = present
        paths = [self.root / s["path"] for s in present]
        self.corpus = Corpus(self.root, skip=self._skip, include_paths=paths)
        self.source_by_file = {}
        for s in self.sources:
            name = Path(s["path"]).name
            self.source_by_file[name] = s["id"]
            s["language"] = s["language"] or self._source_language(s)
        self.corpus.source_by_file = self.source_by_file
        self.corpus.sources = self.sources
        self._build_pages()
        self.corpus.page_map = self.page_map
        self.corpus.no_text_layer = self.no_text_layer
        self.stats = {"sources": len(self.sources), "lines": len(self.corpus)}

    def _source_language(self, s):
        p = self.root / s["path"]
        try:
            if p.suffix.lower() in (".md", ".txt", ".csv"):
                return _language(sniff_bytes(p.read_bytes())[:20000])
        except OSError:
            pass
        return ""

    def _pdf_pages(self, p):
        try:
            import pymupdf
        except ImportError:
            return None
        pages = []
        try:
            with pymupdf.open(str(p)) as doc:
                for pno, page in enumerate(doc, 1):
                    pages.append((pno, page.get_text()))
        except Exception as e:
            log.warning("pdf page map failed for %s: %s", p, e)
            return None
        return pages

    def _build_pages(self):
        """Map every line of a text source to the page of its paired PDF.

        Order is preserved (both come from the same document), so one forward
        scan over a normalized blob is enough; no per-line PDF search.
        """
        for s in self.sources:
            paired = s.get("paired_path") or ""
            own_pdf = Path(s["path"]).suffix.lower() == ".pdf"
            if not paired and not own_pdf:
                continue
            pdf = self.root / (paired if paired else s["path"])
            if pdf.suffix.lower() != ".pdf" or not pdf.exists():
                continue
            pages = self._pdf_pages(pdf)
            if pages is None:
                continue
            blank = [pno for pno, text in pages if len(text.strip()) < MIN_PAGE_CHARS]
            if blank:
                self.no_text_layer.append({
                    "source_id": s["id"], "path": pdf.name,
                    "pages": len(blank), "total_pages": len(pages)})
            if not paired:
                continue  # its own pages are already the citation locator
            blob, bounds = "", []
            for pno, text in pages:
                t = tp.normalize(text)
                bounds.append((len(blob), len(blob) + len(t), pno))
                blob += t + "\n"
            pos = 0
            name = Path(s["path"]).name
            for fname, lineno, raw, _toks, _prec in self.corpus.lines:
                if fname != name:
                    continue
                key = tp.normalize(raw)[:MAX_LINE_MAP]
                if not key:
                    continue
                idx = blob.find(key, pos)
                if idx < 0:
                    self.page_map[(fname, lineno)] = None
                    continue
                pos = idx
                self.page_map[(fname, lineno)] = next(
                    (pno for a, b, pno in bounds if a <= idx < b), None)

    # ---- lookup ----
    def source(self, source_id):
        return next((s for s in self.sources if s["id"] == source_id), None)

    def lines_of(self, source_id, kws, top=12):
        """Corpus lines restricted to one source (used by footnote auditing)."""
        name = next((Path(s["path"]).name for s in self.sources
                     if s["id"] == source_id), None)
        if not name:
            return []
        ids = {i for i, ln in enumerate(self.corpus.lines) if ln[0] == name}
        cand = set()
        for t in kws:
            cand.update(i for i in self.corpus.posting.get(t, ()) if i in ids)
        out = []
        for i in cand:
            f, n, raw, toks, prec = self.corpus.lines[i]
            out.append((len(set(kws) & toks), f, n, raw, prec))
        out.sort(key=lambda r: (-r[0], r[2]))
        return out[:top]


def check_manifest(path):
    lib = Library(path)
    info = lib.verify()
    return info, lib
