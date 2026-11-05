"""BYOS verdict layer: source-grounded claims and footnote auditing.

Sits after `judge()`: the line-level checks stay where they are, and this module
turns "no corpus match" into an honest `no_source`, attaches source ids and page
locators, and audits footnotes against the source each one cites.

Deterministic only. No model is called here.
"""
import logging
import re
from pathlib import Path

from . import textproc as tp
from .queries import hand_queries

log = logging.getLogger("checkmato.byos")

MODES = ("sources_then_web", "sources_only", "web_only")
NO_SOURCE_NOTE = "No supplied source covers this claim."


def _locator_of(ref, library):
    """(source_id, page) from 'name.md:12' or 'book.pdf p.3'."""
    if not ref:
        return None, None
    m = re.match(r"(.+?)\s+p\.(\d+)$", ref)
    if m:
        fname, page = m.group(1), int(m.group(2))
        return library.source_by_file.get(fname), page
    if ":" not in ref:
        return None, None
    fname, _, lineno = ref.rpartition(":")
    try:
        n = int(lineno)
    except ValueError:
        return None, None
    sid = library.source_by_file.get(fname)
    page = library.page_map.get((fname, n))
    return sid, page


def enrich_evidence(claim, library):
    """Attach source_id/page to every local evidence row (idempotent)."""
    for ev in claim.get("evidence") or []:
        if ev.get("kind") != "local":
            continue
        sid, page = _locator_of(ev.get("ref"), library)
        if sid and not ev.get("source_id"):
            ev["source_id"] = sid
        if sid and page is None:
            ev["page_unavailable"] = True  # honest: line only, no page map
        if page is not None and "page" not in ev:
            ev["page"] = page


def _year_near_name(claim, quote):
    """Is a year in the cited line stated next to the claim's own subject?"""
    names = [n for n in tp.name_tokens(claim.get("sentence") or "")
             if len(n) >= 2]
    if not names:
        return True
    q = tp.normalize(quote)
    for m in re.finditer(r"(?:19|20)\d{2}", q):
        window = q[max(0, m.start() - 40): m.end() + 40]
        if any(n in window for n in names):
            return True
    return False


