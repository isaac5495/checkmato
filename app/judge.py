import re
from concurrent.futures import ThreadPoolExecutor

from . import corpus as corp
from . import checks
from . import jev
from . import textproc as tp
from . import web as webmod

FLAG_VERDICTS = {"contradicted", "internal_conflict", "paraphrase_flag",
                 "misattributed", "needs_fix", "structure", "conflicting"}


def _line_values(line):
    return tp.extract_values(line)


def _predicate_ok(claim, raw, shared, claim_event, claim_names):
    """Does this corpus line describe the SAME milestone as the claim?

    A figure that matches proves nothing when the line is plainly about a
    different event: 'founded in 2011' does not support 'opened its plant in
    2011', it states a different fact that happens to share a year. Measured
    before this guard existed, 5 of 5 such year claims came back `supported`.

    The rule is deliberately IDENTICAL for `supported` and `contradicted` —
    the contradiction path had it while the support path did not, and that
    asymmetry is exactly how false greens entered. One definition, so the two
    paths cannot drift apart again: a guard that protects one verdict and not
    the other is a bug, whichever way it points.
    """
    line_event = tp.event_of(tp.normalize(raw))
    if claim_event is not None and line_event is not None:
        if claim_event == line_event:
            return True
    elif len(shared - claim_names - tp.name_tokens(raw)) >= 2:
        # at least one side names no milestone, so the event cannot be compared
        # — fall back to requiring two shared non-name content words
        return True
    return False


_LEVEL_MARKERS = {
    # a claim that names a different level/type of entity must not borrow the
    # parent's fact; these are generic organisational markers, not case data
    "cloud", "subsidiary", "holdings", "hospitals", "hospital", "labs",
    "bank", "insurance", "capital", "ventures",
    "\u4e91", "\u96f2", "\u533b\u9662", "\u91ab\u9662", "\u5b9e\u9a8c\u5ba4",
    "\u5be6\u9a57\u5ba4", "\u5b50\u516c\u53f8",
}


def _has_cjk(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _contains_entity(text, ent):
    """Token-boundary containment for Latin names, plain substring for CJK."""
    if not ent:
        return False
    if ent.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(ent) + r"(?![a-z0-9])",
                         text) is not None
    return ent in text


def _entity_like(ent):
    """Reject grammar fragments that detect_entities can emit for CJK docs."""
    if re.fullmatch(r"[\u4e00-\u9fff]{2,12}", ent):
        return True
    return bool(re.fullmatch(
        r"[A-Za-z][A-Za-z0-9&.'-]*(?:\s+[A-Za-z][A-Za-z0-9&.'-]*){0,3}", ent))


def _cjk_prefix_anchor(s_norm, ents):
    """The longest detected-name prefix the claim actually uses.

    Chinese sources rarely repeat the full legal name: a claim says 金山软件
    while the entity list holds 金山软件公益基金会, and a claim says 金山 for
    either. Anchoring on the longest shared prefix keeps the family (金山) and
    the specific form (金山软件) without accepting a sibling (金山办公).
    """
    best = ""
    for e in ents:
        if not e or e.isascii():
            continue
        for size in range(min(len(e), len(s_norm)), 1, -1):
            prefix = e[:size]
            if prefix in s_norm:
                if len(prefix) > len(best):
                    best = prefix
                break
    return best


