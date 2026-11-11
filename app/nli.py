"""W1.4 — optional semantic judge for prose. Support-only by contract.

Why this module exists: a prose sentence has no figure or quote for the
deterministic judge, so it stays `unverified` even when a source passage states
it in different words. W1.1 retrieval already finds the nearest passages; this
step asks the existing LLM provider whether one of them actually entails the
full sentence.

Quality contract (do not relax):
- Only PROSE claims are touched (event/name/timeline/sentence). Numbers and
  quotes keep their deterministic checkers.
- The model may produce `supported` only. `contradicted` and `conflicting` are
  never taken from a model; only deterministic guards may flag those.
- A support must quote a verbatim span of the evidence, checked here before any
  verdict is set. A paraphrase or invented quote is rejected.
- Confidence is capped at `medium`: the reader still has to open the source.
- Base install stays unchanged: this module is imported only when `--semantic`
  is on, and it uses the existing LLM chain (no new dependency).

The local MiniCheck/Erlangshen NLI backend from IMPROVEMENT_PLAN §W1 can replace
`judge()` later without changing the contract or the call sites.
"""
import json
import re

from . import textproc as tp

PROSE_TYPES = ("event", "name", "timeline", "sentence")
MAX_CLAIMS = 24          # per run: bound the extra LLM cost
BATCH = 8                # claims per call
MAX_LOCAL = 3            # BYOS passages per claim
MAX_WEB = 2              # web snippets per claim
TEXT_CAP = 700           # chars per evidence passage in the prompt


def _ctx(claim):
    return (claim.get("sentence_context")
            or claim.get("context_sentence")
            or claim.get("sentence")
            or "")


_TABLE_CELL_NUM = re.compile(
    r"^[\s¥￥$€£]*[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|％|万|亿|元|美元)?$")


def _is_table_row(claim):
    """A markdown table/financial row is structure, not a checkable sentence.

    The extractor keeps a row as one "sentence", so without this guard a row
    such as `revenue | 1,234 | 5,678` can be "supported" by any passage that
    happens to share a label. Two or more numeric cells mean there is no
    predicate to entail; skip it.
    """
    text = str(_ctx(claim) or "")
    if text.count("|") < 2:
        return False
    cells = [c.strip() for c in text.split("|")]
    if len(cells) < 3:
        return False
    numeric = sum(1 for c in cells if _TABLE_CELL_NUM.match(c))
    return numeric >= 2


def _eligible(claim):
    return (claim.get("verdict") == "unverified"
            and claim.get("type") in PROSE_TYPES
            and not _is_table_row(claim)
            and not claim.get("_dup_of")
            and not claim.get("fx_secondary")
            and not (claim.get("citation") and claim.get("type") != "url")
            and not str(claim.get("_skip_reason") or "").startswith("citation"))


def _pick_local(cands, k):
    """Keep rank order, but never let the semantic lane evict all lexical proof.

    When semantic retrieval is on, its top hits can outscore an exact passage
    that lexical retrieval already found. The NLI prompt only receives k
    passages, so losing that exact hit is a quality loss. Reserve at least one
    slot for a pure-lexical candidate and one for a semantic candidate when
    both lanes are present; when semantic is off every candidate is lexical
    and this is a plain top-k.
    """
    picked, seen = [], set()

    def add(p, replace_tail=False):
        key = (p.get("fname"), p.get("start"))
        if key in seen:
            return
        seen.add(key)
        if replace_tail and len(picked) >= k:
            picked[k - 1] = p
        else:
            picked.append(p)

    def lanes(p):
        why = p.get("why") or {}
        raw = why.get("lanes")
        if raw:
            return set(raw)
        # Older/fake callers may only expose the semantic score.
        return {"semantic"} if why.get("semantic", 0) > 0 else {"lexical"}

    def has_sem(p):
        return "semantic" in lanes(p)

    def has_lex(p):
        return any(lane != "semantic" for lane in lanes(p))

    for p in cands[:k]:
        add(p)
    if any(has_sem(p) for p in cands) and not any(has_sem(p) for p in picked):
        for p in cands:
            if has_sem(p):
                add(p, replace_tail=True)
                break
    elif any(has_lex(p) for p in cands) and not any(has_lex(p) for p in picked):
        for p in cands:
            if has_lex(p):
                add(p, replace_tail=True)
                break
    return picked[:k]


