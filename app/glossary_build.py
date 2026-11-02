"""Glossary builder: harvest names, let a model propose, let the corpus decide.

The model never invents a row that ships: every pair goes through
`glossary.verify_pair`, which requires the source-language form to occur in the
corpus. Without a key the builder still runs from deterministic
short/full-form pairs and in-text glosses.
"""
import json
import logging
import re

from .glossary import Glossary, norm, same_entity, verify_pair

log = logging.getLogger("checkmato.glossary_builder")

LAT = re.compile(r"\b[A-Z][A-Za-z]{1,20}(?:\s+[A-Z][A-Za-z]{1,20}){0,3}\b")
GLOSS_LAT_CJK = re.compile(
    r"([A-Za-z][A-Za-z0-9 .&'\-]{1,40})[（(]([\u4e00-\u9fff]{2,12})[）)]")
GLOSS_CJK_LAT = re.compile(
    r"([\u4e00-\u9fff]{2,12})[（(]([A-Za-z][^）)\n]{1,40})[）)]")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,10}")
CORP_CJK = ("公司", "集團", "集团", "軟件", "软件", "科技", "控股", "銀行", "银行")
CORP_LAT = ("Corp", "Corporation", "Inc", "Ltd", "Group", "Software",
            "Technology", "Cloud", "Holdings")


def _cjk(s):
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def harvest(text):
    """Return {'glossed': [(a,b)], 'lat': [...], 'cjk': [...]} — no model."""
    from collections import Counter
    glossed = []
    for m in GLOSS_LAT_CJK.finditer(text):
        glossed.append((m.group(1).strip(), m.group(2).strip()))
    for m in GLOSS_CJK_LAT.finditer(text):
        glossed.append((m.group(2).strip(), m.group(1).strip()))
    lat = sorted({m.group(0).strip() for m in LAT.finditer(text)},
                 key=len, reverse=True)
    runs = [m.group(0) for m in CJK_RUN.finditer(text)]
    counts = Counter(runs)
    cjk = {s for s, n in counts.items() if n >= 2 and len(s) >= 2}
    # names ending in an org suffix, recovered from inside longer runs
    for run in runs:
        for suf in CORP_CJK:
            i = run.find(suf)
            if i < 1:
                continue
            end = i + len(suf)
            for length in (2, 3, 4):
                if end - length >= 0:
                    cjk.add(run[end - length:end])
    # repeated prefixes catch personal names that start several sentences
    prefixes = Counter()
    for run in runs:
        for length in (2, 3, 4):
            if len(run) >= length:
                prefixes[run[:length]] += 1
    cjk |= {p for p, n in prefixes.items() if n >= 2}
    cjk = sorted({s for s in cjk if len(s) >= 2}, key=len, reverse=True)[:200]
    return {"glossed": glossed, "lat": lat, "cjk": cjk}


def _variants(lat, cjk):
    """Short/full pairs the author actually uses (Example / Example Software)."""
    out = []
    lat_set = set(lat)
    for a in lat:
        for suf in CORP_LAT:
            if a.endswith(" " + suf):
                short = a[: -len(suf) - 1]
                if short in lat_set:
                    out.append((short, a, "org"))
    cjk_set = set(cjk)
    for a in cjk:
        for suf in CORP_CJK:
            if a.endswith(suf) and len(a) > len(suf):
                short = a[: -len(suf)]
                if short in cjk_set:
                    out.append((short, a, "org"))
    return out


def _prompt(h):
    lat = h["lat"][:80]
    cjk = h["cjk"][:80]
    return (
        "You map names between English and Chinese for a document library.\n"
        "Return JSON only, no prose, in this shape:\n"
        '{"pairs":[{"a":"...","b":"...","kind":"person|org|term",'
        '"scope":"same|parent|subsidiary|product","why":"..."}]}\n'
        "Use ONLY names from the two lists below. If you are unsure, omit the "
        "pair. Never invent Chinese characters.\n"
        f"English names: {json.dumps(lat, ensure_ascii=False)}\n"
        f"Chinese names: {json.dumps(cjk, ensure_ascii=False)}\n"
        "Known glosses already in the text: "
        f"{json.dumps(h['glossed'][:40], ensure_ascii=False)}\n")


def propose(llm, h):
    """Ask the model for pairs; return only well-formed ones from the lists."""
    if not llm or not llm.available:
        return []
    out = llm.chat(_prompt(h))
    if not out:
        return []
    try:
        blob = out[out.find("{"): out.rfind("}") + 1]
        data = json.loads(blob)
    except (ValueError, TypeError):
        log.warning("glossary model returned non-JSON; ignored")
        return []
    lat = {norm(x) for x in h["lat"]}
    cjk = {norm(x) for x in h["cjk"]}
    pairs = []
    for p in data.get("pairs") or []:
        a, b = str(p.get("a") or "").strip(), str(p.get("b") or "").strip()
        if not a or not b:
            continue
        if not ((norm(a) in lat and norm(b) in cjk)
                or (norm(b) in lat and norm(a) in cjk)):
            continue  # a pair not grounded in the harvested names
        pairs.append({"a": a, "b": b, "kind": p.get("kind") or "term",
                      "scope": p.get("scope") or "same"})
    return pairs


def build(draft_text, corpus_text, llm=None, use_llm=False):
    """Harvest → (optionally) propose → verify. Returns (Glossary, stats)."""
    h = harvest(draft_text + "\n" + corpus_text)
    rows = []
    for a, b, kind in _variants(h["lat"], h["cjk"]):
        row = verify_pair(a, b, _lang_pair(a, b), corpus_text, draft_text)
        row.update(kind=kind, origin="doc")
        rows.append(row)
    for a, b in h["glossed"]:
        row = verify_pair(a, b, _lang_pair(a, b), corpus_text, draft_text)
        row.update(kind="org", origin="doc")
        rows.append(row)
    if use_llm:
        for p in propose(llm, h):
            row = verify_pair(p["a"], p["b"], _lang_pair(p["a"], p["b"]),
                              corpus_text, draft_text, scope=p["scope"])
            row.update(kind=p["kind"], origin="llm")
            rows.append(row)
    g = Glossary()
    for r in rows:
        g.add(r)
    states = {}
    for r in g.rows:
        states[r.get("state", "")] = states.get(r.get("state", ""), 0) + 1
    return g, {"candidates": len(rows), "states": states,
               "llm_used": bool(use_llm and llm and llm.available)}


def _lang_pair(a, b):
    if _cjk(a) and _cjk(b):
        return "zh-zh"
    if not _cjk(a) and not _cjk(b):
        return "en-en"
    return "zh-en"


def same_subject(a, b, glossary=None):
    """Subject check that may use verified pairs from a built glossary."""
    pairs = glossary.verified_pairs() if glossary else ()
    from .glossary import is_same_subject
    return is_same_subject(a, b, pairs)


__all__ = ["harvest", "propose", "build", "same_subject", "same_entity"]
