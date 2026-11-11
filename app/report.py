import json
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import provenance

FILLS = {
    "supported": "C6EFCE",
    "contradicted": "FFC7CE",
    "internal_conflict": "FFC7CE",
    "misattributed": "FFC7CE",
    "conflicting": "FCD5B4",
    "paraphrase_flag": "FFEB9C",
    "needs_fix": "FFEB9C",
    "structure": "FFEB9C",
    "unverified": "D9D9D9",
    "narrative": "BDD7EE",
    "deferred_web": "DDEBF7",
}

VERDICT_ORDER = ["contradicted", "internal_conflict", "misattributed",
                 "conflicting", "paraphrase_flag",
                 "needs_fix", "structure", "deferred_web", "unverified",
                 "narrative", "supported"]

COVERAGE_ORDER = ["supported", "needs_attention", "conflicting",
                  "checked_not_found", "not_checked", "no_source",
                  "not_checkable", "structure", "other"]

_COVERAGE_EN = {
    "supported": "evidence attached",
    "needs_attention": "contradicted, misattributed, or needs a fix",
    "conflicting": "sources disagree — you decide",
    "checked_not_found": "searched, but no source settled it",
    "not_checked": "budget/cancelled/backend — NOT a negative finding",
    "no_source": "no source supplied or found",
    "not_checkable": "narrative/commentary",
    "structure": "document structure, not a claim",
    "other": "other",
}
_COVERAGE_ZH = {
    "supported": "已附证据",
    "needs_attention": "有矛盾/张冠李戴/需修正",
    "conflicting": "来源相左，请自行裁决",
    "checked_not_found": "已查，但没有来源能证实",
    "not_checked": "未查（额度/取消/后端）— 不是负面结论",
    "no_source": "没有提供或找到来源",
    "not_checkable": "叙述/评论，无需核查",
    "structure": "文档结构问题，不是 claim",
    "other": "其他",
}


def _lane_checked(x):
    """Was this claim evaluated by ANY available lane?

    `_searched` only means the WEB lane ran. In a BYOS run the deterministic
    judge/apply_byos pass has already checked the claim against the supplied
    corpus, so an `unverified` there is "checked, not found", not "never
    checked". A budget/cancel skip is the exception: that claim was not fully
    evaluated, so it must stay "not checked".
    """
    reason = str(x.get("_skip_reason") or "").lower()
    if "budget" in reason or "cancel" in reason:
        return False
    if x.get("_searched"):
        return True
    return str(x.get("_mode") or "") in ("sources_only", "sources_then_web")


def coverage_counts(findings):
    """Split `unverified` into the states a reader actually needs.

    `unverified` was a grey bucket for two very different things: "we searched
    and found nothing" and "we never checked it". The second is not a negative
    finding, so it gets its own row; the same for no-source and narrative.
    """
    c = Counter()
    for x in findings:
        v = x.get("verdict")
        if v == "unverified":
            c["checked_not_found" if _lane_checked(x) else "not_checked"] += 1
        elif v == "deferred_web":
            c["not_checked"] += 1
        elif v == "no_source":
            c["no_source"] += 1
        elif v == "narrative":
            c["not_checkable"] += 1
        elif v == "structure":
            c["structure"] += 1
        elif v in ("contradicted", "needs_fix", "internal_conflict",
                   "misattributed", "paraphrase_flag"):
            c["needs_attention"] += 1
        elif v == "conflicting":
            c["conflicting"] += 1
        elif v == "supported":
            c["supported"] += 1
        else:
            c["other"] += 1
    return dict(c)


def to_record(x):
    """Serialize a finding to the PRD §7 contract (dev + report + eval)."""
    # the explanation is copied, field by field, so a record is a snapshot: it
    # cannot be changed later through the finding, and it carries only the keys
    # the renderer knows how to draw.
    ex_raw = x.get("explain") or {}
    explanation = {
        "checks": [dict(c) for c in ex_raw.get("checks", [])],
        "origin": ex_raw.get("origin", ""),
        "assisted": bool(ex_raw.get("assisted", False)),
    }
    return {
        "claim_id": x["id"],
        "source_span": None if x.get("para") is None else {
            "para": x["para"], "start": x.get("span", [0, 0])[0],
            "end": x.get("span", [0, 0])[1]},
        "quote": x["raw"],
        "context": x.get("sentence", ""),
        "sentence_id": x.get("sentence_id", ""),
        "sentence_context": x.get("context_sentence", ""),
        "slot_kind": x.get("slot_kind", ""),
        "is_primary": bool(x.get("is_primary", False)),
        "sentence_claim_count": int(x.get("sentence_claim_count", 1)),
        "fragment_of_previous": bool(x.get("fragment_of_previous", False)),
        "lead_candidates": x.get("lead_candidates", []),
        "type": x["type"],
        "verdict": x["verdict"],
        "confidence": x.get("confidence", "n/a"),
        "mode": x.get("_mode") or "",
        "evidence": x.get("evidence", []),
        "notes": x.get("suggestion") or x.get("note") or "",
        "search_suggestions": x.get("manual_checks") or [],
        "explanation": explanation,
        "status": "pending_user_review",
        "anchored": None if x.get("para") is None else bool(x.get("anchored", False)),
    }


