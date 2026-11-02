r"""Jev entity-identity risk + the BYOS subject fallback — network-gated, NOT in
run_all.py (same convention as test_blind_lego.py / test_jev_gate.py). Run:
    .venv\Scripts\python.exe -X utf8 tests\test_jev_entity_risk.py

WHY THIS FILE EXISTS
A false green in the corpus path needs THREE things to go wrong at once: the
figure must match, the milestone must match, and the line must be about a
DIFFERENT entity. The first two are deterministic and were hardened today.
The third is the only one a model now touches, so the third is what this
measures:

  PART 1  adversarial pairs where a false green WOULD be produced if the model
          were wrong about subject identity. Same event, same figure, wrong
          entity: two firms founded the same year, a lookalike product from a
          different vendor, a role-reversed adjacent fact, a cross-script
          wrong entity. GATE: false-green must be 0.
  PART 2  the fallback must actually recover the recall it was built for, and
          must not resurrect the off-event false greens from Part A.

Labels are about TEXT, not the world: every pair is a fixed string, and the
label is "does this evidence text assert this claim's figure/event about this
entity?" The evidence lines are constructed, not scraped.

NONDETERMINISM WARNING
Jev is a classifier. A serial-vs-serial noise floor of 0.090 was measured, so a
single run is evidence, not proof. The gate therefore asserts a SAFETY property
(false-green = 0) and a coarse recall floor, never an exact score. Re-run after
any model-version change (`GET /v1/models` reported jev-1.13.0 when written).
"""
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import judge  # noqa: E402
from app.corpus import Corpus  # noqa: E402
from app.names import AliasMap  # noqa: E402

API = "https://api.typesafe.ai/v1/systemone"

# (id, claim, evidence, label, evidence_names_an_entity) — the cases that need a
# wrong entity call. The 5th field is NOT cosmetic: the fallback only ever
# consults the model on lines that NAME the claim's subject, so only those rows
# carry a safety obligation. On anaphoric evidence the model has nothing to
# contradict and answers high regardless of the truth (0.85-0.93, measured over
# 10 reps with spread 0.004), which is a property of the MODEL, and is exactly
# why the name precondition exists. Asserting zero false greens on those rows
# would be asserting something untrue about the model; asserting they never
# reach a verdict is asserting something true about the pipeline.
PAIRS = [
    ("two_co", "Northwind Systems was founded in 2011.",
     "Solaris Grid was founded in 2011 by two engineers.", "not-support", True),
    ("two_co2", "Halcyon Labs was founded in 2011.",
     "Solaris Grid was founded in 2011 by two engineers.", "not-support", True),
    ("lookalike", "Kingsoft released WPS Office in 1989.",
     "Corvus Software released WPS Office in 1989.", "not-support", True),
    ("two_person", "Priya Raman founded Northwind in 2011.",
     "Marcus Feld founded Northwind in 2011.", "not-support", True),
    ("adjacent_wrong", "Corvus acquired Helio in 2016.",
     "Helio Dynamics was founded in 2011; Corvus was acquired in 2016.",
     "not-support", True),
    ("zh_wrong_entity", "联想集团成立于1988年。",
     "1988年，求伯君与另外三人共同创办金山软件公司。", "not-support", True),
    ("generic_wrong", "Northwind Systems was founded in 2011.",
     "The company was founded in 1994 in Oslo by two engineers.",
     "not-support", False),
    ("anaphoric_trap", "Northwind Systems was founded in 2011.",
     "The company was founded in 2011 in Oslo by two engineers.",
     "not-support", False),
    # genuine supports: the model must clear the threshold for these
    ("genuine_co", "Solaris Grid was founded in 2011.",
     "Solaris Grid was founded in 2011 by two engineers.", "support", True),
    ("genuine_person", "Priya Raman founded Northwind in 2011.",
     "Priya Raman founded Northwind in 2011 in Oslo.", "support", True),
    ("generic", "Northwind Systems was founded in 2011.",
     "The company was founded in 2011 in Oslo by two engineers.", "support", False),
    ("zh_ok", "金山软件成立于1988年。",
     "1988年，求伯君与另外三人共同创办金山软件公司。", "support", True),
    ("adjacent", "Helio Dynamics acquired Corvus in 2016.",
     "Helio Dynamics was founded in 2011; Corvus was acquired in 2016.",
     "support", True),
]

