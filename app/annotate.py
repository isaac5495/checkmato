"""Annotated copy export (F7): the document with every verdict applied as a
highlight + a legend. Never edits the source — output is always a new file
(`<out>/annotated.docx` or `annotated.md`), matching the project convention:
tracked-change-style suggestions, never silent edits."""
import re
from pathlib import Path

COLORS = {  # verdict -> (docx highlight name, hex for md)
    "contradicted": ("RED", "#FFC7CE"),
    "internal_conflict": ("PINK", "#FFD9E8"),
    "misattributed": ("DARK_YELLOW", "#FFD966"),
    "conflicting": ("TURQUOISE", "#FCD5B4"),
    "paraphrase_flag": ("YELLOW", "#FFEB9C"),
    "needs_fix": ("YELLOW", "#FFEB9C"),
    "structure": ("YELLOW", "#FFEB9C"),
    "supported": ("BRIGHT_GREEN", "#C6EFCE"),
}


def _locate(findings, paragraphs):
    """(para_idx, start, end, verdict) for every highlightable finding,
    overlap-resolved (first wins)."""
    marks = {}
    for x in findings:
        v = x["verdict"]
        if v not in COLORS or x.get("para") is None:
            continue
        if not (0 <= x["para"] < len(paragraphs)):
            continue
        text = paragraphs[x["para"]]
        needle = x["raw"]
        s = x.get("span")
        i = -1
        if x.get("anchored") and s and text[s[0]:s[1]] == needle:
            i = s[0]  # exact anchor from the engine (M1 hover contract)
        if i < 0:
            i = text.find(needle)
        if i < 0:
            i = text.lower().find(needle.lower())
        if i < 0:
            continue
        marks.setdefault(x["para"], []).append((i, i + len(needle), v))
    resolved = {}
    for pidx, spans in marks.items():
        spans.sort()
        kept, last = [], -1
        for a, b, v in spans:
            if a >= last:
                kept.append((a, b, v))
                last = b
        resolved[pidx] = kept
    return resolved


def annotate_docx(src_path, findings, paragraphs, out_path):
    """Highlight by TEXT LOCATION, not paragraph index: the engine sees tables
    and notes flattened into the paragraph stream, so indices don't line up
    with docx's own paragraph list. Any real w:p (body or table cell) that
    carries the finding's wording gets the mark."""
    from docx import Document
    from docx.enum.text import WD_COLOR_INDEX
    from docx.text.paragraph import Paragraph
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    doc = Document(str(src_path))
    pobjs = [Paragraph(el, doc) for el in doc.element.body.iter(ns + "p")]
    ptexts = [p.text for p in pobjs]
    marks = {}
    for x in findings:
        v = x["verdict"]
        needle = x.get("raw") or ""
        if v not in COLORS or x.get("para") is None or not needle:
            continue
        i = next((k for k, t in enumerate(ptexts)
                  if needle in t or needle.lower() in t.lower()), None)
        if i is None:
            continue
        t = ptexts[i]
        a = t.find(needle)
        if a < 0:
            a = t.lower().find(needle.lower())
        marks.setdefault(i, []).append((a, a + len(needle), v))
    for pidx in list(marks):  # overlap-resolve, first wins
        spans = sorted(marks[pidx])
        kept, last = [], -1
        for a, b, v in spans:
            if a >= last:
                kept.append((a, b, v))
                last = b
        marks[pidx] = kept
    for pidx, spans in marks.items():
        p = pobjs[pidx]
        text = p.text
        segs, pos = [], 0
        for a, b, v in spans:
            if a > pos:
                segs.append((text[pos:a], None))
            segs.append((text[a:b], v))
            pos = b
        if pos < len(text):
            segs.append((text[pos:], None))
        for el in list(p._p):
            if not el.tag.endswith("}pPr"):
                p._p.remove(el)
        for chunk, verdict in segs:
            run = p.add_run(chunk)
            if verdict:
                run.font.highlight_color = getattr(WD_COLOR_INDEX, COLORS[verdict][0])
    doc.add_paragraph("")
    doc.add_paragraph("— Annotated by CheckMato (suggestions copy; original "
                      "untouched). Every pending item needs your review. —")
    legend = {v: sum(1 for spans in marks.values() for s in spans if s[2] == v)
              for v in COLORS}
    doc.add_paragraph("Legend: " + " · ".join(f"{v}: {n}" for v, n in legend.items() if n))
    doc.save(str(out_path))


def annotate_md(src_path, findings, paragraphs, out_path):
    raw = Path(src_path).read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(\n\s*\n)", raw)  # alternating content / separator
    content_idx = [i for i, b in enumerate(blocks) if b.strip()]
    para_to_block = {pi: bi for pi, bi in enumerate(content_idx)}
    out = list(blocks)
    for pidx, spans in _locate(findings, paragraphs).items():
        bi = para_to_block.get(pidx)
        if bi is None:
            continue
        b = blocks[bi]
        segs, pos = [], 0
        for a, e, v in spans:
            segs.append(b[pos:a])
            segs.append(f'<mark style="background:{COLORS[v][1]}">{b[a:e]}</mark>')
            pos = e
        segs.append(b[pos:])
        out[bi] = "".join(segs)
    Path(out_path).write_text("".join(out) +
                              "\n\n---\n*Annotated by CheckMato — suggestions "
                              "copy; original untouched.*\n", encoding="utf-8")