def write_jsonl(findings, path):
    with open(path, "w", encoding="utf-8") as f:
        for x in findings:
            f.write(json.dumps(to_record(x), ensure_ascii=False) + "\n")


LABELS_ZH = {
    "report": "事实核查报告", "run": "运行", "engine": "引擎", "document": "文档",
    "words": "字", "paragraphs": "段", "corpus": "自带上游语料 (BYOS)",
    "summary": "摘要", "evidence": "证据", "suggestion": "建议",
    "confidence": "置信度", "claim_item": "核查项", "open_note":
    "> 结论以所列证据为限。`unverified`（未证实）表示在现有资料中未找到证据，不代表该说法为假。",
    "verdicts": {
        "supported": "有证据支持", "contradicted": "证据相悖",
        "unverified": "未证实", "internal_conflict": "文内矛盾",
        "paraphrase_flag": "疑似改写", "misattributed": "疑似张冠李戴",
        "conflicting": "来源相左（请裁决）",
        "narrative": "叙述性文字（无需核查）",
        "needs_fix": "需修正", "structure": "结构问题", "deferred_web": "待联网核查",
    },
    "timelines": "时间线（按实体，最早在前）", "web": "联网检索",
}
EN_ONLY_NOTE = ""


def _L(meta, key):
    zh = meta.get("lang") == "zh"
    if not zh:
        return None
    return LABELS_ZH.get(key)


def _vlabel(meta, verdict):
    zh = meta.get("lang") == "zh"
    if zh:
        return f"{LABELS_ZH['verdicts'].get(verdict, verdict)} {verdict}"
    return verdict.upper()


def _ev_lines(x):
    out = []
    for e in x.get("evidence", []):
        tag = {"local": "[LOCAL]", "web": "[WEB]", "fx": "[FX]"}.get(e["kind"], "[?]")
        side = {"support": " (supports)", "contradict": " (against)"}.get(
            e.get("side"), "")
        loc = ""
        if e.get("source_id"):
            loc += f" (source={e['source_id']}"
            loc += f", p.{e['page']})" if e.get("page") else ")"
        elif e.get("page"):
            loc += f" (p.{e['page']})"
        if e.get("page_unavailable"):
            loc += " (page unavailable)"
        out.append(f"- {tag} `{e['ref']}`{loc} — “{e['quote']}”{side}")
    return out