def apply_byos(claims, library, mode):
    """Post-process judge output for a library run."""
    def _hand(c):
        """Pasteable queries for THIS claim: its own subject, figure, rarest
        terms. A library run has a corpus, so rarity is real, and a reader can
        paste them into a search box or the folder's Ctrl+F."""
        ents = (c.get("_doc_entities")
                or list(tp.name_tokens(c.get("sentence") or "")))
        return hand_queries(c, corpus=library.corpus, entities=ents)

    for c in claims:
        c["_mode"] = mode
        enrich_evidence(c, library)
        # A year on a book page is usually page CONTEXT, not a claim about that
        # year: "the 2011 results …" mentions many years. A contradiction is
        # only defensible when both sides name the same milestone. Otherwise the
        # reader gets 60 false alarms from unrelated paragraphs.
        if c.get("verdict") == "contradicted":
            ev = (c.get("evidence") or [{}])[0]
            quote = ev.get("quote") or ""
            names = tp.name_tokens(c.get("sentence") or "")
            specific = max(names, key=len) if names else ""
            shared = {t for t in (tp.tokens(c.get("sentence") or "")
                                  & tp.tokens(quote))
                      if len(t) > 1 and not t.isdigit() and t not in tp.STOP}
            rare = [t for t in shared
                    if library.corpus.df.get(t, 0) <= 3]
            if len(specific) >= 3 and specific not in tp.normalize(quote):
                c["verdict"] = "unverified"
                c["confidence"] = "low"
                c["suggestion"] = (
                    f"A source line contradicts a figure, but it is about a "
                    f"different named subject (not {specific}) — too weak to "
                    f"call a contradiction.")
            elif not rare:
                c["verdict"] = "unverified"
                c["confidence"] = "low"
                c["suggestion"] = (
                    "A source page carries a different value, but it shares no "
                    "distinctive term with this sentence — a contradiction "
                    "needs more than a shared year.")
            elif c.get("type") == "year":
                ce = tp.event_of(tp.normalize(c.get("sentence") or ""))
                le = tp.event_of(tp.normalize(quote))
                if not (ce and le and ce == le):
                    c["verdict"] = "unverified"
                    c["confidence"] = "low"
                    c["suggestion"] = (
                        "A source line carries a different year, but it does "
                        "not name the same milestone — not enough to call this "
                        "a contradiction.")
                elif not _year_near_name(c, quote):
                    c["verdict"] = "unverified"
                    c["confidence"] = "low"
                    c["suggestion"] = (
                        "A source line carries a different year, but it is not "
                        "stated next to this claim's subject — too weak to call "
                        "a contradiction.")
        if (c.get("verdict") == "unverified" and not c.get("evidence")
                and not c.get("manual_checks")):
            # every unverified row leaves the user with SOMETHING to paste:
            # the demotion branches above and the numeric "value missing" path
            # both end here (prose adds its own on top)
            qs = _hand(c)
            if qs:
                c["manual_checks"] = qs
        if c.get("verdict") != "unverified" or c.get("evidence"):
            continue
        if c.get("type") in ("event", "sentence"):
            # A prose sentence has no deterministic checker (no figure/quote).
            # Saying "no source covers it" would be a false claim: nothing was
            # searched. Keep it unverified and hand the reader the nearest
            # passage as a LEAD, explicitly not as proof.
            context = c.get("context_sentence") or c.get("sentence") or ""
            cands = library.corpus.find_prose_candidates(context, top=3)
            if cands:
                p = cands[0]
                c["suggestion"] = (
                    "Prose claim — no deterministic check was run. Nearest "
                    f"passage ({p['fname']}:{p['start']}) is a lead, not "
                    f"proof: {p['text'][:200]}")
                # one sentence can need facts from several passages; keep the
                # other leads available for the reader / W1.4 without calling
                # any of them evidence
                c["lead_candidates"] = [
                    {"fname": x["fname"], "start": x["start"], "end": x["end"],
                     "text": (x.get("text") or "")[:200]}
                    for x in cands]
            else:
                c["suggestion"] = (
                    "Prose claim — no deterministic check was run, and no "
                    "passage shares two terms with it.")
            c["confidence"] = "low"
            continue
        note = (c.get("suggestion") or "").lower()
        if ("no corpus line" in note or "no subject keyword" in note
                or not note):
            c["verdict"] = "no_source"
            c["confidence"] = "low"
            c["suggestion"] = NO_SOURCE_NOTE + (
                " Add the source that states this, or verify it by hand."
            )
            qs = _hand(c)
            if qs:
                c["manual_checks"] = qs
    return claims


# ---- footnotes ------------------------------------------------------------

def _definitions(doc):
    """{id: text} from docx '[footnote N] ...' or markdown '[^N]: ...'."""
    out = {}
    for p in doc.get("paragraphs") or []:
        m = re.match(r"\[(?:footnote|endnote)\s+(\d+)\]\s*(.*)", p)
        if not m:
            m = re.match(r"\[\^([^\]]+)\]:\s*(.*)", p)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _sentence_at(para, offset):
    for sent, start in tp.sentences_spans(para):
        if start <= offset <= start + len(sent):
            return sent
    return para


def _cited_titles(text):
    return re.findall(r"《([^》]{1,80})》", text or "")


def resolve_source(def_text, library):
    """Match a footnote definition to a manifest source.

    Citations carry the full title ("《生生不息：一个中国软件企业的…》") while
    the manifest carries the short one ("生生不息"), so containment in either
    direction is required — with a minimum length so a two-character prefix
    cannot match a different book.
    """
    cited = [tp.normalize(t) for t in _cited_titles(def_text)]
    for s in library.sources:
        for name in (s.get("title") or "", Path(s.get("path") or "").stem):
            n = tp.normalize(name)
            if len(n) < 3:
                continue
            for c in cited:
                if len(c) >= 3 and (n in c or c in n):
                    return s
    return None


def _line_settles(vals, raw):
    """Does this source line carry every figure the anchored sentence states?"""
    if not vals:
        return False
    lvals = tp.extract_values(raw)
    for av in vals:
        if not any(v["kind"] == av["kind"]
                   and tp.values_equal(av["value"], v["value"], kind=av["kind"])
                   for v in lvals):
            return False
    return True