def _names_present(claim, raw, doc_entities=()):
    """Does the candidate line name the claim's subject?

    Latin names are reliable; Chinese per-sentence name tokens are not (they
    return bigrams like "是他"/"于是"). A known entity is therefore required in
    full: a shared prefix is not the same subject (Caelum Labs vs Caelum Cloud,
    恒宇健康 vs 恒宇科技/恒宇云). A short form is still accepted when the
    evidence names no sibling entity, so a documented alias does not become a
    false negative. A claim with no detected name skips the guard.
    """
    sentence = claim.get("sentence") or ""
    s_norm = tp.normalize(sentence)
    text = tp.normalize(raw)
    ents = sorted({tp.normalize(e) for e in (doc_entities or ())
                   if e and _entity_like(str(e))}, key=len, reverse=True)
    claim_ents = [e for e in ents if _contains_entity(s_norm, e)]
    anchor = claim_ents[0] if claim_ents else ""
    if not anchor:
        prefix = _cjk_prefix_anchor(s_norm, ents)
        # A bare 2-char head (金山) is too weak to anchor: it is often an
        # incidental mention, and demanding it on every line cost Chinese
        # recall. Three characters (金山云, 西山居) or a full entity is a name.
        anchor = prefix if len(prefix) >= 3 else ""
    if anchor:
        if _contains_entity(text, anchor):
            return True
        head = tp.entity_head(anchor)
        rivals = [e for e in ents
                  if e != anchor and head and (head in e or e in head)
                  and _contains_entity(text, e)]
        if rivals or not head or not _contains_entity(text, head):
            return False
        return True
    names = tp.name_tokens(sentence)
    if not names:
        return True
    reliable = {n for n in names if n.isascii()}
    latin_ents = {e for e in ents if e.isascii()}
    if latin_ents:
        reliable |= {t for t in tp.tokens(sentence)
                     if any(t in e or e in t for e in latin_ents)}
    if not reliable:
        return False
    if not any(n in text for n in reliable):
        if not (all(n.isascii() for n in reliable) and _has_cjk(text)):
            return False
    low = tp.normalize(sentence)
    for marker in _LEVEL_MARKERS:
        if not marker.isascii():
            continue  # CJK descriptors are not entity-level markers
        if marker in low and marker not in text:
            return False
    return True


_ANAPHORIC = ("it ", "its ", "they ", "their ", "the company", "this ",
              "that ", "these ", "those ", "该", "該", "其", "这", "這",
              "那", "公司", "集团", "集團")


def _value_sentence(text, needle):
    """The sentence that carries the matched figure, so the subject check is
    local to the fact rather than to a multi-line passage."""
    if not needle:
        return text
    spans = [s for s, _ in tp.sentences_spans(text)]
    for s in spans:
        if needle in s:
            return s
    n = tp.normalize(needle)
    for s in spans:
        if n and n in tp.normalize(s):
            return s
    return text


_FACILITY = (r"(?:plant|factory|office|facility|branch|store|warehouse|site|"
             r"centre|center|hub|campus|hospital|school|university|lab|"
             r"laboratory|subsidiary)")
_LOC_PREP = r"(?:in|at|near|outside|across|from)"
_VENUE_RX = re.compile(
    rf"(?:\b{_LOC_PREP}\s+)([A-Z][A-Za-z'\u00c0-\u00ff\-]{{2,}})"
    rf"|([A-Z][A-Za-z'\u00c0-\u00ff\-]{{2,}})\s+{_FACILITY}\b")


def _venue_tokens(sentence):
    """Place-like names in a sentence: after a locative preposition ("in
    Bergen") or before a facility noun ("Bergen plant"). A co-founder's name is
    not a venue, so the guard never mistakes an extra person for another site."""
    out = set()
    for m in _VENUE_RX.finditer(sentence or ""):
        w = (m.group(1) or m.group(2) or "").lower()
        if w and w not in tp.STOP:
            out.add(w)
    return out


def _same_instance(claim, raw, needle):
    """Are the claim and the source sentence about the SAME place?

    A contradiction needs the same milestone on the same thing. "Foo's Bergen
    plant opened in 2011" vs "Foo's Oslo plant opened in 2012" is a different
    venue. Only venue-like names are compared: a source that merely adds a
    co-founder or an attribution is still the same instance, and a source with
    no venue at all skips the guard.
    """
    a = _venue_tokens(_value_sentence(claim.get("sentence") or "",
                                       claim.get("raw")))
    b = _venue_tokens(_value_sentence(raw, needle or claim.get("raw")))
    return not ((a - b) and (b - a))


def _previous_sentence(text, sentence):
    spans = [s for s, _ in tp.sentences_spans(text)]
    for i, s in enumerate(spans):
        if s == sentence and i:
            return spans[i - 1]
    return ""