def write_md(meta, findings, path):
    zh = meta.get("lang") == "zh"

    def L(en, zh_text):
        return zh_text if zh else en

    lines = [f"# {L('Fact-Check Report', '事实核查报告')} — {meta['doc']}", ""]
    lines.append(f"- {L('Run', '运行')}: {meta['run']} | {L('Engine', '引擎')}: {meta['engine']}")
    if meta.get("cancelled"):
        lines.append(f"- **{L('CANCELLED BY USER — partial run.', '用户取消 — 部分结果。')}** "
                     + L("Everything already checked is below; unchecked items say "
                         "'cancelled'. Re-run any time.",
                         "已完成核查的内容见下文；未核查项标注为“已取消”。可随时重新运行。"))
    lines.append(f"- {L('Document', '文档')}: {meta['words']} {L('words', '字')}, "
                 f"{meta['paras']} {L('paragraphs', '段')}, lang={meta['lang']}")
    if meta.get("sentence_count") is not None:
        lines.append(
            f"- {L('Sentences / claims', '句子 / claim')}: "
            f"{meta['sentence_count']} / {meta['claim_count']} "
            f"({L('structure', '结构')} {meta.get('structure_count', 0)})")
    if meta.get("context") and meta["context"].get("subject"):
        ctx = meta["context"]
        origin = f" [origin: {ctx['origin_language']}] " if ctx.get("origin_language") else " "
        lines.append(f"- Subject (inferred): **{ctx['subject']}**"
                     + origin
                     + f"(people: {', '.join(ctx.get('people', [])[:8]) or '—'}); "
                     "used to anchor and translate web search"
                     + (f" + {meta.get('auto_aliases', 0)} auto-matched aliases"
                        if meta.get("auto_aliases") else ""))
    if meta.get("anchor_total") is not None:
        lines.append(f"- {L('Anchors (for UI highlight/annotation)', '定位锚点（供高亮/批注）')}: "
                     f"{meta['anchor_ok']}/{meta['anchor_total']} {L('exact', '精确')}")
    lines.append(f"- {L('BYOS corpus', '自带上游语料 (BYOS)')}: {meta['corpus_files']} "
                 f"{L('files', '个文件')} / {meta['corpus_lines']} {L('lines', '行')}"
                 + ("" if meta["corpus_lines"] else f"  ({L('none — web-dependent claims unverified', '无 — 需联网的条目未核实')})"))
    if meta.get("mode"):
        lines.append(f"- Mode: `{meta['mode']}`"
                     + (" — no network requests were made"
                        if meta["mode"] == "sources_only" else ""))
    if meta.get("free_tier"):
        cap = meta.get("free_tier_search_cap", 40)
        lines.append(f"- **{L('Free tier', '免费层')}**: " + L(
            f"web search capped at {cap} per document; claims reached after "
            "the cap are marked not checked, not unverified.",
            f"联网检索上限 {cap} 次/文档；达到上限后未检查的条目会标为"
            "“未检查”，不会当作“查过但找不到”。"))
    if meta.get("byos_sources"):
        lines.append(f"- BYOS library: {meta['byos_sources']} sources"
                     + (f"; {meta['byos_no_text_layer']} with no text layer "
                        "(convert externally before trusting a miss)"
                        if meta.get("byos_no_text_layer") else ""))
    if meta.get("web_search_budget"):
        ents = ", ".join(meta.get("web_entities") or []) or L("none detected", "未检测到")
        lines.append(f"- {L('Web', '联网检索')}: {meta.get('web_searches_used', 0)}/{meta['web_search_budget']} "
                     f"{L('searches used (free keyless tier)', '次检索（免费无需密钥）')}"
                     + (f"; {meta.get('web_pages_read', 0)} {L('pages deep-read', '次全文深读')}"
                        if meta.get("web_pages_read") else "")
                     + (f"; {meta.get('web_cache_hits', 0)} {L('cache hits (free)', '次缓存命中（免费）')}"
                        if meta.get("web_cache_hits") else "")
                     + (f"; {L('backends', '检索后端')}: {meta['web_backends']}"
                        if meta.get("web_backends") else "")
                     + f"; {L('entity anchor: a snippet must name one of', '联网证据须命中以下实体之一')}: {ents}")
        if meta.get("web_checked") is not None:
            lines.append(f"- {L('Coverage', '覆盖率')}: {meta.get('web_checked', 0)} "
                         f"{L('claims were web-searched; unverified items each say why and give hand-search queries', '条声明经过联网检索；每个未证实项都说明原因并给出人工搜索建议')}")
        if meta.get("web_exhausted"):
            lines.append(f"- **{L('INCOMPLETE — resume', '未完成 — 可续跑')}**: "
                         f"{L('web budget reached; remaining web items were not checked this run.', '联网额度已用尽；本轮未核查依赖联网的条目。')}")
    if meta.get("llm_calls"):
        lines.append(f"- {L('LLM assistance', 'LLM 辅助')}: {meta['llm_calls']} {L('calls (free tier); LLM only judges quoted snippets, never invents verdicts.', '次调用（免费额度）；LLM 仅对引用原文判断，绝不臆造结论。')}")
    if meta.get("semantic_rescued"):
        lines.append(f"- {L('Semantic judge', '语义判断')}: {meta['semantic_rescued']} "
                     f"{L('prose claims supported (support-only, medium confidence; open the attached source to confirm).', '条叙述性声明由语义匹配支持（仅支持、中等置信度；请打开所附来源确认）。')}")
    # Which host actually served the calls. Surfaced because the primary Agnes
    # host is a personal relay: if it lapsed mid-run the reader should see that
    # rather than assume every judgement came from the usual endpoint.
    if meta.get("llm_provider"):
        _prov = f"{meta['llm_provider']}"
        _fb = meta.get("llm_relay_fallbacks") or 0
        if _fb:
            _prov += L(f"  (relay failed {_fb}x this run; the official host took over)",
                       f"（本轮中继失败 {_fb} 次，已改用官方接口）")
        lines.append(f"- {L('LLM provider', 'LLM 提供方')}: {_prov}")
    counts = {}
    for x in findings:
        counts[x["verdict"]] = counts.get(x["verdict"], 0) + 1
    lines.append(f"- {L('Summary', '摘要')}: " + " · ".join(
        f"{v}: {counts[v]}" for v in VERDICT_ORDER if v in counts))
    cov = coverage_counts(findings)
    lines.append("")
    lines.append(f"**{L('Coverage at a glance', '覆盖概览')}**")
    lines.append("")
    lines.append(f"| {L('State', '状态')} | {L('Count', '数量')} | {L('Meaning', '含义')} |")
    lines.append("|---|---:|---|")
    for key in COVERAGE_ORDER:
        n = cov.get(key, 0)
        if key == "other" and not n:
            continue
        label = L(key.replace("_", " ").title(), _COVERAGE_ZH[key])
        meaning = L(_COVERAGE_EN[key], _COVERAGE_ZH[key])
        lines.append(f"| {label} | {n} | {meaning} |")
    lines.append("")
    lines.append(L("> Verdicts reflect the evidence shown, nothing more. `unverified` "
                   "means no evidence was found in the provided sources — not that the claim is false.",
                   "> 结论以所列证据为限。`unverified`（未证实）表示现有资料中未找到证据，并不代表该说法为假。"))
    if counts.get("conflicting"):
        lines.append(L("> `conflicting` means live sources DISAGREE with each other: both "
                       "camps are shown below tagged (supports)/(against) — open them and decide.",
                       "> `conflicting`（来源相左）表示不同来源互相矛盾：下方列出双方证据并标注"
                       "（支持）/（反对），请打开来源自行裁决。"))
    grouped = {}
    for x in findings:
        grouped.setdefault(x["verdict"], []).append(x)
    for verdict in VERDICT_ORDER:
        items = grouped.get(verdict, [])
        if not items:
            continue
        lines.append(f"\n## {_vlabel(meta, verdict)} ({len(items)})\n")
        for x in items:
            anchor = f"¶{x['para'] + 1}" if x.get("para") is not None else "—"
            lines.append(f"### {x['id']} — {x['type']} — {anchor}")
            lines.append("")
            lines.append(f"> {x.get('sentence_context') or x['sentence']}")
            if x.get("fragment_of_previous"):
                lines.append(
                    f"> *{L('continued from the previous sentence', '接上一句')}*")
            lines.append("")
            lines.append(f"- **{L('Claim item', '核查项')}:** `{x['raw']}`")
            lines.append(f"- **{L('Confidence', '置信度')}:** {x.get('confidence', 'n/a')}")
            if x.get("suggestion"):
                lines.append(f"- **{L('Suggestion', '建议')}:** {x['suggestion']}")
            if x.get("manual_checks"):
                lines.append(
                    f"- **{L('Search yourself', '自行搜索')}:** "
                    + "  |  ".join(f"`{q}`" for q in x["manual_checks"]))
            leads = x.get("lead_candidates") or []
            if len(leads) > 1:
                lines.append(
                    f"- **{L('Other leads', '其他线索')}:** "
                    + "  |  ".join(f"`{lead['fname']}:{lead['start']}`"
                                   for lead in leads[1:]))
            _pl = provenance.render_md(provenance.explain(x, zh), zh)
            if len(_pl) > 1:
                lines.append("")
                lines.extend(_pl)
            if x.get("user_status"):
                lines.append(f"- **{L('User decision', '用户裁决')}:** {x['user_status']}")
            ev = _ev_lines(x)
            if ev:
                lines.append(f"- **{L('Evidence', '证据')}:**")
                lines.extend("  " + e for e in ev)
            lines.append("")
    tl = meta.get("timelines") or {}
    tl_ents = {e: t for e, t in tl.items() if t}
    if tl_ents:
        lines.append(f"\n## {L('TIMELINES (per entity, earliest first)', '时间线（按实体，最早在前）')}\n")
        for ent, t in tl_ents.items():
            lines.append(f"**{ent}**")
            for ev, by_year in sorted(t.items()):
                span = f"{min(by_year)}–{max(by_year)}" if len(by_year) > 1 else str(min(by_year))
                lines.append(f"- {ev}: {span} — " + ", ".join(str(y) for y in sorted(by_year)))
            lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def _cell(s):
    s = str(s) if s is not None else ""
    return s if len(s) <= 32000 else s[:31990] + "…[trunc]"