def _local_evidence(claim, corpus, k=MAX_LOCAL):
    out = []
    ctx = _ctx(claim)
    if corpus is not None and ctx:
        cands = corpus.find_prose_candidates(ctx, top=max(k * 3, 9)) or []
        for p in _pick_local(cands, k):
            text = (p.get("text") or "").strip()
            if not text:
                continue
            out.append({"kind": "local",
                        "ref": f"{p.get('fname')}:{p.get('start')}",
                        "text": text})
    if not out:
        # BYOS already computed these leads; use them when the corpus object is
        # unavailable (e.g. a direct caller) instead of silently losing them.
        for lead in (claim.get("lead_candidates") or [])[:k]:
            text = (lead.get("text") or "").strip()
            if text:
                out.append({"kind": "local",
                            "ref": f"{lead.get('fname')}:{lead.get('start')}",
                            "text": text})
    return out


def _web_evidence(claim, web, k=MAX_WEB):
    if web is None or not getattr(web, "_pool", None):
        return []
    ctx = _ctx(claim)
    rare = {tp.normalize(t) for t in tp.rare_raw_tokens(ctx) if len(t) > 2}
    if not rare:
        return []
    scored, seen = [], set()
    for r in list(web._pool):
        href = r.get("href") or ""
        body = ((r.get("body") or "") + " " + (r.get("title") or "")).strip()
        if not body or (href and href in seen):
            continue
        if not web._mentions_entity(body):
            continue
        nb = tp.normalize(body)
        hits = sum(1 for t in rare if t in nb)
        if hits:
            seen.add(href)
            scored.append((hits, href, body))
    scored.sort(key=lambda x: -x[0])
    return [{"kind": "web", "ref": href or "web", "text": body}
            for _h, href, body in scored[:k]]


def _evidence_for(claim, corpus, web):
    ev = _local_evidence(claim, corpus) + _web_evidence(claim, web)
    return ev[:MAX_LOCAL + MAX_WEB]


_LIST_TRIGGER = re.compile(r"(?:包括|包含|分为|如下|：|:|——|—)(.*)$")
_LIST_SPLIT = re.compile(r"[、，,；;]\s*")


def _list_items(text):
    """Elements of an explicit list ('包括 A、B、C') — the unit of a partial
    support check. Returns [] when the sentence has no list trigger."""
    m = _LIST_TRIGGER.search(text or "")
    if not m:
        return []
    out = []
    for part in _LIST_SPLIT.split(m.group(1)):
        part = part.strip(" 。.!?？；;：:、\"'“”‘’「」")
        if 2 <= len(part) <= 16 and not re.fullmatch(r"[\d.%]+", part):
            out.append(part)
    return list(dict.fromkeys(out))


def _list_gap(claim, evidence_text):
    """List elements missing from this evidence text (0..total).

    Includes 0-1 found: evidence may share the topic while naming none of the
    listed elements. That is not partial support and must never become a green.
    """
    items = _list_items(_ctx(claim))
    if len(items) < 3:
        return None
    text = tp.normalize(evidence_text)
    found = [x for x in items if tp.normalize(x) in text]
    if len(found) >= len(items):
        return None
    return {"found": len(found), "total": len(items),
            "missing": [x for x in items if x not in found]}


def _partial_note(claim, evidence_text):
    """Most elements present, not all: a partial, not a green.

    Example: the claim lists 4 products and the source names 3. The contract
    stays supported/unverified (user decision A); the note says exactly which
    element is missing, so the reader never sees a false green.
    """
    note = _list_gap(claim, evidence_text)
    if note and note["found"] >= 2:
        return note
    return None


_CJK_ORG = re.compile(
    r"[\u4e00-\u9fff]{2,6}(?:科技|公司|集团|企业|银行|大学|学院|"
    r"研究院|资本|基金|控股|实业|网络|软件|云|健康|医疗|证券|保险|"
    r"汽车|能源|传媒)")


def _claim_entities(claim):
    text = _ctx(claim)
    ents = set(tp.detect_entities([text]) + tp.detect_cjk_entities([text]))
    # detect_cjk_entities only accepts repeated/quoted names; a one-off
    # '华光科技与恒宇科技' still names two subjects, so scan suffix-anchored
    # organisations directly.
    ents |= set(_CJK_ORG.findall(text))
    return sorted({e for e in ents if len(e) >= 3}, key=len, reverse=True)


def _multi_entity_note(claim, evidence_text):
    """Evidence names one subject, the sentence names two: not a support.

    'Alpha and Beta opened an office' cannot be settled by an Alpha-only page.
    """
    ents = _claim_entities(claim)
    if len(ents) < 2:
        return None
    text = tp.normalize(evidence_text)
    present = [e for e in ents if tp.normalize(e) in text]
    missing = [e for e in ents if e not in present]
    if present and missing:
        return {"present": present, "missing": missing}
    return None


