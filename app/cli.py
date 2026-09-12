import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from . import checks
from .corpus import Corpus
from .enrich import classify_prose, enrich, mark_narrative
from .extract import extract_claims, read_doc
from .judge import judge
from .llm import LLM, extract_semantic_claims
from .names import AliasMap
from .report import write_jsonl, write_md, write_xlsx
from .textproc import detect_language
from .web import WebBudget, WebEvidence


def _run_stats(doc, corpus, claims):
    from .textproc import count_words
    need = [c for c in claims if c["verdict"] in ("unverified", "deferred_web")
            and not (c.get("citation") and c["type"] != "url")
            and not c.get("fx_secondary")]
    uniq = len({(c["type"], c["raw"].strip().lower()) for c in need})
    return {"words": count_words(doc["paragraphs"]),
            "paras": len(doc["paragraphs"]),
            "claims": len(claims), "need_web": len(need), "uniq_need_web": uniq}


def run(doc_path, corpus_dir=None, out_dir="reports", use_web=False, use_llm=False,
        max_search=60, whitelist=None, fx_rates=None, names=None, cfg=None,
        progress=None, cancel=None, backend="auto"):
    _p = progress or (lambda e: None)
    cancelled_midrun = False
    from . import config as _cfg
    from . import estimate as est
    from . import llm as llm_mod
    from .textproc import detect_entities
    cfg = cfg or _cfg.load()
    import corpus as _corpus_mod
    _corpus_mod.VERBATIM_CUT = cfg["quote_verbatim_cut"]
    _corpus_mod.PARAPHRASE_CUT = cfg["quote_paraphrase_cut"]
    alias = AliasMap.load(names)
    doc = read_doc(doc_path)
    from .textproc import count_words as _cw
    _p({"stage": "parse", "words": _cw(doc["paragraphs"]),
        "paras": len(doc["paragraphs"])})
    corpus = Corpus(corpus_dir, aliases=alias)
    _p({"stage": "corpus", "files": len(corpus.files), "lines": len(corpus)})
    llm = LLM(max_calls=cfg["llm_max_calls"], max_tokens=cfg["llm_max_tokens"],
              max_seconds=cfg["llm_max_seconds"]) if use_llm else None
    claims = extract_claims(doc["paragraphs"])
    _p({"stage": "extract", "claims": len(claims)})
    context = None
    if llm and llm.available:
        from .names import extract_names
        _p({"stage": "thinking", "item": "inferring the subject of this document"})
        context = llm_mod.resolve_subject(llm, "\n\n".join(doc["paragraphs"]))
        if context and context.get("subject"):
            doc_names = list(dict.fromkeys(
                detect_entities(doc["paragraphs"])
                + [p for p in context.get("people", []) if isinstance(p, str)]))
            if not alias.groups and corpus.files:
                for a, b in llm_mod.auto_aliases(llm, doc_names,
                                                 extract_names(corpus)):
                    alias.add_group([a, b])
    _p({"stage": "context", "subject": (context or {}).get("subject"),
        "auto_aliases": len(alias.groups)})
    if llm and llm.available:
        _p({"stage": "thinking", "item": "finding claims written without numbers"})
        base = len(claims)
        extra = extract_semantic_claims(llm, doc["paragraphs"], None, progress=_p)
        for c in extra:
            if not any(c["raw"].lower() in x["sentence"].lower() and
                       c["type"] == x["type"] for x in claims[:base]):
                claims.append(c)
    judge(claims, corpus, progress=_p)
    # citation text (footnote/endnote paragraphs) is the SOURCE, not a claim:
    # fact-checking a citation against the web is out of scope and wastes the
    # search budget — only URLs inside them get liveness-probed
    cite_idx = {i for i, p in enumerate(doc["paragraphs"])
                if p.startswith("[footnote ") or p.startswith("[endnote ")}
    for c in claims:
        if c.get("para") in cite_idx:
            c["citation"] = True
    # mark stated conversions BEFORE any searching, so the converted figure is
    # never web-judged out of context (see fx.tag_conversions)
    from .fx import tag_conversions
    tag_conversions(claims)
    # eligibility (deterministic floor first: no LLM needed): headings and
    # questions assert nothing checkable — a human checker never opens them
    mark_narrative(claims)
    # budgets SCALE with the document's actual needs — a 6800-word case study
    # gets the same rigor per paragraph as a 200-word blurb, just more time
    budgets = est.scaled_budgets(_run_stats(doc, corpus, claims),
                                 {**cfg, "max_search": max_search},
                                 web=True, llm=bool(llm and llm.available))
    if llm:
        llm.max_calls = budgets["llm_max_calls"]
        llm.max_tokens = budgets["llm_max_tokens"]
        llm.max_seconds = budgets["llm_max_seconds"]
    # prose triage NEEDS the scaled budget (it is a real LLM call): sentences
    # that are the author's voice become 'narrative' (visible, reasoned, never
    # searched) so essay prose cannot flood the report with grey 'unverified'
    classify_prose(llm, claims, progress=_p)
    entities = detect_entities(doc["paragraphs"])
    if context and context.get("subject"):
        nat = str(context.get("subject_native") or "").strip()
        heads = [context["subject"]]
        if nat and nat.lower() != str(context["subject"]).lower():
            # native-script alias (Kingsoft ↔ 金山软件): without it a Chinese
            # snippet stating the exact fact fails the entity anchor and the
            # whole evidence pool is thrown away as 'not mentioning the subject'
            heads.append(nat)
        for pn in (context.get("people_native") or []):
            sp = str(pn).strip()
            if sp and sp.lower() != "null":
                heads.append(sp)  # 雷军/求伯君 anchor Chinese snippets too
        entities = heads + [e for e in entities if e not in heads]
    if alias.groups:
        entities = entities + [grp[0] for grp, _ts in alias.groups
                               if grp[0] not in entities]
    timelines = checks.entity_timelines(doc["paragraphs"], entities)
    web = None
    if use_web or (llm and llm.available):
        pairs = []
        if context:
            s = str(context.get("subject") or "").strip()
            sn = str(context.get("subject_native") or "").strip()
            if s and sn and sn.lower() != "null" and sn != s:
                pairs.append((s, sn))
            for a, b in zip(context.get("people") or [],
                            context.get("people_native") or []):
                a, b = str(a).strip(), str(b).strip()
                if a and b and b.lower() != "null" and a.isascii() and not b.isascii():
                    pairs.append((a, b))
        web = WebEvidence(
            WebBudget(budgets["max_search"], budgets["web_max_seconds"],
                      budgets["max_pages"]),
            site_whitelist=whitelist or [], entities=entities,
            searxng_url=cfg.get("searxng_url"),
            searxng_engines=cfg.get("searxng_engines"),
            entity_pairs=pairs, doc_paras=doc["paragraphs"],
            backends=backend)
    if web:
        enrich(claims, web, llm, progress=_p, context=context, cancel=cancel)
    if cancel and cancel():
        cancelled_midrun = True
        for c in claims:
            if c["verdict"] == "unverified" and not c.get("_skip_reason"):
                c["_skip_reason"] = "cancelled by user"
    from .fx import FX, verify_conversions
    meta_fx = FX(tolerance=cfg["fx_tolerance"], rates=fx_rates, allow_http=bool(web))
    verify_conversions(claims, meta_fx)
    structural = checks.structural_findings(doc, claims)
    drift = checks.name_drift(doc["paragraphs"], alias)
    findings = _order(structural + checks.timeline_conflicts(timelines) + drift + claims)
    anchored = [x for x in findings if x.get("para") is not None]
    anchor_ok = sum(1 for x in anchored if x.get("anchored"))

    meta = {
        "doc": Path(doc_path).name,
        "paragraphs": doc["paragraphs"],
        "run": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "engine": _engine_label(use_web, llm, web),
        "words": _word_count(doc["paragraphs"]),
        "paras": len(doc["paragraphs"]),
        "lang": detect_language(doc["paragraphs"]),
        "corpus_files": len(corpus.files),
        "corpus_lines": len(corpus),
        "web_searches_used": web.budget.used if web else 0,
        "web_search_budget": web.budget.max if web else 0,
        "web_pages_read": web.budget.used_pages if web else 0,
        "web_backends": _backends(web),
        "web_checked": sum(1 for x in findings if x.get("_searched")),
        "web_unsearched": sum(1 for x in findings
                              if x["verdict"] in ("unverified", "deferred_web")
                              and not x.get("_searched")),
        "web_exhausted": bool(web and web.budget.exhausted),
        "web_entities": entities,
        "timelines": timelines,
        "context": context,
        "name_drift": len(drift),
        "alias_groups": len(alias.groups),
        "alias_map": [list(g) for g, _ts in alias.groups],
        "auto_aliases": len(alias.groups) if context else 0,
        "fx_checks": meta_fx.checks if meta_fx else 0,
        "anchor_total": len(anchored),
        "anchor_ok": anchor_ok,
        "llm_calls": llm.calls if llm else 0,
        "cancelled": bool(cancelled_midrun or (cancel and cancel())),
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _p({"stage": "reporting", "item": "writing report, spreadsheet and annotated copy"})
    write_jsonl(findings, out / "claims.jsonl")
    write_md(meta, findings, out / "report.md")
    write_xlsx(meta, findings, out / "report.xlsx")
    from .annotate import annotate_docx, annotate_md
    try:
        if Path(doc_path).suffix.lower() == ".docx":
            annotate_docx(doc_path, findings, doc["paragraphs"], out / "annotated.docx")
        else:
            annotate_md(doc_path, findings, doc["paragraphs"], out / "annotated.md")
        meta["annotated"] = str(out / "annotated.*")
    except Exception as e:
        meta["annotate_error"] = str(e)
    return findings, meta


def _word_count(paragraphs):
    from .textproc import count_words
    return count_words(paragraphs)


def _backends(web):
    if not web:
        return "off"
    from .web import DDGS
    names = (["ddgs"] if DDGS is not None else []) + \
            (["searxng"] if web.searxng else []) + \
            (["wikipedia"] if getattr(web, "wikipedia", None) else []) + \
            (["google-cse"] if getattr(web, "cse", None) and web.cse.usable else []) + \
            (["brave"] if getattr(web, "brave", None) and web.brave.usable else [])
    only = getattr(web, "only", "auto")
    if only not in ("", "auto"):  # the user picked an engine: the report
        names = [n for n in names
                 if n in (only, "wikipedia")]  # says what ran, period
    return "+".join(names) or "none"


def _engine_label(use_web, llm, web=None):
    parts = ["M0.5 (deterministic: extraction + BYOS grep + structural)"]
    if use_web or web:
        parts.append(f"+ free web ({_backends(web)})")
    if llm and llm.available:
        parts.append("+ LLM (free tier)")
    return " ".join(parts)


def _order(findings):
    order = ["contradicted", "internal_conflict", "needs_fix", "structure",
             "misattributed", "paraphrase_flag", "conflicting",
             "deferred_web", "unverified", "narrative", "supported"]
    rank = {v: i for i, v in enumerate(order)}
    return sorted(findings, key=lambda x: (rank.get(x["verdict"], 9), x["id"]))


def main(argv=None):
    logging.basicConfig(level=os.environ.get("CHECKMATO_LOG", "WARNING").upper(),
                        format="%(levelname)s %(name)s: %(message)s")
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "diff":
        return _main_diff(argv[1:])
    ap = argparse.ArgumentParser(
        prog="checkmato",
        description="CheckMato M0.5 — fact-check pipeline for documents.")
    ap.add_argument("doc", help="path to .md/.txt/.docx document to check")
    ap.add_argument("--corpus", help="BYOS directory of source files (.md/.txt/.csv/.pdf/.docx)")
    ap.add_argument("--out", default="reports", help="output directory")
    ap.add_argument("--web", action="store_true",
                    help="enable free keyless web search (ddgs) for unverified claims")
    ap.add_argument("--llm", action="store_true",
                    help="enable LLM assistance (needs GEMINI_/GROQ_/OPENAI_ API key)")
    ap.add_argument("--max-search", type=int, default=None, help="search budget per run")
    ap.add_argument("--whitelist", default="",
                    help="comma-separated authoritative sites, e.g. reuters.com,gov.cn")
    ap.add_argument("--backend", default="auto", choices=("auto", "brave", "ddgs"),
                    help="search engine choice: auto (chain), brave, or ddgs")
    ap.add_argument("--names", default=None,
                    help="alias/name-equivalence file (CSV 'en,zh' or 'A = B' lines)")
    ap.add_argument("--config", default="checkmato.toml",
                    help="settings file (budgets/thresholds); used if present")
    ap.add_argument("--estimate", action="store_true",
                    help="analyze the document and predict duration/budgets, do NOT check")
    a = ap.parse_args(argv)
    from .config import load as load_cfg
    from . import estimate as est
    cfg = load_cfg(a.config)
    if a.estimate:
        stats = est.analyze(a.doc, a.corpus, a.names)
        e = est.estimate(stats, {**cfg, "max_search": a.max_search or cfg["max_search"]},
                         web=a.web or a.llm, llm=a.llm)
        lo, hi, typ = e["seconds_lo"], e["seconds_hi"], e["seconds_typ"]

        def fmt(s):
            return f"{s//60} min {s % 60:02d} s" if s >= 60 else f"{s} s"
        pl = e["plan"]
        print(f"CheckMato job plan — {stats['doc']}")
        print(f"  document: {stats['words']} words, {stats['paras']} paragraphs, "
              f"{stats['claims']} claims ({stats['need_web']} need live web checks)")
        print("  plan (sized to THIS document; budget up to 5-6 searches per "
              "claim, spent only while unsettled — early-stop keeps it honest):")
        print(f"    - {pl['searches']} web searches")
        print(f"    - {pl['deep_checks']} sentence-level deep checks (every claim)")
        print(f"    - {pl['pages']} full-page deep-reads")
        print(f"    - {pl['llm_calls']} LLM judgment calls")
        print(f"  estimated duration: ~{fmt(typ)} (range {fmt(lo)} – {fmt(hi)})")
        print(f"  full-depth coverage: {e['coverage_pct']}%")
        if e.get("recommend"):
            print(f"  RECOMMENDATION: {e['recommend']}")
        return 0
    findings, meta = run(a.doc, a.corpus, a.out, use_web=a.web, use_llm=a.llm,
                         max_search=a.max_search or cfg["max_search"],
                         whitelist=([w.strip() for w in a.whitelist.split(",") if w.strip()]
                                    or cfg["whitelist"]),
                          names=a.names, cfg=cfg, backend=a.backend)
    counts = {}
    for x in findings:
        counts[x["verdict"]] = counts.get(x["verdict"], 0) + 1
    print(f"CheckMato — {meta['doc']} ({meta['words']} words, {len(findings)} findings)")
    for v in ("contradicted", "internal_conflict", "needs_fix", "structure",
              "misattributed", "paraphrase_flag", "conflicting", "unverified",
              "deferred_web", "narrative", "supported"):
        if counts.get(v):
            print(f"  {v:18} {counts[v]}")
    if meta.get("name_drift"):
        print(f"  name drift     {meta['name_drift']}")
    if meta.get("alias_groups"):
        print(f"  alias groups   {meta['alias_groups']}")
    if meta.get("web_searches_used"):
        print(f"  web searches: {meta['web_searches_used']}/{meta['web_search_budget']}"
              + ("  [BUDGET EXHAUSTED — remaining web items not checked]"
                 if meta.get("web_exhausted") else ""))
    if meta.get("llm_calls"):
        print(f"  llm calls: {meta['llm_calls']}")
    print(f"Reports -> {Path(a.out) / 'report.md'} | report.xlsx | claims.jsonl")
    return 0


def _main_diff(argv):
    import argparse as _ap
    from .diff import compare
    from .report import write_diff_md
    ap = _ap.ArgumentParser(prog="checkmato diff",
                             description="Compare two language versions of one document.")
    ap.add_argument("file_a")
    ap.add_argument("file_b")
    ap.add_argument("--names", default=None, help="alias file (cross-script name identity)")
    ap.add_argument("--out", default="reports/diff")
    ap.add_argument("--labels", default="EN,ZH", help="version labels for the report")
    a = ap.parse_args(argv)
    alias = AliasMap.load(a.names)
    la, lb = [x.strip() for x in a.labels.split(",")]
    findings, summary = compare(read_doc(a.file_a), read_doc(a.file_b), alias, la, lb)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_diff_md(summary, findings, out / "diff.md", la, lb)
    write_jsonl(findings, out / "diff.jsonl")
    print(f"CheckMato diff — {la} ({summary['a_paras']}¶) vs {lb} "
          f"({summary['b_paras']}¶): {summary['findings']} drift items")
    for x in findings:
        print(f"  - {x['raw']}")
    print(f"Report -> {out / 'diff.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
