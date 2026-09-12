from . import corpus as corp
from . import checks
from . import textproc as tp
from . import web as webmod

FLAG_VERDICTS = {"contradicted", "internal_conflict", "paraphrase_flag",
                 "misattributed", "needs_fix", "structure", "conflicting"}


def _line_values(line):
    return tp.extract_values(line)


def _evidence(fname, lineno, raw, note="", precision="line"):
    return {"kind": "local", "ref": f"{fname}:{lineno}", "quote": corp.clip(raw),
             "precision": precision, "note": note}


def _check_number(claim, corpus):
    kws = corpus.rare_tokens(claim["sentence"])
    if not kws or not corpus.lines:
        return "unverified", "low", [], "No subject keyword found in corpus."
    lines = corpus.find_lines(kws, 1)
    if not lines:
        return "unverified", "low", [], "No corpus line about this subject."
    ctx = []
    cur_clash = []
    mod = webmod.modifier(claim)
    for shared_n, fname, lineno, raw, shared, precision in lines:
        # uniform subject-overlap bar; years are protected from false
        # contradiction by the PREDICATE guard below (event match or >=2 shared
        # non-name content tokens), not by a raw token count tuned per doc
        need = 2
        strong = shared_n >= need and (claim["type"] == "year"
                                       or any(corpus.df.get(t, 0) == 1 for t in shared))
        vals = _line_values(raw)
        same_kind = [v for v in vals
                     if v["kind"] == claim["type"]
                     and (claim["type"] != "amount"
                          or tp.currency_compatible(claim["currency"], v["currency"]))]
        if shared_n >= 2 and any(webmod.num_matches(claim, v, mod) for v in same_kind):
            return "supported", "high" if strong else "medium", [
                _evidence(fname, lineno, raw, precision=precision)], ""
        # identical figure, different currency, same subject = contradiction
        diff_cur = [v for v in vals
                    if v["kind"] == claim["type"] == "amount"
                    and v["currency"] and claim["currency"]
                    and not tp.currency_compatible(claim["currency"], v["currency"])
                    and tp.values_equal(claim["value"], v["value"], kind="amount")]
        if shared_n >= 2 and diff_cur:
            cur_clash.append((fname, lineno, raw, diff_cur, precision))
        ctx.append((fname, lineno, raw, same_kind, strong, precision, set(shared)))
    if cur_clash:
        fname, lineno, raw, diff_cur, precision = cur_clash[0]
        return ("contradicted", "high",
                [_evidence(fname, lineno, raw, precision=precision)],
                f"Same figure {claim['raw']} appears in the source as "
                f"{', '.join(v['raw'] for v in diff_cur)} — currency mismatch.")
    # no match: contradict only on strong subject lines that carry a different
    # value AND agree on the predicate — a line that merely shares the person's
    # name while stating a different event's date must not contradict (1984 bug).
    claim_event = tp.event_of(tp.normalize(claim["sentence"]))
    claim_names = tp.name_tokens(claim["sentence"])
    for fname, lineno, raw, same_kind, strong, precision, shared in ctx:
        if not (strong and same_kind):
            continue
        line_event = tp.event_of(tp.normalize(raw))
        predicate_ok = (
            (claim_event is not None and claim_event == line_event)
            or len(shared - claim_names - tp.name_tokens(raw)) >= 2)
        if not predicate_ok:
            continue
        cf = [v for v in same_kind if webmod.num_conflicts(claim, v, mod)]
        if not cf:
            continue  # values are consistent with an 'over/approx' phrasing
        diff = ", ".join(sorted({v["raw"] for v in cf}))
        return ("contradicted", "medium",
                [_evidence(fname, lineno, raw, precision=precision)],
                f"Corpus states {diff} here, document says {claim['raw']}.")
    if ctx:
        return "unverified", "low", [], \
            "Subject found in corpus but value not confirmed."
    return "unverified", "low", [], "No corpus line about this subject."


def _check_quote(claim, corpus):
    if not corpus.lines:
        return "unverified", "low", [], "No corpus provided."
    ratio, fname, lineno, raw, precision = corpus.best_quote_match(claim["raw"])
    ev = [_evidence(fname, lineno, raw, precision=precision)] if fname else []
    # attribution check: a genuine quote can still be pinned to the wrong person
    doc_speaker = tp.speaker_before_quote(claim["sentence"])
    src_speaker = tp.speaker_before_quote(raw) if fname else None
    mis = tp.names_conflict(doc_speaker, src_speaker)
    if mis and ratio >= corp.PARAPHRASE_CUT:
        return "misattributed", "medium", ev, (
            f"Quote text matches ({ratio:.0%}) but is said by "
            f"'{src_speaker}' in the source, not '{doc_speaker}'.")
    if ratio >= corp.VERBATIM_CUT:
        return "supported", "high", ev, f"Verbatim match ({ratio:.0%})."
    if ratio >= corp.PARAPHRASE_CUT:
        return "paraphrase_flag", "medium", ev, (
            f"Closest original differs ({ratio:.0%} similar) — quote may be "
            f"embellished; verify before presenting as verbatim.")
    return "unverified", "low", [], (
        f"Best corpus similarity only {ratio:.0%} — possibly fabricated "
        "or from an uncaptured source.")


def judge(claims, corpus, progress=None):
    _p = progress or (lambda e: None)
    for c in claims:
        _p({"stage": "check", "id": c["id"], "type": c["type"],
            "item": c["raw"][:70]})
        if c["type"] == "placeholder":
            c["verdict"], c["confidence"], c["evidence"] = "needs_fix", "high", []
            c["suggestion"] = "Unresolved placeholder in final text — remove or fill."
            continue
        if c["type"] == "url":
            c["verdict"], c["confidence"], c["evidence"] = "deferred_web", "n/a", []
            c["suggestion"] = "URL liveness/title check requires web module (M2)."
            continue
        if c["type"] == "quote":
            v, conf, ev, note = _check_quote(c, corpus)
        elif c["type"] in ("year", "amount", "pct", "count"):
            v, conf, ev, note = _check_number(c, corpus)
        else:
            v, conf, ev, note = "unverified", "low", [], ""
        c["verdict"], c["confidence"], c["evidence"] = v, conf, ev
        c["suggestion"] = note

    for cs, msg in checks.internal_conflicts(claims):
        for c in cs:
            c["verdict"] = "internal_conflict"
            c["confidence"] = "high"
            c["suggestion"] = msg
    return claims
