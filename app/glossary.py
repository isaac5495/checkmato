"""Glossary: short/full forms, parent/subsidiary guards, cross-script pairs.

The model (if any) only PROPOSES pairs; this module decides. A pair is
`verified` only when the source-language string is found in the corpus and the
identity rule holds. Everything else widens retrieval and nothing more.

Identity is deliberately conservative: "Example Cloud" is NOT "Example". A
wrong alias costs a false green; a missed alias costs one failed search.
"""
import csv
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("checkmato.glossary")

LEGAL = ("股份有限公司", "有限公司", "公司", "corporation", "corp", "inc",
         "ltd", "company", "co", "holdings")
# descriptors that can be the same entity when the author uses both forms
SOFT = ("軟件", "软件", "software")
# descriptors that denote a DIFFERENT entity and must never merge
OTHER = ("雲", "云", "cloud", "集團", "集团", "group", "科技",
         "technology", "控股")

_cc = None


def _to_simplified(text):
    global _cc
    if _cc is None:
        try:
            from opencc import OpenCC
            _cc = OpenCC("t2s")
        except Exception as e:  # optional dependency: stay usable without it
            log.debug("opencc unavailable: %s", e)
            _cc = False
    if not _cc:
        return text
    try:
        return _cc.convert(text)
    except Exception:
        return text


def norm(text):
    """Comparison form: NFKC, traditional->simplified, no spaces/punctuation."""
    t = unicodedata.normalize("NFKC", str(text or "")).lower()
    t = _to_simplified(t)
    return re.sub(r"[\s\W_]+", "", t)


def strip_suffix(t):
    out = t
    changed = True
    while changed:
        changed = False
        for s in LEGAL + SOFT:
            ns = norm(s)
            if ns and out.endswith(ns) and len(out) > len(ns):
                out = out[: -len(ns)]
                changed = True
    return out


def same_entity(a, b, cooccur=False):
    """True only when the two forms name the SAME entity.

    Legal forms always collapse (Corp/Corporation/有限公司). Business
    descriptors need the author to use both forms (cooccur). Markers that
    denote a different entity (Cloud/Group/Technology) never collapse.
    """
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long = sorted((na, nb), key=len)
    if not long.startswith(short):
        return False
    extra = long[len(short):]
    if any(m in extra for m in OTHER):
        return False
    if extra in {norm(s) for s in LEGAL}:
        return True
    if extra in {norm(s) for s in SOFT}:
        return bool(cooccur)
    return False


def is_same_subject(a, b, pairs=()):
    """Subject check: verified pairs + the conservative identity rule only."""
    if same_entity(a, b, cooccur=False):
        return True
    for x, y in pairs:
        if {norm(x), norm(y)} == {norm(a), norm(b)}:
            return True
    return False


def _occ(needle, haystack):
    n = norm(needle)
    if not n:
        return 0
    return norm(haystack).count(n)


def verify_pair(a, b, lang_pair, corpus_text, draft_text, scope="same",
                cooccur=None):
    """Decide what a proposed pair is allowed to do.

    Returns a row with `state`:
      verified        identity proven; may anchor a subject
      retrieval_only  stored, widens search, never anchors
      proposed_unverified  no proof; retrieval candidates only
    """
    oa, ob = _occ(a, corpus_text), _occ(b, corpus_text)
    da, db = _occ(a, draft_text), _occ(b, draft_text)
    if cooccur is None:
        cooccur = bool(da and db) or bool(oa and ob)
    if lang_pair == "zh-en" or lang_pair == "en-zh":
        both = bool(oa or ob) and bool(da or db)
        state = "retrieval_only" if both else "proposed_unverified"
        return {"a": a, "b": b, "lang_pair": lang_pair, "scope": "retrieval",
                "state": state, "occ_a": oa, "occ_b": ob,
                "note": "cross-script aliases never anchor a verdict"}
    same = same_entity(a, b, cooccur=cooccur)
    known = bool(oa or ob)
    if same and known:
        state, sc = "verified", "same"
    elif known:
        state, sc = "retrieval_only", scope if scope in OTHER_SCOPES else "parent"
    else:
        state, sc = "proposed_unverified", scope
    return {"a": a, "b": b, "lang_pair": lang_pair, "scope": sc,
            "state": state, "occ_a": oa, "occ_b": ob, "note": ""}


OTHER_SCOPES = {"parent", "subsidiary", "product", "retrieval"}


class Glossary:
    """Editable CSV: a,b,lang_pair,kind,scope,origin,occ_a,occ_b,state,note."""

    COLS = ["a", "b", "lang_pair", "kind", "scope", "origin",
            "occ_a", "occ_b", "state", "note"]

    def __init__(self, rows=None):
        self.rows = list(rows or [])

    @classmethod
    def load(cls, path):
        p = Path(path)
        if not p.exists():
            return cls()
        with open(p, encoding="utf-8", newline="") as f:
            return cls([dict(r) for r in csv.DictReader(f)])

    def add(self, row):
        key = {norm(row["a"]), norm(row["b"])}
        for r in self.rows:
            if {norm(r["a"]), norm(r["b"])} == key:
                if r.get("origin") != "user":
                    r.update(row)
                return r
        row.setdefault("origin", "llm")
        self.rows.append(row)
        return row

    def save(self, path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.COLS, extrasaction="ignore")
            w.writeheader()
            for r in self.rows:
                w.writerow({k: r.get(k, "") for k in self.COLS})

    def verified_pairs(self):
        return [(r["a"], r["b"]) for r in self.rows
                if r.get("state") == "verified"]