def _heading_quote(claim, evidence_text, quote):
    """The matched wording sits on a heading/title line, not attributed
    speech. A section title is not a quote even when it is verbatim."""
    text = str(evidence_text or "")
    nq = tp.normalize(quote or "")[:80]
    for line in text.splitlines():
        if nq and nq in tp.normalize(line):
            return line.lstrip().startswith("#")
    return text.lstrip().startswith("#") and bool(
        _ATTRIB.search(str(claim.get("sentence") or "")))


_ATTRIB = re.compile(
    r"(?i)\b(?:said|says|stated|wrote|recalled|noted|declared)\b|"
    r"强调|表示|写道|指出|说：")


def _mark_partial(claim, note):
    claim["verdict"] = "unverified"
    claim["confidence"] = "low"
    claim["_partial"] = note
    claim["suggestion"] = (
        f"Partial support: {note['found']}/{note['total']} elements found; "
        f"missing: {', '.join(note['missing'])}. Not counted as supported.")


def _mark_list_gap(claim, note):
    """Evidence names almost none of the list: reject the support outright."""
    claim["verdict"] = "unverified"
    claim["confidence"] = "low"
    claim["_partial"] = note
    claim["suggestion"] = (
        f"Evidence covers only {note['found']}/{note['total']} listed "
        f"elements; missing: {', '.join(note['missing'])}. "
        "Not counted as supported.")


def _prompt(items):
    blocks = []
    for it in items:
        lines = "\n".join(f"- {e['text']}" for e in it["evidence"])
        blocks.append(
            f"CLAIM {it['id']}: {it['claim']}\n"
            f"EVIDENCE for claim {it['id']} (use ONLY this block):\n"
            f"{lines}\n")
    return (
        "You are a conservative fact-checker. For each numbered CLAIM below, "
        "decide whether its OWN evidence block supports it. Use ONLY the "
        "evidence in that claim's block; never borrow another claim's "
        "evidence. The wording may differ: accept synonyms, paraphrase and "
        "pronouns that refer to the claim's subject. Support means the evidence "
        "states the SAME event or relationship with the same entities and "
        "values. If the evidence is only topically related, or states a "
        "different event, value, place, role, time or organisation, omit the "
        "claim. Never use outside knowledge. Never report a contradiction; "
        "omit instead. The quote MUST be a verbatim substring of that claim's "
        "own evidence. Prefer the highest-ranked evidence item that actually "
        "supports the claim; use a lower item only when it is the direct proof. "
        "Return ONLY a JSON array of "
        '{"id":"<claim id>","ev":<evidence number in that claim\'s block>,'
        '"verdict":"supported","quote":"<verbatim proof>",'
        '"note":"<one short sentence>"}.\n\n'
        + "\n".join(blocks) + "JSON:")


def _parse(raw):
    if not raw:
        return []
    i, j = raw.find("["), raw.rfind("]")
    if i < 0 or j <= i:
        return []
    try:
        arr = json.loads(raw[i:j + 1])
    except json.JSONDecodeError:
        return []
    return arr if isinstance(arr, list) else []


def _apply(claim, ev, quote, note):
    claim["verdict"] = "supported"
    claim["confidence"] = "medium"      # never high: a model read the passage
    claim["evidence"] = (claim.get("evidence") or []) + [{
        "kind": ev["kind"],
        "ref": ev["ref"],
        "quote": (quote or ev["text"])[:320],
        "precision": "passage" if ev["kind"] == "local" else "snippet",
        "note": "semantic judge (LLM) on the full sentence — open source to confirm",
    }]
    claim["suggestion"] = ((note or "")
                           + " Semantic match on the full sentence; the source "
                             "is attached — open it to confirm.")
    claim["_semantic"] = True