def _anaphoric(sentence):
    """A sentence that names no subject because it points at the previous one."""
    low = tp.normalize(sentence).lstrip()
    return any(low.startswith(a) for a in _ANAPHORIC)


def _evidence(fname, lineno, raw, note="", precision="line", corpus=None):
    ev = {"kind": "local", "ref": f"{fname}:{lineno}", "quote": corp.clip(raw),
          "precision": precision, "note": note}
    if corpus is not None:
        sid = getattr(corpus, "source_by_file", {}).get(fname)
        if sid:
            ev["source_id"] = sid
            page = getattr(corpus, "page_map", {}).get((fname, lineno))
            if page is not None:
                ev["page"] = page
    return ev


# --- verdict provenance (app/explain.py renders this; see HANDOFF rule 18) ---
# Recorded at the return site, not re-derived afterwards, so the checks a user
# reads are literally the ones that produced the verdict. A re-derivation could
# drift from the code path and explain a decision that never happened.

def _event_detail(claim_event, line_event):
    """Structured, not a finished sentence: app/provenance.py phrases it, so a
    Chinese report gets a Chinese reason from the same recorded data."""
    if claim_event is None or line_event is None:
        return {"t": "event_na"}
    if claim_event == line_event:
        return {"t": "event_same", "what": claim_event}
    return {"t": "event_mismatch", "claim": claim_event, "line": line_event}


def _rec(claim, subject=None, figure=None, event=None, unit=None,
         origin="corpus", assisted=False):
    """Record which checks ran, and how each turned out, as we decide."""
    order = (("subject", subject), ("figure", figure),
             ("event", event), ("unit", unit))
    checks = []
    for key, val in order:
        if val:
            status, detail = val
            checks.append({"key": key, "status": status, "detail": detail})
    claim["explain"] = {
        "checks": checks,
        "origin": origin,
        "assisted": assisted,
    }


def _passage_quote(text, needles, width=260):
    """Window around the matched figure, so clipping cannot hide the evidence."""
    for n in needles:
        if not n:
            continue
        i = text.find(n)
        if i >= 0:
            a = max(0, i - 100)
            return text[a:a + width]
    return text


