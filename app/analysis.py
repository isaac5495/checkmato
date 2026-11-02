"""Explain every non-supported outcome of a BYOS run, in a portable docx.

The point is diagnosis, not scoring: for each verdict the report says what the
engine saw (note), what it retrieved (top candidate), and which general rule
would have changed the outcome. No case answers are written into code; the
examples come from the run's own files.

Usage:
  python -m app.cli analyze <run>/claims.jsonl --library <dir|toml> --out report.docx
"""
import json
from collections import Counter, OrderedDict
from pathlib import Path

from docx import Document
from docx.shared import Pt

from .library import Library

CATEGORIES = OrderedDict([
    ("narrative", "Narrative / eligibility (intentional, not a miss)"),
    ("no_source_prose", "Prose: no deterministic check was run (not a failed match)"),
    ("no_source_number", "No source: checkable claim, nothing retrieved"),
    ("value_missing", "Unverified: subject found, the value was not confirmed"),
    ("event_mismatch", "Unverified: value found, but the source milestone differs"),
    ("demoted_other_value", "Contradiction demoted: a different value on the page"),
    ("demoted_other_year", "Contradiction demoted: a different year, other milestone"),
    ("demoted_other_subject", "Contradiction demoted: another named subject"),
    ("quote_similarity", "Unverified quote: closest source text is only a paraphrase"),
    ("contradicted", "Contradicted (kept: name/event checks passed)"),
    ("internal_conflict", "Document-internal conflict (not a source verdict)"),
    ("deferred_web", "URL liveness deferred (web-only check)"),
    ("paraphrase_flag", "Quote differs from every source (flagged, not rejected)"),
])


def _category(r):
    v = r["verdict"]
    note = (r.get("notes") or "").strip()
    if v == "narrative":
        return "narrative"
    if v == "no_source":
        return "no_source_prose" if r["type"] in ("event", "sentence") \
            else "no_source_number"
    if v == "contradicted":
        return "contradicted"
    if v == "internal_conflict":
        return "internal_conflict"
    if v == "deferred_web":
        return "deferred_web"
    if v == "paraphrase_flag":
        return "paraphrase_flag"
    if v == "unverified":
        if note.startswith("Prose claim"):
            return "no_source_prose"
        if note.startswith("No subject keyword") or note.startswith("No corpus line"):
            return "no_source_number"
        if "value not confirmed" in note or "does not settle" in note:
            return "value_missing"
        if "different event" in note or "same milestone" in note:
            return "event_mismatch"
        if note.startswith("A source page carries"):
            return "demoted_other_value"
        if note.startswith("A source line carries"):
            return "demoted_other_year"
        if note.startswith("A source line contradicts"):
            return "demoted_other_subject"
        if note.startswith("Best corpus similarity"):
            return "quote_similarity"
    return "value_missing"


def _top_candidate(corpus, sentence):
    kws = corpus.rare_tokens(sentence or "", k=8)
    lines = corpus.find_lines(kws, 1, 3)
    if not lines:
        return "—", kws
    _shared, fname, lineno, raw, _sh, _prec = lines[0]
    return f"{fname}:{lineno} — {raw[:220]}", kws


def analyze(claims_path, library_path):
    rows = [json.loads(line) for line in
            open(claims_path, encoding="utf-8")]
    lib = Library(library_path)
    groups = OrderedDict((k, []) for k in CATEGORIES)
    for r in rows:
        if r["verdict"] == "supported":
            continue
        groups.setdefault(_category(r), []).append(r)
    counts = Counter(r["verdict"] for r in rows)
    return rows, lib, groups, counts


def _add_table(doc, header, rows, widths=None):
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(header):
        hdr[i].text = h
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)[:600]
    return table


def write_report(rows, lib, groups, counts, out_docx):
    doc = Document()
    doc.styles["Normal"].font.size = Pt(9)
    doc.add_heading("BYOS: why items were not supported", level=0)
    doc.add_paragraph(
        f"Run: {Path(out_docx).name} · {len(rows)} findings · library "
        f"{len(lib.sources)} sources / {len(lib.corpus)} lines. "
        "Every example below is taken from this run; the engine has no "
        "case-specific rules, so the fixes are stated as general rules.")
    doc.add_heading("Verdict counts", level=1)
    _add_table(doc, ["Verdict", "Count"],
               sorted(counts.items(), key=lambda kv: -kv[1]))
    doc.add_heading("Diagnosis by outcome", level=1)
    for key, title in CATEGORIES.items():
        items = groups.get(key) or []
        if not items:
            continue
        doc.add_heading(f"{title} — {len(items)}", level=2)
        doc.add_paragraph(_diagnosis(key, items))
        sample = []
        for r in items[:5]:
            top, kws = _top_candidate(lib.corpus, r.get("context")
                                      or r["quote"])
            sample.append((r["quote"][:80], r["type"],
                           (r.get("notes") or "")[:160], top))
        _add_table(doc, ["Claim", "Type", "Engine note", "Top candidate line"],
                   sample)
        doc.add_paragraph("")
    doc.add_heading("General fixes this analysis points to", level=1)
    for line in FIXES:
        doc.add_paragraph(line, style="List Bullet")
    out = Path(out_docx)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