def judge(llm, claims, corpus=None, web=None, progress=None,
          batch=BATCH, max_claims=MAX_CLAIMS):
    """Rescue prose claims that a passage entails. Returns the number upgraded.

    Only `supported` is possible here. A claim that is not directly entailed
    stays exactly as it was (`unverified`), so the mode can never manufacture a
    red flag or a green from a topical resemblance.
    """
    if not (llm and llm.available):
        return 0
    _p = progress or (lambda e: None)
    # Collect evidence first, then cap: a document whose first prose claims have
    # no passage must not hide later claims that do. The cap bounds LLM cost,
    # not local retrieval.
    todo = []
    for c in claims:
        if not _eligible(c):
            continue
        ev = _evidence_for(c, corpus, web)
        if ev:
            todo.append((c, ev))
            if len(todo) >= max_claims:
                break
    if not todo:
        return 0

    by_id = {c["id"]: c for c, _ev in todo}
    partial_by_id, multi_by_id = {}, {}
    for c, ev in todo:
        evidence_text = " ".join(e["text"] for e in ev)
        pn = _partial_note(c, evidence_text)
        if pn:
            partial_by_id[c["id"]] = pn
        mn = _multi_entity_note(c, evidence_text)
        if mn:
            multi_by_id[c["id"]] = mn
    rescued = 0
    for start in range(0, len(todo), batch):
        if llm.exhausted:
            break
        items, ev_by_id = [], {}
        for c, ev in todo[start:start + batch]:
            ev_by_id[c["id"]] = ev
            items.append({
                "id": c["id"],
                "claim": _ctx(c)[:300],
                "evidence": [{"i": i + 1, "text": e["text"][:TEXT_CAP]}
                             for i, e in enumerate(ev)],
            })
        if not items:
            continue
        _p({"stage": "semantic", "claims": len(items),
            "item": f"judging {len(items)} prose claims against retrieved passages"})
        for d in _parse(llm.chat(_prompt(items))):
            try:
                cid = str(d["id"])
                i = int(d["ev"])
            except (KeyError, ValueError, TypeError):
                continue
            if cid not in by_id or cid not in ev_by_id:
                continue
            evs = ev_by_id[cid]
            if not 1 <= i <= len(evs):
                continue
            # Support-only: a model contradiction/conflict is ignored, never
            # promoted. Only the deterministic guards may flag those.
            if d.get("verdict") not in (None, "supported"):
                continue
            quote = str(d.get("quote") or "")
            nq, nt = tp.normalize(quote), tp.normalize(evs[i - 1]["text"])
            if not nq or nq[:120] not in nt:
                continue  # invented/paraphrased proof -> no verdict
            c = by_id[cid]
            if c["verdict"] != "unverified":
                continue
            # The reader sees the model's QUOTE, not the whole candidate
            # passage. A support is only complete if the quote itself carries
            # every listed element; otherwise it is a partial, never a green.
            quote_gap = _list_gap(c, quote)
            if quote_gap:
                if quote_gap["found"] >= 2:
                    _mark_partial(c, quote_gap)
                else:
                    _mark_list_gap(c, quote_gap)
                continue
            if _heading_quote(c, evs[i - 1]["text"], quote):
                c["suggestion"] = (
                    "The matched wording is a heading/title, not attributed "
                    "speech; not counted as a quote.")
                continue
            quote_multi = _multi_entity_note(c, quote)
            if quote_multi:
                c["_multi_entity"] = quote_multi
                c["suggestion"] = (
                    f"Evidence covers only {', '.join(quote_multi['present'])}; "
                    f"the sentence also names {', '.join(quote_multi['missing'])}. "
                    "Not counted as supported — split the sentence or find a "
                    "source covering both.")
                continue
            if multi_by_id.get(cid):
                note = multi_by_id[cid]
                c["_multi_entity"] = note
                c["suggestion"] = (
                    f"Evidence covers only {', '.join(note['present'])}; the "
                    f"sentence also names {', '.join(note['missing'])}. Not "
                    "counted as supported — split the sentence or find a "
                    "source covering both.")
                continue
            if partial_by_id.get(cid):
                _mark_partial(c, partial_by_id[cid])
                continue
            _apply(c, evs[i - 1], quote, str(d.get("note") or "")[:160])
            rescued += 1
    # Even when the model does not support, leave the reader the partial /
    # multi-subject diagnosis instead of a bare "unverified".
    for c, _ev in todo:
        if c["verdict"] != "unverified":
            continue
        if multi_by_id.get(c["id"]):
            note = multi_by_id[c["id"]]
            c["_multi_entity"] = note
            c["suggestion"] = (
                f"Evidence covers only {', '.join(note['present'])}; the "
                f"sentence also names {', '.join(note['missing'])}. Not "
                "counted as supported — split the sentence or find a source "
                "covering both.")
        elif partial_by_id.get(c["id"]):
            _mark_partial(c, partial_by_id[c["id"]])
    if rescued:
        _p({"stage": "semantic_done", "rescued": rescued,
            "item": f"{rescued} prose claims supported by a full-sentence semantic match"})
    return rescued