def write_xlsx(meta, findings, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    headers = ["No.", "Type", "Anchor", "Claim", "Verdict", "Confidence",
               "Evidence (file:line)", "Why (checks run)", "Suggestion", "Status"]
    ws.append(headers)
    for c in ws[1]:
        c.fill = PatternFill("solid", fgColor="1F4E78")
        c.font = Font(bold=True, color="FFFFFF")
    for x in findings:
        ev = "\n".join(f"{e['ref']}: {e['quote']}" for e in x.get("evidence", []))
        ws.append([_cell(v) for v in (
            x["id"], x["type"],
            f"¶{x['para'] + 1}" if x.get("para") is not None else "—",
            x["raw"], x["verdict"], x.get("confidence", "n/a"), ev,
            provenance.render_inline(provenance.explain(x)),
            x.get("suggestion", ""), x.get("user_status") or "pending_review")])
        fill = PatternFill("solid", fgColor=FILLS.get(x["verdict"], "FFFFFF"))
        for c in ws[ws.max_row]:
            c.fill = fill
            c.alignment = Alignment(vertical="top", wrap_text=True)
    widths = [7, 10, 7, 45, 16, 11, 55, 60, 50, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    # One-screen coverage sheet: what is proven, what needs attention, and what
    # was never checked. "Not checked" is not a negative finding.
    cov = coverage_counts(findings)
    cs = wb.create_sheet("Coverage")
    cs.append(["State", "Count", "Meaning"])
    for c in cs[1]:
        c.fill = PatternFill("solid", fgColor="1F4E78")
        c.font = Font(bold=True, color="FFFFFF")
    for key in COVERAGE_ORDER:
        n = cov.get(key, 0)
        if key == "other" and not n:
            continue
        cs.append([key.replace("_", " ").title(), n, _COVERAGE_EN[key]])
    for i, w in enumerate([26, 10, 70], 1):
        cs.column_dimensions[chr(64 + i)].width = w
    cs.freeze_panes = "A2"
    wb.save(path)


def write_diff_md(summary, findings, path, name_a="A", name_b="B"):
    lines = [f"# Version Diff — {name_a} vs {name_b}", ""]
    lines.append(f"- {name_a}: {summary['a_paras']} paragraphs | "
                 f"{name_b}: {summary['b_paras']} paragraphs")
    lines.append(f"- Drift items: {summary['findings']}")
    lines.append("")
    lines.append("> Fact-set comparison (values, alias-canonical names, URLs). "
                 "Quote wording is intentionally not compared across languages.")
    lines.append("")
    for x in findings:
        lines.append(f"- [ ] {x['raw']}")
    if not findings:
        lines.append("- (no drift detected between the two versions)")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def from_record(r):
    """Rebuild a claim-shaped dict from a §7 record — enough to re-render
    report.md / report.xlsx after user decisions (evidence/anchors pass through
    verbatim, decision lands in user_status)."""
    span = r.get("source_span") or {}
    decided = r.get("status") != "pending_user_review"
    return {
        "id": r["claim_id"], "type": r["type"], "raw": r["quote"],
        "sentence": r.get("context", ""), "verdict": r["verdict"],
        "sentence_id": r.get("sentence_id", ""),
        "context_sentence": r.get("sentence_context", ""),
        "slot_kind": r.get("slot_kind", ""),
        "is_primary": bool(r.get("is_primary", False)),
        "sentence_claim_count": int(r.get("sentence_claim_count", 1)),
        "fragment_of_previous": bool(r.get("fragment_of_previous", False)),
        "lead_candidates": r.get("lead_candidates", []),
        "confidence": r.get("confidence", "n/a"),
        "evidence": r.get("evidence", []),
        "suggestion": r.get("notes", ""),
        "manual_checks": r.get("search_suggestions", []),
        "explain": r.get("explanation", {}),
        "para": span.get("para"),
        "span": [span.get("start", 0), span.get("end", 0)],
        "anchored": r.get("anchored"),
        "user_status": (r["status"] + (f" — {r['user_note']}" if r.get("user_note") else ""))
        if decided else "",
    }


def rerender_with_decisions(out_dir, meta, records):
    """Rewrite claims.jsonl / report.md / report.xlsx so every export reflects
    the user's decisions. Returns the list of re-written file names."""
    out = Path(out_dir)
    claims = [from_record(r) for r in records]
    with open(out / "claims.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_md(meta, claims, str(out / "report.md"))
    write_xlsx(meta, claims, str(out / "report.xlsx"))
    return ["claims.jsonl", "report.md", "report.xlsx"]
