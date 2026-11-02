"""Explain a verdict in plain words, from the checks that actually ran.

Template-only by design. This module renders structure that the judge already
computed; it never re-judges, never sees the source lines as its own input, and
cannot change a verdict. That is the whole point: an LLM asked to "explain this
verdict" will smooth a caveat away, and a smoothed caveat is a false green in
prose (see HANDOFF rule 18 for the same argument on the subject check).

The judge records `explain` on a claim as it decides it -- attached at the
return site, so the checks shown are literally the ones that produced the
verdict, not a re-derivation that could drift from it. Findings that never
recorded checks (prose, quotes, structural notes) degrade to a headline plus
whatever the judge already said.
"""

PASS, FAIL, UNRUN = "pass", "fail", "unrun"
GLYPH = {PASS: "\u2713", FAIL: "\u2717", UNRUN: "\u2014"}

CHECKS = {
    "subject": ("Same subject", "\u540c\u4e00\u4e3b\u4f53"),
    "figure": ("Same figure", "\u6570\u503c\u4e00\u81f4"),
    "event": ("Same event", "\u540c\u4e00\u4e8b\u4ef6"),
    "unit": ("Same unit", "\u5355\u4f4d\u4e00\u81f4"),
}

HEADLINE = {
    "supported": ("Confirmed by the evidence shown",
                  "\u8bc1\u636e\u652f\u6301\u8be5\u8bf4\u6cd5"),
    "contradicted": ("The evidence disagrees",
                     "\u8bc1\u636e\u4e0e\u8be5\u8bf4\u6cd5\u4e0d\u7b26"),
    "unverified": ("Could not confirm this one",
                   "\u672a\u80fd\u786e\u8ba4"),
    "conflicting": ("Sources disagree with each other",
                    "\u4e0d\u540c\u6765\u6e90\u4e92\u76f8\u77db\u76fe"),
    "internal_conflict": ("This contradicts something else in your own document",
                          "\u4e0e\u6587\u6863\u5185\u5176\u4ed6\u5185\u5bb9\u77db\u76fe"),
    "narrative": ("Narrative text \u2014 nothing to check",
                  "\u53d9\u8ff0\u6027\u6587\u5b57\u2014\u2014\u65e0\u9700\u6838\u67e5"),
    "needs_fix": ("Needs a fix before it ships",
                  "\u9700\u4fee\u6b63"),
}

ASSISTED = ("Subject match was confirmed by a language model, not by matching "
            "words. The figure and the event were still checked by code.",
            "\u4e3b\u4f53\u4e00\u81f4\u6027\u7531\u6a21\u578b\u786e\u8ba4\uff08\u975e\u8bcd\u9762"
            "\u5339\u914d\uff09\uff0c\u6570\u503c\u4e0e\u4e8b\u4ef6\u4ecd\u7531\u7a0b\u5e8f"
            "\u786e\u8ba4\u3002")

# Milestone names, so the reason reads in the reader's language. The key set is
# fixed by textproc.EVENT_ANCHORS; a missing key falls back to the raw key rather
# than silently rendering an empty reason.
EVENTS = {
    "founding": ("founding", "\u521b\u7acb"),
    "launch": ("launch", "\u4e0a\u5e02 / \u53d1\u5e03"),
    "acquisition": ("an acquisition", "\u6536\u8d2d"),
    "funding_round": ("a funding round", "\u878d\u8d44"),
    "naming": ("a name change", "\u66f4\u540d"),
    "shutdown": ("a closure", "\u5173\u505c"),
    "ipo": ("an IPO", "\u4e0a\u5e02"),
}