def _check_number(claim, corpus):
    kws = corpus.rare_tokens(claim.get("_query") or claim["sentence"])
    strict_subject = bool(getattr(corpus, "source_by_file", None))
    if not kws or not corpus.lines:
        return "unverified", "low", [], "No subject keyword found in corpus."
    lines = []
    if claim.get("value") is not None:
        lines = corpus.find_value_lines(
            kws, claim["type"], claim["value"], claim.get("currency"), top=16)
    if not lines:
        lines = corpus.find_lines(kws, 1)
    if not lines:
        return "unverified", "low", [], "No corpus line about this subject."
    ctx = []
    cur_clash = []
    off_event = []
    mod = webmod.modifier(claim)
    claim_event = tp.event_of(tp.normalize(claim["sentence"]))
    claim_names = tp.name_tokens(claim["sentence"])
    for shared_n, fname, lineno, raw, shared, precision in lines:
        # A value match is not a subject match: another subject's revenue must
        # never be supported by this subject's line. If the claim names a
        # subject, the candidate line must name at least one of those tokens.
        if strict_subject and not _names_present(
                claim, raw, claim.get("_doc_entities") or ()):
            continue
        # uniform subject-overlap bar, NOT tuned per doc: `strong` drives
        # confidence and contradiction eligibility, while the PREDICATE guard
        # below decides whether the line is about this claim's milestone at
        # all — and it is deliberately the same guard on both verdicts.
        need = 2
        strong = shared_n >= need and (claim["type"] == "year"
                                       or any(corpus.df.get(t, 0) == 1 for t in shared))
        vals = _line_values(raw)
        same_kind = [v for v in vals
                     if v["kind"] == claim["type"]
                     and (claim["type"] != "amount"
                          or tp.currency_compatible(claim["currency"], v["currency"]))]
        predicate_ok = _predicate_ok(claim, raw, set(shared),
                                     claim_event, claim_names)
        mv = [v for v in same_kind if webmod.num_matches(claim, v, mod)]
        if shared_n >= 2 and predicate_ok and mv:
            _rec(claim,
                 subject=("pass", {"t": "subj_ok_n", "n": shared_n}),
                 figure=("pass", {"t": "fig_ok", "v": mv[0]["raw"]}),
                 event=("pass", _event_detail(
                     claim_event, tp.event_of(tp.normalize(raw)))),
                 unit=(("pass", {"t": "unit_ok", "cur": claim["currency"]})
                       if claim["type"] == "amount" else None),
                 origin=("web" if precision != "line" else "corpus"))
            return "supported", "high" if strong else "medium", [
                _evidence(fname, lineno, raw, precision=precision, corpus=corpus)], ""
        # identical figure, different currency, same subject = contradiction
        diff_cur = [v for v in vals
                    if v["kind"] == claim["type"] == "amount"
                    and v["currency"] and claim["currency"]
                    and not tp.currency_compatible(claim["currency"], v["currency"])
                    and tp.values_equal(claim["value"], v["value"], kind="amount")]
        if shared_n >= 2 and diff_cur:
            cur_clash.append((fname, lineno, raw, diff_cur, precision))
        if not predicate_ok and shared_n >= 2 and same_kind:
            off_event.append((fname, lineno, raw))
        ctx.append((fname, lineno, raw, same_kind, strong, precision, set(shared)))
    if cur_clash:
        fname, lineno, raw, diff_cur, precision = cur_clash[0]
        _rec(claim,
             subject=("pass", {"t": "subj_ok"}),
             figure=("pass", {"t": "fig_ok_same", "v": claim["raw"]}),
             event=("pass", _event_detail(
                 claim_event, tp.event_of(tp.normalize(raw)))),
             unit=("fail", {"t": "unit_fail", "a": claim["currency"],
                            "b": ", ".join(sorted(
                                {v["currency"] for v in diff_cur}))}),
             origin=("web" if precision != "line" else "corpus"))
        return ("contradicted", "high",
                [_evidence(fname, lineno, raw, precision=precision, corpus=corpus)],
                f"Same figure {claim['raw']} appears in the source as "
                f"{', '.join(v['raw'] for v in diff_cur)} — currency mismatch.")
    # no match: contradict only on strong subject lines that carry a different
    # value AND agree on the predicate — a line that merely shares the person's
    # name while stating a different event's date must not contradict (1984 bug).
    for fname, lineno, raw, same_kind, strong, precision, shared in ctx:
        if not (strong and same_kind):
            continue
        cf = [v for v in same_kind if webmod.num_conflicts(claim, v, mod)]
        if not cf:
            continue  # values are consistent with an 'over/approx' phrasing
        if strict_subject:
            # The conflicting figure's own sentence must name this subject.
            # A long paragraph can mention 金山软件 once and still be about
            # 金山办公's 2019 listing; the whole-paragraph check would let the
            # parent's event contradict the subsidiary's.
            subj_text = _value_sentence(raw, cf[0]["raw"])
            if not _names_present(claim, subj_text,
                                  claim.get("_doc_entities") or ()):
                continue  # another subject's value is not a contradiction
        if not _same_instance(claim, raw, cf[0]["raw"]):
            continue  # another venue/product is a different instance
        if not _predicate_ok(claim, raw, shared, claim_event, claim_names):
            continue
        diff = ", ".join(sorted({v["raw"] for v in cf}))
        _rec(claim,
             subject=("pass", {"t": "subj_ok"}),
             figure=("fail", {"t": "fig_fail_diff", "a": claim["raw"],
                              "b": diff}),
             event=("pass", _event_detail(
                 claim_event, tp.event_of(tp.normalize(raw)))),
             unit=(("pass", {"t": "unit_ok", "cur": claim["currency"]})
                   if claim["type"] == "amount" else None),
             origin=("web" if precision != "line" else "corpus"))
        return ("contradicted", "medium",
                [_evidence(fname, lineno, raw, precision=precision, corpus=corpus)],
                f"Corpus states {diff} here, document says {claim['raw']}.")
    # PASSAGE FALLBACK: a fact split across lines (or a book paragraph that
    # wraps mid-sentence) is still one fact. Support only: a passage may add a
    # `supported`, never a `contradicted`, so this cannot lower precision.
    if getattr(corpus, "passages", None):
        base = []
        if claim.get("value") is not None:
            base = corpus.find_value_passages(
                kws, claim["type"], claim["value"], claim.get("currency"),
                top=8)
        if not base:
            base = corpus.find_bm25_passages(
                claim.get("_query") or claim.get("sentence"), top=8)
        if not base:
            base = corpus.find_passages(kws, min_shared=2, top=8)
        cand_p, seen = [], set()
        for p in base[:4] + corpus.expand_passages(base[:2], radius=1):
            if p["idx"] not in seen:
                seen.add(p["idx"])
                cand_p.append(p)

        def _score(p):
            text = p["text"]
            score = len(set(kws) & p["tokens"])
            if any(n in tp.normalize(text) for n in claim_names):
                score += 3
            if claim.get("value") is not None:
                score += 3 * any(
                    v["kind"] == claim["type"]
                    and webmod.num_matches(claim, v, mod)
                    for v in _line_values(text))
            return score

        cand_p.sort(key=_score, reverse=True)
        for p in cand_p:
            text = p["text"]
            shared_p = set(kws) & p["tokens"]
            vals_p = _line_values(text)
            same_p = [v for v in vals_p
                      if v["kind"] == claim["type"]
                      and (claim["type"] != "amount"
                           or tp.currency_compatible(claim["currency"],
                                                     v["currency"]))]
            mv_p = [v for v in same_p if webmod.num_matches(claim, v, mod)]
            subj = text
            if strict_subject:
                # The value's own sentence, not the whole window: a passage
                # can hold two subjects (Caelum Cloud on one line, Caelum Labs
                # on the next), and a name anywhere in the window must not
                # green-light the other subject's figure.
                subj = _value_sentence(text, mv_p[0]["raw"] if mv_p else "")
                if not _names_present(claim, subj,
                                      claim.get("_doc_entities") or ()):
                    prev = _previous_sentence(text, subj)
                    if not (_anaphoric(subj) and prev
                            and _names_present(
                                claim, prev,
                                claim.get("_doc_entities") or ())):
                        continue
            if (len(shared_p) >= 2 and mv_p
                    and _predicate_ok(claim, subj, shared_p,
                                      claim_event, claim_names)):
                quote = _passage_quote(text, [v["raw"] for v in mv_p])
                _rec(claim,
                     subject=("pass", {"t": "subj_ok_n", "n": len(shared_p)}),
                     figure=("pass", {"t": "fig_ok", "v": mv_p[0]["raw"]}),
                     event=("pass", _event_detail(
                         claim_event, tp.event_of(tp.normalize(text)))),
                     origin="corpus")
                return "supported", "medium", [
                    _evidence(p["fname"], p["start"], quote,
                              precision="passage", corpus=corpus)], ""
    if off_event:
        # honest, actionable reason: the figure IS in the corpus, but on a line
        # about a different milestone. "value not confirmed" would hide that.
        fname, lineno, raw = off_event[0]
        _rec(claim,
             subject=("pass", {"t": "subj_ok"}),
             figure=("pass", {"t": "fig_ok_appear", "v": claim["raw"]}),
             event=("fail", _event_detail(
                 claim_event, tp.event_of(tp.normalize(raw)))),
             origin="corpus")
        return "unverified", "low", [], (
            f"Corpus mentions {claim['raw']} at {fname}:{lineno}, but that "
            f"line is about a different event — not a confirmation of this claim.")
    # LEXICAL-ONLY FALLBACK (see app/jev.py for the full safety argument).
    # Runs ONLY here, i.e. once every deterministic path has already declined,
    # so it is monotone: it can add a `supported`, never alter one. A line
    # qualifies ONLY if the figure and the predicate already agreed and the
    # lexical subject bar was the sole obstacle — the one thing a lexical bar
    # is bad at is the cross-script or paraphrased subject, which is exactly
    # what the model is better at. Off-event lines never reach here: they were
    # captured above with a specific reason, and `_subject_fallback` re-checks
    # the predicate anyway.
    jv = _subject_fallback(claim, corpus, ctx, mod, same_kind_ok=lambda vs: any(
        webmod.num_matches(claim, v, mod) for v in vs), predicate_ok=lambda r, s:
        _predicate_ok(claim, r, s, claim_event, claim_names))
    if jv:
        fname, lineno, raw, score, precision = jv
        _rec(claim,
             subject=("pass", {"t": "subj_ok_model"}),
             figure=("pass", {"t": "fig_ok_plain"}),
             event=("pass", {"t": "evt_ok_plain"}),
             origin=("web" if precision != "line" else "corpus"),
             assisted=True)
        return ("supported", "medium",
                [_evidence(fname, lineno, raw, note=(
                    f"subject match confirmed by model ({score:.2f}); figure "
                    "and event matched deterministically"), precision=precision,
                    corpus=corpus)],
                "")
    if ctx:
        _rec(claim,
             subject=("pass", {"t": "subj_ok"}),
             figure=("fail", {"t": "fig_fail_absent"}),
             event=("pass", {"t": "event_same", "what": claim_event}
                    if claim_event else {"t": "event_na"}),
             origin="corpus")
        return "unverified", "low", [], \
            "Subject found in corpus but value not confirmed."
    _rec(claim, subject=("fail", {"t": "subj_fail"}), origin="corpus")
    return "unverified", "low", [], "No corpus line about this subject."


