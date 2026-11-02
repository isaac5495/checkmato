"""BYOS unit + end-to-end gate (offline, synthetic sources only).

Covers: same-language aliases and the parent/subsidiary guard, glossary
verification, footnote misattribution, book-only support with line+page
evidence, no_text_layer reporting, no_source conversion, and a full
sources_only CLI run that writes report/claims/audit.

Facts only the library carries must become `supported`; facts no library
source carries must become `no_source` — never a silent `unverified`.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app import textproc as tp
    from app.byos import apply_byos, footnote_audit
    from app.cli import run
    from app.corpus import Corpus
    from app.enrich import mark_narrative
    from app.extract import extract_claims, read_doc
    from app.glossary import is_same_subject, norm, same_entity, verify_pair
    from app.glossary_build import build as build_glossary
    from app.judge import judge
    from app.library import Library

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"BYOS FAIL: {msg}"
        n += 1

    lib_dir = ROOT / "tests" / "byos" / "lib"
    lib = Library(lib_dir)

    # --- library + locators ---
    ok(lib.stats["sources"] == 4, f"four sources indexed (got {lib.stats})")
    ok(lib.stats["lines"] > 0, "line index is populated")

    rev = next(ln for ln in lib.corpus.lines
               if "reported revenue" in ln[2] and ln[0].endswith(".md"))
    ok(lib.page_map.get((rev[0], rev[1])) == 1,
       "a markdown line maps to its page in the paired PDF")

    ok(any(x["path"] == "scanned.pdf" for x in lib.no_text_layer),
       "a PDF with no text layer is reported, not silently empty")
    ok(not any(x["path"] == "acme_history.pdf" for x in lib.no_text_layer),
       "a normal text-layer PDF is not flagged")

    # --- passage fallback: a figure split across two lines ---
    pcorpus = Corpus(ROOT / "tests" / "byos" / "passage")
    ok(any("125" in p["text"] and "million" in p["text"]
           for p in pcorpus.passages),
       "adjacent lines are merged into a passage")
    pclaims = extract_claims(
        ["Acme Systems reported revenue of 125 million dollars in 2019."])
    amt = next(c for c in pclaims if c["type"] == "amount")
    judge([amt], pcorpus)
    ok(amt["verdict"] == "supported",
       f"a split figure is supported from the passage ({amt['verdict']})")
    ok(amt["evidence"][0]["precision"] == "passage",
       "passage evidence is labelled as such")

    # --- numeric formatting + value-first retrieval ---
    spaced = [v for v in tp.extract_values("122 000 lines") if v["kind"] == "count"]
    ok(spaced and spaced[0]["value"] == 122000.0,
       f"a space-grouped number is one value, not 000 (got {spaced})")
    by_val = lib.corpus.find_value_lines(
        ["revenue"], "amount", 125_000_000.0, "USD")
    ok(by_val and "125 million" in by_val[0][3],
       "value index finds a line by the figure, not only by words")

    # --- same-language aliases and the parent/sub guard ---
    ok(same_entity("Acme", "Acme Software", cooccur=True),
       "short form + descriptor used by the author is the same entity")
    ok(not same_entity("Acme", "Acme Cloud", cooccur=True),
       "a Cloud subsidiary is never the parent")
    ok(not is_same_subject("Acme", "Acme Cloud"),
       "Cloud subsidiary must not pass the subject check")
    ok(same_entity("華光", "華光軟件", cooccur=True),
       "short/full Chinese form is the same entity")
    ok(not same_entity("華光", "華光雲", cooccur=True),
       "Chinese Cloud subsidiary is never the parent")

    # --- glossary verification: proposals are not proof ---
    corpus_text = "華光軟件（下稱華光）在 1998 年成立。陳艾莉是創辦人。"
    draft_text = "華光軟件在 1998 年成立，華光其後擴張。"
    good = verify_pair("華光", "華光軟件", "zh-zh", corpus_text, draft_text)
    ok(good["state"] == "verified", f"both forms proven -> verified ({good})")
    bad = verify_pair("Alice Chen", "陳愛麗", "zh-en", corpus_text, draft_text)
    ok(bad["state"] != "verified" and bad["occ_b"] == 0,
       f"an invented native name is not verified ({bad})")

    # --- builder: harvest -> model proposes -> corpus decides ---
    g_corpus = ("華光軟件（下稱華光）。華光軟件在 1998 年成立。"
                "陳艾莉是創辦人。陳艾莉負責研發。Alice Chen 是顧問。")
    g_draft = "華光軟件在 1998 年成立。華光其後擴張。Alice Chen 出席會議。"

    class _StubLLM:
        available = True

        def chat(self, _prompt):
            return ('{"pairs": ['
                    '{"a": "Alice Chen", "b": "陳愛麗", "kind": "person", '
                    '"scope": "same"},'
                    '{"a": "Alice Chen", "b": "陳艾莉", "kind": "person", '
                    '"scope": "same"}]}')

    g, gs = build_glossary(g_draft, g_corpus, llm=_StubLLM(), use_llm=True)
    ok(any(r["state"] == "verified"
           and {norm(r["a"]), norm(r["b"])} == {norm("華光"), norm("華光軟件")}
           for r in g.rows),
       "builder verifies the short/full Chinese pair")
    ok(not any("陳愛麗" in (r["a"], r["b"]) for r in g.rows),
       "invented name never reaches the glossary")
    ok(any(r["state"] == "retrieval_only"
           and {norm(r["a"]), norm(r["b"])} == {norm("Alice Chen"), norm("陳艾莉")}
           for r in g.rows),
       "cross-script pair is stored as retrieval-only")
    ok(gs["llm_used"] is True, "builder reports that a model was consulted")

    # --- footnote anchoring: wrong milestone is misattributed ---
    wrong_doc = read_doc(ROOT / "tests" / "byos" / "wrong_anchor.docx")
    rows = footnote_audit(wrong_doc, lib)
    ok(len(rows) == 1, "one footnote reference audited")
    ok(rows[0]["verdict"] == "misattributed",
       f"footnote about a different milestone -> misattributed ({rows})")
    ok("opened" in rows[0]["anchor_quote"] and "founded" in rows[0]["def_text"],
       "both the anchor quote and the cited text are shown")

    # --- markdown footnotes get the same anchoring + audit ---
    md_doc = read_doc(ROOT / "tests" / "byos" / "md_footnote.md")
    ok(len(md_doc.get("footnote_anchors") or []) == 1,
       "markdown [^n] reference has a paragraph + offset anchor")
    md_rows = footnote_audit(md_doc, lib)
    ok(md_rows and md_rows[0]["verdict"] == "misattributed",
       "markdown footnote is audited, not skipped")
    ok("founded" in md_rows[0]["def_text"],
       "markdown definition text is read")

    # --- scanned-PDF import: converted text keeps its provenance ---
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "lib"
        shutil.copytree(lib_dir, copy)
        conv = Path(td) / "converted.md"
        conv.write_text("Acme Systems was founded in 1998 in Bergen.\n",
                        encoding="utf-8")
        lib2 = Library(copy)
        src = lib2.import_converted(conv, copy / "scanned.pdf",
                                    out=copy / "library.toml")
        ok(src["derived_from"].endswith("scanned.pdf"),
           "imported copy records the original PDF")
        reloaded = Library(copy / "library.toml")
        ok(len(reloaded.sources) == 5, "imported source is persisted")
        ok(any(s.get("derived_from") for s in reloaded.sources),
           "manifest keeps derived_from across reloads")

    # --- no_source conversion ---
    claim = {"id": "x", "type": "year", "raw": "1999",
             "sentence": "Acme opened a plant in 1999.", "verdict": "unverified",
             "confidence": "low", "evidence": [], "suggestion": ""}
    apply_byos([claim], lib, "sources_only")
    ok(claim["verdict"] == "no_source",
       "uncovered numeric claim becomes no_source")

    prose = {"id": "p", "type": "event", "raw": "an unsourced statement",
             "sentence": "Acme announced something no source records.",
             "verdict": "unverified", "confidence": "low", "evidence": [],
             "suggestion": ""}
    apply_byos([prose], lib, "sources_only")
    ok(prose["verdict"] == "unverified"
       and "Prose claim" in prose["suggestion"],
       "prose is left unverified with a lead, never called no_source")

    weak = {"id": "w", "type": "year", "raw": "1995",
            "sentence": "Acme opened a plant in 1995.",
            "verdict": "contradicted", "confidence": "high",
            "evidence": [{"kind": "local", "ref": "acme_history.md:3",
                          "quote": "Acme Systems reported revenue of 125 "
                                   "million dollars for the 2019 fiscal year."}],
            "suggestion": ""}
    apply_byos([weak], lib, "sources_only")
    ok(weak["verdict"] == "unverified",
       "a shared year alone is not enough to call a contradiction")

    # --- eligibility: a Word heading is context, not a claim ---
    head = {"id": "h", "type": "year", "raw": "1988",
            "sentence": "First Renewal (1988-2000)", "para": 0,
            "verdict": "unverified", "confidence": "low", "evidence": []}
    mark_narrative([head], {0})
    ok(head["verdict"] == "narrative",
       "a heading paragraph (no '#' marker in docx) is not a checkable claim")

    # --- end-to-end: CLI run in sources_only ---
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        _findings, meta = run(
            str(ROOT / "tests" / "byos" / "book_only.docx"),
            out_dir=str(out), library=str(lib_dir), sources_only=True,
            footnotes=True)
        ok(meta["mode"] == "sources_only", "run reports sources_only mode")
        ok(meta["web_searches_used"] == 0 and meta["web_search_budget"] == 0,
           "sources_only spends no searches")
        ok(meta["byos_sources"] == 4, "run uses the attached library")
        ok(meta["byos_no_text_layer"] == 1, "scanned source surfaced in meta")

        with open(out / "claims.jsonl", encoding="utf-8") as f:
            records = [json.loads(line) for line in f]
        ok(records and all(r.get("mode") == "sources_only" for r in records),
           "every record carries mode=sources_only")

        supported = [r for r in records if r["verdict"] == "supported"]
        ok(supported, "a book-only fact is supported by the library")
        ev = supported[0]["evidence"][0]
        ok(ev.get("source_id") == "acme-history-md",
           f"evidence has source id ({ev})")
        ok(ev.get("ref", "").startswith("acme_history.md:")
           and ev.get("page") == 1,
           f"evidence carries both line and page ({ev})")

        # a source with no paired PDF keeps the line locator and says so
        from app.byos import enrich_evidence
        from app.report import _ev_lines
        c = {"evidence": [{"kind": "local", "ref": "harbor_ledger.md:3",
                           "quote": "Acme Systems was founded in 1998."}]}
        enrich_evidence(c, lib)
        ok(c["evidence"][0].get("page_unavailable") is True,
           "no page map -> page_unavailable, never a guessed page")
        ok("page unavailable" in _ev_lines(c)[0],
           "the report says page unavailable instead of omitting it")

        report = (out / "report.md").read_text(encoding="utf-8")
        ok("no network requests" in report,
           "report states the no-network promise")
        ok((out / "audit.md").exists(), "audit.md is written")
        ok((out / "corrections.md").exists(), "corrections.md is written")
        audit = (out / "audit.md").read_text(encoding="utf-8")
        ok("## Evidence" in audit and "Footnote" in audit,
           "audit contains the per-footnote evidence block")

    print(f"BYOS TESTS: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
