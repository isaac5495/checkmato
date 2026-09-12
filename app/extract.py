import logging
import re
import zipfile
from pathlib import Path

from . import textproc as tp

log = logging.getLogger("checkmato.extract")


def read_doc(path):
    """Return dict {fmt, paragraphs, raw_text, footnote_refs, footnote_defs}.

    Walks the body IN ORDER and flattens tables (Word counts them; python-docx's
    .paragraphs skips them — a case-study's financial tables are exactly where
    the checkable numbers live, so they must be visible to extraction)."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        doc = Document(str(path))
        paragraphs = []
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                t = Paragraph(child, doc).text.strip()
                if t:
                    paragraphs.append(t)
            elif tag == "tbl":
                for row in Table(child, doc).rows:
                    cells = [" ".join(c.text.split()) for c in row.cells]
                    line = " | ".join(c for c in cells if c)
                    if line.strip(" |"):
                        paragraphs.append(line)
        raw = "\n\n".join(paragraphs)
        refs, defs = _docx_footnotes(path)
        # text boxes / callout shapes live outside the paragraph flow but ARE
        # counted by Word — and case studies hide key figures in them
        have = {p.strip() for p in paragraphs}
        paragraphs += _textbox_texts(path, have)
        # footnote/endnote text is counted by Word too; the citations inside
        # them carry URLs worth liveness-checking
        paragraphs += _footnote_texts(path)
        raw = "\n\n".join(paragraphs)
        return {"fmt": ext, "paragraphs": paragraphs, "raw_text": raw,
                "footnote_refs": refs, "footnote_defs": defs}
    raw = path.read_text(encoding="utf-8", errors="replace")
    paragraphs = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    refs, defs = _md_footnotes(raw)
    return {"fmt": ext, "paragraphs": paragraphs, "raw_text": raw,
            "footnote_refs": refs, "footnote_defs": defs}


def _md_footnotes(raw):
    uses = re.findall(r"\[\^([^\]\s:]+)\](?!:)", raw)
    defs = re.findall(r"^\[\^([^\]]+)\]:", raw, re.M)
    return uses, defs


def _textbox_texts(path, have):
    """Text from Word text boxes / DrawingML shapes (not part of the body
    paragraph flow but counted by MS Word's word count)."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            if "word/document.xml" not in z.namelist():
                return out
            from lxml import etree
            root = etree.fromstring(z.read("word/document.xml"))
            for tb in root.iter(ns + "txbxContent"):
                txt = " ".join(" ".join((t.text or "") for t in tb.iter(ns + "t")).split())
                if txt and txt not in have:
                    have.add(txt)
                    out.append(txt)
    except Exception as e:
        log.warning("docx text-box extraction failed for %s: %s", path, e)
    return out


def _footnote_texts(path):
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            from lxml import etree
            for part, tag in (("word/footnotes.xml", "footnote"),
                              ("word/endnotes.xml", "endnote")):
                if part not in z.namelist():
                    continue
                root = etree.fromstring(z.read(part))
                for fn in root.iter(ns + tag):
                    if fn.get(ns + "id") in ("-1", "0"):
                        continue
                    txt = " ".join(" ".join((t.text or "")
                                            for t in fn.iter(ns + "t")).split())
                    if txt:
                        out.append(f"[{tag} {fn.get(ns + 'id')}] {txt}")
    except Exception as e:
        log.warning("docx footnote/endnote extraction failed for %s: %s", path, e)
    return out


def _docx_footnotes(path):
    """Reference ids (display order) from document.xml; definition ids from footnotes.xml.

    Ids -1 (separator) and 0 (continuation) are internal and always excluded.
    """
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        from lxml import etree
        names = set(z.namelist())
        refs = []
        if "word/document.xml" in names:
            doc = etree.fromstring(z.read("word/document.xml"))
            refs = [r.get(ns + "id") for r in doc.iter(ns + "footnoteReference")
                    if r.get(ns + "id") not in ("-1", "0")]
        defs = []
        if "word/footnotes.xml" in names:
            fns = etree.fromstring(z.read("word/footnotes.xml"))
            defs = [f.get(ns + "id") for f in fns.iter(ns + "footnote")
                    if f.get(ns + "id") not in ("-1", "0")]
    return refs, defs


def extract_claims(paragraphs):
    """Deterministic claim extraction: every factual assertion worth checking.

    Types: quote | year | amount | pct | count | placeholder | url
    Each claim: {id, type, raw, value, currency, sentence, para, span}
    """
    claims = []
    n = 0

    def add(ctype, raw, value, currency, sentence, para, span):
        nonlocal n
        n += 1
        claims.append({
            "id": f"c{n:03d}", "type": ctype, "raw": raw.strip(),
            "value": value, "currency": currency,
            "sentence": sentence, "para": para, "span": list(span),
        })

    for pidx, para in enumerate(paragraphs):
        for sent, off in tp.sentences_spans(para):
            for m in tp.QUOTE_RE.finditer(sent):
                add("quote", m.group(1), None, None, sent, pidx,
                    (m.start(1) + off, m.end(1) + off))
            for v in tp.extract_values(sent):
                add(v["kind"], v["raw"], v["value"], v["currency"], sent, pidx,
                    (v["start"] + off, v["end"] + off))
        for rx in tp.PLACEHOLDER_RES:
            for m in rx.finditer(para):
                add("placeholder", m.group(0), None, None, para, pidx, m.span())
        for m in tp.URL_RE.finditer(para):
            add("url", m.group(0), None, None, para, pidx, m.span())
    _inject_sentences(paragraphs, claims, add)
    deduped, seen = [], set()
    for c in claims:
        key = (c["type"], c["raw"], c["para"], c["span"][0])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    _finalize_anchors(deduped, paragraphs)
    return deduped


def _inject_sentences(paragraphs, claims, add):
    """Every sentence is a claim: if a sentence produced NO checkable item
    (no number, quote, URL...), the sentence itself becomes one 'event' claim
    so it gets web-checked like everything else. 'WPS was a word processor'
    must not escape checking just because it contains no digits."""
    covered = {}
    for c in claims:
        covered.setdefault(c["para"], []).append(tuple(c["span"]))
    for pidx, para in enumerate(paragraphs):
        spans = covered.get(pidx, [])
        for sent, off in tp.sentences_spans(para):
            if len(sent) < 30 or not any(ch.isalpha() for ch in sent):
                continue  # headings, bullets, fragments
            lo, hi = off, off + len(sent)
            if any(s >= lo and e <= hi for s, e in spans):
                continue  # a claim already lives inside this sentence
            add("event", sent[:200], None, None, sent, pidx, (0, min(len(sent), 200)))
            claims[-1]["origin"] = "sentence"


def _finalize_anchors(claims, paragraphs):
    """Guarantee paragraphs[para][span[0]:span[1]] == raw (the M1 hover-highlight
    contract). Re-locate via exact then case-insensitive search when off-by-strip
    or sentence reconstruction shifted the span; else mark anchored=False."""
    for c in claims:
        para = paragraphs[c["para"]]
        s, e = c["span"]
        if para[s:e] == c["raw"]:
            c["anchored"] = True
            continue
        i = para.find(c["raw"], max(0, s - 5))
        if i < 0:
            i = para.find(c["raw"])
        if i < 0:
            i = para.lower().find(c["raw"].lower())
        if i >= 0:
            c["span"] = [i, i + len(c["raw"])]
            c["anchored"] = para[i:i + len(c["raw"])] == c["raw"]
        else:
            c["anchored"] = False