# Detail templates: id -> (en, zh). `judge.py` records only the id and the
# slots, so every user-facing sentence lives here and can be re-phrased without
# touching a decision. A missing id renders an empty reason rather than a lie.
DETAILS = {
    "subj_ok": ("source names the same subject",
                "\u6765\u6e90\u786e\u5b9e\u63d0\u5230\u540c\u4e00\u4e3b\u4f53"),
    "subj_ok_n": ("source names the same subject ({n} shared terms)",
                  "\u6765\u6e90\u786e\u5b9e\u63d0\u5230\u540c\u4e00\u4e3b\u4f53"
                  "\uff08{n} \u4e2a\u5171\u540c\u8bcd\uff09"),
    "subj_ok_model": ("a model judged these to be the same subject",
                      "\u7531\u6a21\u578b\u5224\u65ad\u4e24\u8005\u662f\u540c\u4e00\u4e3b\u4f53"),
    "subj_fail": ("no source line about this subject",
                  "\u6765\u6e90\u4e2d\u6ca1\u6709\u5173\u4e8e\u8be5\u4e3b\u4f53\u7684\u5185\u5bb9"),
    "fig_ok": ("source states {v}", "\u6765\u6e90\u5199\u660e {v}"),
    "fig_ok_appear": ("the figure {v} does appear in the source",
                      "\u6570\u5b57 {v} \u786e\u5b9e\u51fa\u73b0\u5728\u6765\u6e90\u4e2d"),
    "fig_ok_same": ("same figure {v}", "\u76f8\u540c\u7684\u6570\u5b57 {v}"),
    "fig_ok_plain": ("the figure matched, without needing the model",
                     "\u6570\u5b57\u5df2\u5339\u914d\uff0c\u65e0\u9700\u6a21\u578b\u5e2e\u5fd9"),
    "fig_fail_diff": ("document says {a}, source says {b}",
                      "\u6587\u6863\u5199 {a}\uff0c\u6765\u6e90\u5199 {b}"),
    "fig_fail_absent": ("the source does not state this figure",
                        "\u6765\u6e90\u6ca1\u6709\u5199\u51fa\u8fd9\u4e2a\u6570\u5b57"),
    "evt_ok_plain": ("the milestone matched, without needing the model",
                     "\u4e8b\u4ef6\u5df2\u5339\u914d\uff0c\u65e0\u9700\u6a21\u578b\u5e2e\u5fd9"),
    "event_same": ("both about {what}", "\u4e24\u8fb9\u90fd\u662f\u5173\u4e8e{what}"),
    "event_mismatch": ("your claim is about {claim}, the source line is about {line}",
                       "\u4f60\u7684\u8bf4\u6cd5\u662f\u5173\u4e8e{claim}\uff0c"
                       "\u800c\u6765\u6e90\u90a3\u4e00\u884c\u662f\u5173\u4e8e{line}"),
    "event_na": ("one side names no milestone, so this was not required",
                 "\u4e00\u8fb9\u6ca1\u6709\u5199\u660e\u4e8b\u4ef6\uff0c\u56e0\u6b64\u8fd9\u4e00\u9879"
                 "\u65e0\u9700\u4e25\u683c\u6838\u5bf9"),
    "unit_ok": ("both in {cur}", "\u4e24\u8fb9\u5747\u4e3a {cur}"),
    "unit_fail": ("claim is {a}, source is {b}",
                  "\u6587\u6863\u4e3a {a}\uff0c\u6765\u6e90\u4e3a {b}"),
}


def _phrase(detail, zh):
    """Turn a recorded detail into a sentence in the reader's language."""
    if not detail:
        return ""
    if isinstance(detail, str):
        return detail
    tpl = DETAILS.get(detail.get("t", ""))
    if not tpl:
        return ""
    slots = {k: (EVENTS.get(v, ("", v))[1] if zh else EVENTS.get(v, (v, v))[0])
             for k, v in detail.items() if k != "t"}
    return tpl[1 if zh else 0].format(**slots)


NEXT = ("Try searching for", "\u53ef\u5c1d\u8bd5\u641c\u7d22")


def _labels(zh):
    return {k: (v[1] if zh else v[0]) for k, v in CHECKS.items()}


def explain(finding, zh=False):
    """Return a structured explanation for one finding. Never raises."""
    verdict = finding.get("verdict", "")
    head = HEADLINE.get(verdict)
    if head is None:
        head = (verdict or "unverified",
                verdict or "\u672a\u80fd\u786e\u8ba4")
    out = {
        "verdict": verdict,
        "headline": head[1] if zh else head[0],
        "checks": [],
        "assisted": bool(finding.get("explain", {}).get("assisted")),
        "next": list(finding.get("manual_checks") or []),
        "origin": finding.get("explain", {}).get("origin", ""),
    }
    raw = finding.get("explain", {}).get("checks") or []
    labels = _labels(zh)
    for c in raw:
        key = c.get("key", "")
        if key not in labels:
            continue
        out["checks"].append({
            "label": labels[key],
            "status": c.get("status", UNRUN),
            "glyph": GLYPH.get(c.get("status", UNRUN), GLYPH[UNRUN]),
            "detail": _phrase(c.get("detail", ""), zh),
        })
    return out


def render_inline(expl):
    """One-cell summary, for the xlsx 'Explanation' column."""
    if expl["checks"]:
        return expl["headline"] + " \u2014 " + " \u00b7 ".join(
            f"{c['label']} {c['glyph']}"
            + (f" ({c['detail']})" if c["detail"] else "")
            for c in expl["checks"])
    return expl["headline"]


def render_md(expl, zh=False):
    """The explanation as markdown lines, for the report."""
    lines = [f"**{expl['headline']}**", ""]
    if expl["checks"]:
        for c in expl["checks"]:
            detail = f" \u2014 {c['detail']}" if c["detail"] else ""
            lines.append(f"- {c['glyph']} {c['label']}{detail}")
        lines.append("")
    if expl["assisted"]:
        lines.append(f"> {ASSISTED[1] if zh else ASSISTED[0]}")
        lines.append("")
    for q in expl["next"]:
        lines.append(f"- {NEXT[1] if zh else NEXT[0]}: `{q}`")
    return lines
