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


def _eligible(claim):
    return (claim.get("verdict") == "unverified"
            and claim.get("type") in PROSE_TYPES
            and not claim.get("_dup_of")
            and not claim.get("fx_secondary")
            and not (claim.get("citation") and claim.get("type") != "url")
            and not str(claim.get("_skip_reason") or "").startswith("citation"))


def _local_evidence(claim, corpus, k=MAX_LOCAL):
    out = []
    ctx = _ctx(claim)
    if corpus is not None and ctx:
        for p in (corpus.find_prose_candidates(ctx, top=k) or []):
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


def _prompt(items):
    return (
        "You are a conservative fact-checker. For each CLAIM, decide whether "
        "its own EVIDENCE contains a passage that entails the claim. SUPPORT "
        "ONLY: return a claim only when the evidence directly establishes it. "
        "If the evidence is merely topically related, omit the claim. Never "
        "use outside knowledge. Never report a contradiction; omit instead.\n"
        "Rules: (1) evidence about a DIFFERENT organisation that merely shares "
        "part of the name (subsidiary, spin-off, lookalike) settles nothing; "
        "(2) a later outcome does not contradict an earlier intention, refusal "
        "or state; (3) the quote MUST be a verbatim substring of that claim's "
        "evidence text, in its own language. Return ONLY a JSON array of "
        '{"id":"<claim id>","ev":<evidence number>,"verdict":"supported",'
        '"quote":"<verbatim proof>","note":"<one short sentence>"}.\n\n'
        "CLAIMS:\n" + json.dumps(items, ensure_ascii=False) + "\n\nJSON:")


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
            _apply(c, evs[i - 1], quote, str(d.get("note") or "")[:160])
            rescued += 1
    if rescued:
        _p({"stage": "semantic_done", "rescued": rescued,
            "item": f"{rescued} prose claims supported by a full-sentence semantic match"})
    return rescued