def footnote_audit(doc, library):
    """One row per reference: where it sits, what it cites, whether it fits."""
    defs = _definitions(doc)
    anchors = doc.get("footnote_anchors") or []
    rows = []
    for a in anchors:
        para_i = a.get("para")
        if para_i is None or para_i >= len(doc.get("paragraphs") or []):
            continue
        para = doc["paragraphs"][para_i]
        anchor = _sentence_at(para, int(a.get("offset") or 0))
        def_text = defs.get(str(a.get("id")), "")
        src = resolve_source(def_text, library)
        row = {
            "id": a.get("id"), "para": para_i, "anchor_quote": anchor,
            "def_text": def_text, "source_id": src["id"] if src else None,
            "verdict": "no_source", "note": "",
        }
        if not def_text:
            row["note"] = "reference has no definition"
        elif not src:
            row["note"] = ("cited source is not in the library — add it before "
                           "this footnote can be checked")
        else:
            ev_a = tp.event_of(tp.normalize(anchor))
            ev_d = tp.event_of(tp.normalize(def_text))
            if ev_a and ev_d and ev_a != ev_d:
                row["verdict"] = "misattributed"
                row["note"] = (f"anchor is about {ev_a}, the cited source is "
                               f"about {ev_d}")
            else:
                hits = library.lines_of(
                    src["id"], list(tp.tokens(anchor))[:8], top=5)
                vals = tp.extract_values(anchor)
                settled = any(_line_settles(vals, h[3]) for h in hits)
                if vals:
                    ok = settled
                else:
                    ok = len(hits) >= 1 and len(
                        set(tp.tokens(anchor)) & set(tp.tokens(hits[0][3]))
                    ) >= 2
                row["verdict"] = "supported" if ok else "unverified"
                row["note"] = ("" if ok else
                               "source is cited but its text does not settle "
                               "this sentence")
        rows.append(row)
    return rows


def write_corrections(findings, path):
    """Deterministic fix list: only rows a reader can act on."""
    path = Path(path)
    todo = [x for x in findings
            if x.get("verdict") not in ("supported", "narrative")
            and (x.get("suggestion") or x.get("note"))]
    lines = ["# Suggested corrections", "",
             "One row per item the report does not accept. The locator is the "
             "evidence a human should open before editing.", "",
             "| Claim | Verdict | Fix | Evidence |", "|---|---|---|---|"]
    for x in todo:
        ev = (x.get("evidence") or [{}])[0]
        loc = ev.get("ref", "")
        if ev.get("source_id"):
            loc += f" (source={ev['source_id']}"
            loc += f", p.{ev['page']})" if ev.get("page") else ")"
        fix = (x.get("suggestion") or x.get("note") or "").replace("|", "\\|")
        raw = (x.get("raw") or "").replace("|", "\\|")[:120]
        lines.append(f"| {raw} | {x['verdict']} | {fix[:240]} | {loc} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_audit(rows, path):
    path = Path(path)
    lines = ["# Footnote audit", "",
             "Anchor = the sentence the reference sits on. The source is the "
             "one the footnote cites, not any source in the library.", "",
             "| # | Anchor | Cited source | Verdict | Note |",
             "|---|---|---|---|---|"]
    for r in rows:
        def_short = " ".join((r["def_text"] or "").split())[:90]
        anchor_short = " ".join(r["anchor_quote"].split())[:90]
        lines.append(
            f"| {r['id']} | {_cell(anchor_short)} | {_cell(def_short)} | "
            f"{r['verdict']} | {_cell(r['note'])} |")
    lines += ["", "## Evidence", ""]
    for r in rows:
        lines += [f"### Footnote {r['id']} — {r['verdict']}", "",
                  f"- Anchor (¶{r['para']}): {r['anchor_quote']}",
                  f"- Footnote: {r['def_text'] or '(none)'}",
                  f"- Resolved source: {r['source_id'] or '(not in library)'}",
                  f"- Note: {r['note'] or '—'}", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _cell(s):
    return (s or "").replace("|", "\\|")