def _diagnosis(key, items):
    n = len(items)
    if key == "narrative":
        return ("Eligibility floor: headings, questions and citations are "
                "kept visible but are not checkable claims. This is correct "
                "behaviour, not a miss.")
    if key == "no_source_prose":
        return (f"{n} prose sentences have no deterministic checker (no "
                "figure or quote). They are left unverified with the nearest "
                "passage as a lead, so the reader can see what was found "
                "without the engine pretending it proved the sentence.")
    if key == "no_source_number":
        return (f"{n} checkable claims retrieved no candidate line. Either "
                "the library lacks the fact, or retrieval missed it (long "
                "Chinese sentences, different wording, chunk boundaries).")
    if key == "value_missing":
        return (f"{n} claims found a line about the subject but not the exact "
                "value. Common causes: the value is in the next passage, is "
                "written in another unit/format, or the sentence has several "
                "figures and the matcher picked the wrong one.")
    if key == "event_mismatch":
        return (f"{n} claims found the figure on a line about a different "
                "milestone. The predicate guard is working; this is a "
                "retrieval problem (wrong line ranked first).")
    if key == "demoted_other_value":
        return ("A conflicting value was found, but the page shared no "
                "distinctive term with the sentence. Kept unverified instead "
                "of a false contradiction.")
    if key == "demoted_other_year":
        return ("A different year exists, but neither side names the same "
                "milestone. Kept unverified.")
    if key == "demoted_other_subject":
        return ("The conflicting line names a different entity. Kept "
                "unverified.")
    if key == "quote_similarity":
        return ("Quoted text is not present verbatim; the closest source "
                "passage is a paraphrase. The engine refuses to upgrade a "
                "paraphrase to a quote match.")
    if key == "contradicted":
        return ("Kept as contradictions: same event label and a distinctive "
                "shared term. Inspect these first; entity/venue collisions are "
                "the known residual.")
    if key == "internal_conflict":
        return ("These compare values inside the draft, not against sources. "
                "On a long bilingual case study the grouping can pair "
                "different metrics that share generic words.")
    if key == "deferred_web":
        return ("URL claims need a liveness probe, which sources_only cannot "
                "run. Honest deferral, not a failed match.")
    if key == "paraphrase_flag":
        return ("Quote differs from the source wording but is close; flagged "
                "for a human rather than rejected.")
    return ""


FIXES = [
    "Eligibility before retrieval (implemented 2026-10-28): docx headings and "
    "footnote citations are classified before judging.",
    "Say what actually happened (implemented 2026-10-28): a prose claim that "
    "was never checked stays 'unverified' with a lead passage, not 'no source'.",
    "Local, unit-aware internal conflicts (implemented 2026-10-28): counts need "
    "the same unit; amounts/percentages must be near and share a metric word.",
    "Entity proximity for year contradictions (implemented 2026-10-28): the "
    "year must sit next to the claim's own subject in the cited line.",
    "Still open: entity proximity for amount/percentage contradictions; a "
    "figure can still be the wrong metric on the same page.",
    "Still open: overlapping passages (a fact can straddle a chunk boundary) "
    "and figure-first candidate ranking; this is the main remaining recall gap.",
    "Still open: numeric formatting normalisation (spaces/thousands "
    "separators, 万/亿) before comparison.",
]


def write_markdown(rows, lib, groups, counts, out_md):
    lines = ["# BYOS: why items were not supported", "",
             f"{len(rows)} findings · {len(lib.sources)} sources / "
             f"{len(lib.corpus)} lines", "", "## Verdict counts", ""]
    for v, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {v}: {n}")
    for key, title in CATEGORIES.items():
        items = groups.get(key) or []
        if not items:
            continue
        lines += ["", f"## {title} — {len(items)}", "",
                  _diagnosis(key, items), ""]
        for r in items[:5]:
            top, _kws = _top_candidate(lib.corpus, r.get("context") or r["quote"])
            lines.append(f"- **{r['quote'][:80]}** ({r['type']}) — "
                         f"{(r.get('notes') or '')[:140]}")
            lines.append(f"  - top: {top}")
    out = Path(out_md)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