# (id, claim, year, [lines], does a correct line exist) — end-to-end through
# the real corpus judge, with the fallback ENABLED.
FALLBACK_CASES = [
    # the measured motivation: right answer, ONE shared token -> lexical bar
    # rejects it, and that is the recall the fallback exists to recover
    ("cross_zh", "金山软件成立于1988年。", 1988.0,
     ["1988年，求伯君与另外三人共同创办金山软件公司。"], True),
    ("cross_en", "WPS was announced by Kingsoft in 1989.", 1989.0,
     ["1989年，金山宣布WPS文字处理系统问世。"], True),
    # --- these are RESCUED BY THE FALLBACK, and only by it ----------------
    # A SINGLE-token subject, so claim and line share exactly one token
    # (shared_n = 1) and the lexical bar blocks them; no alias-map entry
    # exists, so nothing deterministic closes the gap. Confidence must come
    # back "medium", never "high": the subject was not established lexically
    # and claiming otherwise would overstate what was actually checked.
    ("one_token_en", "Helio was founded in 2011.", 2011.0,
     ["Helio 于2011年成立。"], True),
    ("one_token_mixed", "Corvus was founded in 2016.", 2016.0,
     ["Corvus 于2016年正式成立。"], True),
    # --- the honest boundary: ZERO token overlap is invisible to the fallback
    # too, because the line never becomes a retrieval candidate at all.
    # Documented so the limit is measured rather than assumed: closing THIS
    # needs Jev inside RETRIEVAL, a separate and unproven design.
    ("zero_overlap", "Northwind was founded in 2011.", 2011.0,
     ["1998年，远景出版社正式成立。"], False),
    # must NOT be rescued: figure matches, milestone does not
    ("off_open", "Solaris Grid opened its Bergen plant in 2011.", 2011.0,
     ["Solaris Grid was founded in 2011 by two engineers."], False),
    ("off_launch", "Vantage Press launched its colour title in 1998.", 1998.0,
     ["Vantage Press was founded in 1998."], False),
    ("off_fund", "Helio Dynamics closed its Oslo office in 2014.", 2014.0,
     ["Helio Dynamics raised 45 million in 2014."], False),
    # the DANGEROUS shape: same figure, same milestone, different entity, and
    # the line is anaphoric so the model would wave it through. Only the
    # deterministic name precondition stands between this and a false green.
    ("wrong_entity", "Northwind Systems was founded in 2011.", 2011.0,
     ["The company was founded in 2011 in Oslo by two engineers."], False),
    ("wrong_entity_named", "Northwind Systems was founded in 2011.", 2011.0,
     ["Solaris Grid was founded in 2011 by two engineers."], False),
]


def post(key, claim, ev):
    payload = {"state": f"CLAIM: {claim}\n\nEVIDENCE: {ev}",
               "model": os.environ.get("JEV_MODEL", "jev-latest"),
               "questions": {"q": {
                   "type": "noul",
                   "instructions": (
                       "Is the EVIDENCE about the same subject as the CLAIM — "
                       "the same organisation, product or person? Answer the "
                       "probability that the claim's subject and the evidence's "
                       "subject are the same entity. A different organisation, "
                       "product or person is NOT the same subject, even when "
                       "the year, figure or event match.")}}}
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return float((d.get("answers", {}).get("q") or {})["noul"])
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except Exception:  # noqa: BLE001
        return None