def _subject_fallback(claim, corpus, ctx, mod, same_kind_ok, predicate_ok):
    """Ask the model to stand in for the lexical subject bar, and only that.

    Returns the winning (fname, lineno, raw, score, precision) or None. It
    re-derives the two deterministic conditions rather than trusting the
    caller's, so this function cannot be reached into to bypass them: the
    figure must match, the predicate must agree, and the model must clear
    SUBJECT_T. Anything short of all three returns None.

    The qualifying lines are asked concurrently and capped, so the worst case
    is one round trip rather than one per candidate.
    """
    if not ctx or not jev.available():
        return None
    qualified = []
    for fname, lineno, raw, same_kind, _strong, precision, shared in ctx:
        if not same_kind or not same_kind_ok(same_kind):
            continue
        if not predicate_ok(raw, shared):
            continue
        # PRECONDITION: the line must actually NAME the claim's subject.
        # Measured (tests/test_jev_entity_risk.py): where the line names a
        # different organisation the model answers 0.03, and where it names
        # the right one 0.99 — a wide, reliable margin. But on ANAPHORIC
        # evidence ("The company was founded in 2011") it has nothing to
        # contradict and answers 0.85-0.93, which clears the threshold while
        # carrying no information at all. Asking it to confirm an entity the
        # evidence never mentions is asking it to guess, so we don't ask —
        # and that test is deterministic, not a matter of trust.
        if not tp.shares_subject(claim["sentence"], raw):
            continue
        qualified.append((fname, lineno, raw, precision))
        if len(qualified) >= jev.MAX_LINES:
            break
    if not qualified:
        return None
    if len(qualified) == 1:
        scores = [jev.same_subject(claim["sentence"], qualified[0][2])]
    else:
        with ThreadPoolExecutor(max_workers=len(qualified)) as ex:
            scores = list(ex.map(
                lambda q: jev.same_subject(claim["sentence"], q[2]), qualified))
    best = None
    for (fname, lineno, raw, precision), score in zip(qualified, scores):
        if score is None or score < jev.SUBJECT_T:
            continue
        if best is None or score > best[3]:
            best = (fname, lineno, raw, score, precision)
    return best


def _check_quote(claim, corpus):
    if not corpus.lines:
        return "unverified", "low", [], "No corpus provided."
    ratio, fname, lineno, raw, precision = corpus.best_quote_match(claim["raw"])
    ev = [_evidence(fname, lineno, raw, precision=precision, corpus=corpus)] if fname else []
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
