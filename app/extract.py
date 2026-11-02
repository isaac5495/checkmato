import logging
import re
import zipfile
from pathlib import Path

from . import textproc as tp
from .normalize import split_compound

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
        headings = []
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                para = Paragraph(child, doc)
                t = para.text.strip()
                if t:
                    if (para.style.name or "").startswith("Heading"):
                        headings.append(len(paragraphs))
                    paragraphs.append(t)
            elif tag == "tbl":
                for row in Table(child, doc).rows:
                    cells = [" ".join(c.text.split()) for c in row.cells]
                    line = " | ".join(c for c in cells if c)
                    if line.strip(" |"):
                        paragraphs.append(line)
        raw = "\n\n".join(paragraphs)
        refs, defs = _docx_footnotes(path)
        # WHERE each reference sits: the audit needs the anchor paragraph, not
        # just the id list. Indices are mapped to the flattened body, because
        # the raw XML walk also counts empty and table paragraphs.
        anchors = _docx_footnote_anchors(path)
        for a in anchors:
            a["para"] = _map_para(paragraphs, a.get("para_text", ""))
        # text boxes / callout shapes live outside the paragraph flow but ARE
        # counted by Word — and case studies hide key figures in them
        have = {p.strip() for p in paragraphs}
        paragraphs += _textbox_texts(path, have)
        # footnote/endnote text is counted by Word too; the citations inside
        # them carry URLs worth liveness-checking
        paragraphs += _footnote_texts(path)
        raw = "\n\n".join(paragraphs)
        return {"fmt": ext, "paragraphs": paragraphs, "raw_text": raw,
                "footnote_refs": refs, "footnote_defs": defs,
                "footnote_anchors": anchors, "heading_paras": headings}
    raw = path.read_text(encoding="utf-8", errors="replace")
    paragraphs = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    refs, defs = _md_footnotes(raw)
    return {"fmt": ext, "paragraphs": paragraphs, "raw_text": raw,
            "footnote_refs": refs, "footnote_defs": defs,
            "footnote_anchors": _md_footnote_anchors(paragraphs),
            "heading_paras": [i for i, p in enumerate(paragraphs)
                              if p.startswith("#")]}


def _md_footnote_anchors(paragraphs):
    """[{id, para, offset, para_text}] for `[^id]` references in markdown."""
    out = []
    for i, p in enumerate(paragraphs):
        if re.match(r"^\[\^[^\]]+\]:", p):
            continue  # definition line, not a reference
        for m in re.finditer(r"\[\^([^\]\s:]+)\](?!:)", p):
            out.append({"id": m.group(1), "para": i, "offset": m.start(),
                        "para_text": p})
    return out


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


def _map_para(paragraphs, text):
    """Index of the flattened paragraph this XML paragraph became, or None."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        return paragraphs.index(t)
    except ValueError:
        pass
    head = t[:80]
    for i, p in enumerate(paragraphs):
        if p.startswith(head):
            return i
    return None


def _docx_footnote_anchors(path):
    """[{id, para, offset, para_text}] for every reference, in display order.

    Offset is the character position of the reference inside its paragraph, so
    the auditor can quote the clause the footnote is actually attached to.
    """
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            from lxml import etree
            if "word/document.xml" not in z.namelist():
                return out
            root = etree.fromstring(z.read("word/document.xml"))
            for p in root.iter(ns + "p"):
                text, found = "", []
                for el in p.iter():
                    if el.tag == ns + "t":
                        text += el.text or ""
                    elif el.tag == ns + "footnoteReference":
                        fid = el.get(ns + "id")
                        if fid not in ("-1", "0"):
                            found.append({"id": fid, "offset": len(text),
                                          "para_text": ""})
                for a in found:
                    a["para_text"] = text
                    out.append(a)
    except Exception as e:
        log.warning("docx footnote anchors failed for %s: %s", path, e)
    return out


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
    """Every CLAUSE is a claim: if a clause produced NO checkable item (no
    number, quote, URL...), the clause itself becomes one 'event' claim so it
    gets checked like everything else. 'WPS was a word processor' must not
    escape checking just because it contains no digits.

    Compound sentences are split (`normalize.split_compound`) so one clause's
    figure does not hide the other clause's prose: "Foo opened a plant in
    2011, and it hired 200 staff" yields the two numeric claims AND an event
    claim for the remaining clause. The displayed `sentence` stays the original
    sentence; `raw` and `span` point at the clause, so the hover contract is
    unchanged.
    """
    covered = {}
    for c in claims:
        covered.setdefault(c["para"], []).append(tuple(c["span"]))
    for pidx, para in enumerate(paragraphs):
        spans = covered.get(pidx, [])
        for sent, off in tp.sentences_spans(para):
            if len(sent) < 30 or not any(ch.isalpha() for ch in sent):
                continue
            for part, start, end in split_compound(sent):
                part = part.strip()
                if len(part) < 20 or not any(ch.isalpha() for ch in part):
                    continue  # a fragment ("and he left") is not a claim
                at = sent.find(part, start, end)
                if at < 0:
                    at = sent.find(part)
                if at < 0:
                    continue
                lo, hi = off + at, off + at + len(part)
                if any(s >= lo and e <= hi for s, e in spans):
                    continue  # a claim already lives inside this clause
                raw = part[:200]
                add("event", raw, None, None, sent, pidx, (lo, lo + len(raw)))
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