def load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def part1(key):
    print("PART 1 — raw subject judgment, split by whether the line NAMES the entity")
    print(f"  {'pair':18} {'want':12} {'noul':>7} {'named':>7}  ")
    print("  " + "-" * 54)
    with ThreadPoolExecutor(max_workers=12) as ex:
        vals = list(ex.map(lambda p: post(key, p[1], p[2]), PAIRS))
    fails = []
    named_fp, blind_high = [], []
    for (pid, claim, ev, lab, named), v in zip(PAIRS, vals):
        sup = isinstance(v, float) and v >= 0.5
        if not named:
            # uninformative class: reported, never gated, and never consulted
            if sup and lab == "not-support":
                blind_high.append(pid)
            shown = f"{v:7.3f}" if isinstance(v, float) else f"{str(v):>7}"
            print(f"  {pid:18} {lab:12} {shown} {'no':>7}  "
                  f"n/a (blind: model defaults high)")
            continue
        if sup and lab == "not-support":
            named_fp.append((pid, claim, ev, v))
        shown = f"{v:7.3f}" if isinstance(v, float) else f"{str(v):>7}"
        wrong = sup != (lab == "support")
        print(f"  {pid:18} {lab:12} {shown} {'yes':>7}  "
              f"{'MISS' if wrong else 'ok'}")

    n_ns = sum(1 for p in PAIRS if p[3] == "not-support" and p[4])
    n_s = sum(1 for p in PAIRS if p[3] == "support" and p[4])
    rec = sum(1 for p, v in zip(PAIRS, vals)
              if p[3] == "support" and p[4]
              and isinstance(v, float) and v >= 0.5) / max(1, n_s)
    print("\n  NAMED-ENTITY rows (the ones the fallback relies on):")
    print(f"    recall {rec:.3f}   FALSE-GREEN {len(named_fp)}/{n_ns}")
    for pid, c, e, v in named_fp:
        print(f"      !! {pid} noul={v:.3f}\n         claim {c}\n         line  {e}")
    print(f"  ANAPHORIC rows: {len(blind_high)} answered high while the truth is "
          "not-support")
    print(f"    ({', '.join(blind_high) or 'none'}) — the model cannot see a "
          "mismatch that is\n    not written down, so the fallback requires a "
          "name overlap before asking.")
    if named_fp:
        fails.append(f"{len(named_fp)} false green(s) on NAMED-entity pairs — "
                     f"the class the fallback actually uses")
    if rec < 0.70:
        fails.append(f"named-entity recall {rec:.3f} < 0.70 — fallback inert")
    return fails, rec


def part2(key):
    print("\nPART 2 — end-to-end through the real corpus judge (fallback ON)")
    print(f"  {'case':12} {'want':11} {'verdict':11} {'conf':6} evidence")
    print("  " + "-" * 66)
    aliases = AliasMap.load(ROOT / "tests" / "ks_names.csv")
    os.environ["JEV_SUBJECT_FALLBACK"] = "1"
    bad, missed = [], []
    for cid, sent, yr, lines, should_support in FALLBACK_CASES:
        d = Path(tempfile.mkdtemp())
        (d / "src.md").write_text("\n".join(lines), encoding="utf-8")
        corpus = Corpus(str(d), aliases)
        claim = {"id": cid, "type": "year", "raw": str(int(yr)), "value": yr,
                 "currency": None, "para": 0, "span": [0, 4], "sentence": sent}
        v, conf, ev, _note = judge._check_number(claim, corpus)
        want = "supported" if should_support else "not-support"
        ok = (v == "supported") == should_support
        if v == "supported" and not should_support:
            bad.append(cid)
        if should_support and v != "supported":
            missed.append(cid)
        # a fallback-rescued claim must not claim lexical certainty
        if v == "supported" and cid.startswith("one_token") and conf != "medium":
            bad.append(f"{cid}: rescued by fallback but reported {conf!r}")
        ref = ev[0]["ref"] if ev else "-"
        print(f"  {cid:18} {want:11} {v:11} {conf:6} {ref}  "
              f"{'ok' if ok else 'MISS'}")
    n_sup = sum(1 for c in FALLBACK_CASES if c[4])
    fails = []
    if bad:
        fails.append(f"fallback created false greens: {bad}")
    if len(missed) > max(1, n_sup // 2):
        fails.append(f"fallback recovered only "
                     f"{n_sup - len(missed)}/{n_sup} of its target cases")
    print(f"  recovered {n_sup - len(missed)}/{n_sup}  "
          f"false greens {len(bad)}")
    return fails


def main():
    load_env()
    key = os.environ.get("JEV_API_KEY")
    if not key:
        print("JEV_API_KEY not set - skipping (network-gated test)")
        return 0
    t0 = time.monotonic()
    fails, rec = part1(key)
    fails += part2(key)
    print(f"\nwall clock {time.monotonic() - t0:.1f}s")
    print("JEV ENTITY RISK:", "PASS" if not fails else "FAIL " + "; ".join(fails))
    print("\nNOTE: PART 1 reports the RAW model, which is demonstrably unreliable\n"
          "      on anaphoric evidence and is therefore never consulted there.\n"
          "      PART 2 is the gate that matters: end-to-end, no false green.")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
