"""EN<->ZH dual-version diff (generalizes the KS compare workflow).

v1 semantics are deliberately conservative: global FACT SETS per version
(values, alias-canonicalized names, URLs) compared set-wise.
- fact in A but not B          -> drift (dropped/altered in translation)
- same-kind near-miss values   -> reported once as a suspected drift pair
- names via alias map          -> 陳艾達 vs 'Ada Chen' = SAME fact, not drift
Quote TEXT is intentionally not compared (translation legitimately rewrites it).
"""
from . import textproc as tp


def _canon_names(text, alias):
    tn = tp.normalize(text)
    found = set()
    covered = []
    if alias:
        for gi, (forms, _toks) in enumerate(alias.groups):
            hits = [tp.normalize(f) for f in forms if tp.normalize(f) in tn]
            if hits:
                found.add(f"#{gi}")
            covered.extend(hits)
    for e in tp.detect_entities([text]):
        en = tp.normalize(e)
        if any(en in c or c in en for c in covered):
            continue
        found.add(en)
    for m in tp._SPEAK_ZH.finditer(text):
        nm = tp.normalize(m.group(1))
        if not any(nm in c or c in nm for c in covered):
            found.add(nm)
    return found


def fingerprint(text, alias):
    ev = tp.extract_values(text)
    return {
        "vals": {(v["kind"], round(v["value"], 4)) for v in ev},
        "urls": set(tp.URL_RE.findall(text)),
        "quotes": len(tp.QUOTE_RE.findall(text)),
        "names": _canon_names(text, alias),
    }


def _fmt(kind, x):
    if kind == "amount":
        return f"{x:,.0f}"
    if kind == "pct":
        return f"{x:g}%"
    return f"{x:g}"


def _near(kind, x, y):
    if kind == "year":
        return 0 < abs(x - y) <= 2
    if kind in ("amount", "count", "pct") and x and y:
        return 1 < max(x, y) / min(x, y) <= 1.35
    return False


def _first(idxs):
    return idxs[0] + 1 if idxs else None


def compare(doc_a, doc_b, alias=None, name_a="A", name_b="B"):
    fa = [fingerprint(p, alias) for p in doc_a["paragraphs"]]
    fb = [fingerprint(p, alias) for p in doc_b["paragraphs"]]

    def union(fs, key):
        s = set()
        for f in fs:
            s |= f[key]
        return s

    def idx_of(fs, item, key):
        return [i for i, f in enumerate(fs) if item in f[key]]

    findings = []

    def add(detail):
        findings.append({
            "id": f"v{len(findings) + 1:03d}", "type": "version_drift",
            "verdict": "needs_fix", "raw": detail, "confidence": "medium",
            "para": None, "span": [0, 0], "evidence": [],
            "sentence": detail, "note": detail, "suggestion": detail,
        })

    va, vb = union(fa, "vals"), union(fb, "vals")
    paired_a, paired_b = set(), set()
    # near-pair only values that are NOT exactly shared, and only in the
    # symmetric difference (else 2021/2023 — both present in each version —
    # would spuriously "drift").
    only_a = va - vb
    only_b = vb - va
    for (k, x) in sorted(only_a):
        ia = idx_of(fa, (k, x), "vals")
        for (kk, y) in sorted(only_b):
            if kk == k and (k, y) not in paired_b and _near(k, x, y):
                ib = idx_of(fb, (k, y), "vals")
                paired_a.add((k, x))
                paired_b.add((k, y))
                add(f"{k} differs: {name_a} ¶{_first(ia)}={_fmt(k, x)} vs "
                    f"{name_b} ¶{_first(ib)}={_fmt(k, y)}")
    for (k, x) in sorted(only_a - paired_a):
        add(f"{k} {_fmt(k, x)} only in {name_a} (¶{_first(idx_of(fa, (k, x), 'vals'))})")
    for (k, y) in sorted(only_b - paired_b):
        add(f"{k} {_fmt(k, y)} only in {name_b} (¶{_first(idx_of(fb, (k, y), 'vals'))})")

    # names: only ALIAS-CANONICALIZED (#gi) subjects are comparable across
    # scripts; raw detected entities would produce false drift (Hangzhou!=杭州
    # unless mapped), so they are excluded from the cross-version name check.
    na = {x for x in union(fa, "names") if x.startswith("#")}
    nb = {y for y in union(fb, "names") if y.startswith("#")}
    for x in sorted(na - nb):
        add(f"mapped subject {x} only in {name_a} (¶{_first(idx_of(fa, x, 'names'))})")
    for y in sorted(nb - na):
        add(f"mapped subject {y} only in {name_b} (¶{_first(idx_of(fb, y, 'names'))})")

    ua, ub = union(fa, "urls"), union(fb, "urls")
    for u in sorted(ua - ub):
        add(f"URL only in {name_a}: {u}")
    for u in sorted(ub - ua):
        add(f"URL only in {name_b}: {u}")

    return findings, {"a_paras": len(fa), "b_paras": len(fb), "findings": len(findings)}
