r"""JEV (TypeSafe System One) relevance-gate evaluation — network-gated, NOT in
run_all.py (same convention as test_blind_lego.py). Run:
    .venv\Scripts\python.exe -X utf8 tests\test_jev_gate.py

WHAT THIS MEASURES
Jev cannot generate strings, so it can never replace the generative judge. What
it CAN do is gate it: one noul question per (claim, evidence) pair answers
"does this evidence state this claim?", and only pairs that clear a threshold
are worth spending an expensive generative call on.

Two numbers decide whether that is safe to build on:
  1. FALSE-GREEN RATE — P(jev says support | truth is not-support). A high
     value would poison the pipeline, because a false green becomes evidence.
  2. BATCH ISOLATION — CheckMato's core premise is that each judgement sees
     ONLY its own evidence. Three batching shapes are compared against the
     isolated ground truth:
       isolated      one call per pair (reference, and the ONLY shape we use)
       batched_all   every pair in ONE state          <- shown UNSAFE
       batched_claim one state per CLAIM, all of that
                     claim's evidence blocks in it    <- also shown UNSAFE

MEASURED RESULT (2026-09-26, 18 pairs, THRESHOLD 0.5)
  isolated      18/18 correct, support recall 1.000, false-green 0.000
  batched_claim 16/18 correct, support recall 0.818, false-green 0.182
  batched_all   14/18 correct, support recall 0.636, false-green 0.364
Batching collapses recall under distraction and does it SILENTLY — the call
still returns 200 with a confident number. So the conclusion is not "batching is
slightly worse", it is "isolated or nothing", and the gate below is written to
enforce exactly that rather than to keep re-litigating a settled question.

LABELS ARE ABOUT TEXT, NOT THE WORLD
Every (claim, evidence) pair below is a fixed string, and the label is simply
"does this evidence text assert the claim's figure/event?" — checkable by
reading, with no need for the text to be factually true. The evidence lines are
CONSTRUCTED for this benchmark (shaped like the real CJK/EN snippets the
pipeline meets), not scraped quotes. So this measures Jev's discrimination, not
the web's truthfulness, and a pass here is NOT evidence that CheckMato's
verdicts are correct.

A first run of this file MISLABELLED `grad_fudan`: the claim says Fudan
University while the evidence says 国防科技大学, i.e. the claim carries a planted
error — Jev scored it 0.02 and was RIGHT. The label was wrong. A fixture that
the model corrects is worth keeping, so it is split into an honest support pair
and an explicit planted-error pair.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.typesafe.ai/v1/systemone"
THRESHOLD = 0.5

# Recorded false-green rates of the DISPROVEN batched shapes (2026-09-26), with
# slack for Jev's measured 0.090 noise floor. These are regression ceilings, not
# targets: only `isolated` is gated on correctness. See the note in main().
REC_BATCHED_CLAIM_FG = 0.20
REC_BATCHED_ALL_FG = 0.40

# (pair_id, claim_id, claim, evidence, label)  label: "support" | "not-support"
# "not-support" deliberately merges contradicts + irrelevant: per design rule 14
# no LLM holds contradiction power, so the gate never needs to tell them apart.
PAIRS = [
    ("grad_1984", "C1984", "Qiu Bojun graduated in 1984.",
     "1984年，求伯君毕业于国防科技大学。", "support"),
    ("grad_fudan", "C1984F", "Qiu Bojun graduated in 1984 from Fudan University.",
     "1984年，求伯君毕业于国防科技大学。", "not-support"),
    ("founded_1991", "F91", "Kingsoft was founded in 1991.",
     "1988年，求伯君与另外三人共同创办金山软件公司。", "not-support"),
    ("founded_1988", "F88", "Kingsoft was founded in 1988.",
     "1988年，求伯君与另外三人共同创办金山软件公司。", "support"),
    ("founded_1988_bio", "F88B", "Kingsoft was founded in 1988.",
     "求伯君出生于1964年，广东江门人，毕业于西安交通大学。", "not-support"),
    ("founded_1988_poison", "F88P", "Kingsoft was founded in 1988.",
     "The Toyota Camry 2024 review: best-in-class fuel economy and a roomy "
     "501-inch cabin with a 12.3-inch touchscreen.", "not-support"),
    ("founded_1988_listing", "F88L", "Kingsoft was founded in 1988.",
     "Kingsoft Office Limited listed on the Hong Kong Stock Exchange in 2007 "
     "under stock code 3888 and is headquartered in Lei King Wan, Hong Kong.",
     "not-support"),
    ("seed_30k", "S30K", "Qiu Bojun founded Kingsoft with 30000 yuan.",
     "Qiu Bojun, Kingsoft's founder, started the company in 1988 with 30,000 "
     "yuan of his own savings.", "support"),
    ("seed_30k_wrongyear", "S30KW", "Qiu Bojun founded Kingsoft with 30000 yuan in 1989.",
     "Qiu Bojun, Kingsoft's founder, started the company in 1988 with 30,000 "
     "yuan of his own savings.", "not-support"),
    ("fund_1992", "Z92", "Zhang Xuanlong funded Qiu Bojun in 1992.",
     "1992年，张旭龙提出为求伯君提供资金开发文字处理软件。", "support"),
    ("rev_90pct", "R90", "Over 90% of Kingsoft's revenue came from software.",
     "Kingsoft reported that 95% of its revenue was generated by software "
     "products in that fiscal year.", "support"),
    ("headcount", "H200", "Kingsoft had 200 employees in 1998.",
     "Kingsoft had 2,000 employees in 1998.", "not-support"),
    ("wps_1989", "W89", "WPS was announced by Kingsoft in 1989.",
     "1988年，求伯君与另外三人共同创办金山软件公司。", "not-support"),
    ("share_2289", "M2289", "Kingsoft's market share was 22.89% in 2007.",
     "Kingsoft's market share rose by 22.89 percentage points in 2007.",
     "not-support"),
    ("share_2289_ok", "M2289OK", "Kingsoft's market share was 22.89% in 2007.",
     "Kingsoft held 22.89% of the Chinese word processor market in 2007.",
     "support"),
    ("fx_3m", "X3M", "The investment was RMB 3 million (about US$4.5 million).",
     "The investment totalled 3 million yuan, equivalent to roughly 4.5 "
     "million US dollars at the time.", "support"),
    ("ratio_26of40", "N26", "Kingsoft had 26 employees out of 40 in its first year.",
     "Kingsoft was widely praised in the Chinese press for its early product "
     "quality and the dedication of its small engineering team.",
     "not-support"),
    ("sony_tr55", "T55", "Sony released the TR-55 in 1988.",
     "The TR-55, released by Sony in 1978, was the company's first portable "
     "single-lens reflex camera.", "not-support"),
]

INSTR = ("Does the EVIDENCE block directly support the specific CLAIM, "
         "including its figure, year, entity and event? Evidence naming a "
         "different year, a different figure, a different organisation or "
         "person, or a different event does NOT support it. Answer the "
         "probability that the claim is supported by that evidence block.")


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


def post(key, payload, timeout=60):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace")), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return {"__http": e.code,
                "__body": e.read().decode("utf-8", "replace")[:300]}, time.monotonic() - t0
    except Exception as e:  # noqa: BLE001
        return {"__http": None, "__body": f"{type(e).__name__}: {e}"}, time.monotonic() - t0


def q_for(claim):
    return {"type": "noul", "instructions": f"{INSTR}\n\nCLAIM: {claim}"}


def run_batched_all(key):
    qs = {pid: q_for(c) for pid, _cid, c, _e, _l in PAIRS}
    state = "\n\n".join(f"EVIDENCE {i}: {e}"
                        for i, (_p, _c, _cl, e, _l) in enumerate(PAIRS))
    r, dt = post(key, {"state": state, "model": "jev-latest", "questions": qs})
    if "__http" in r:
        return {}, dt, 0
    nouls = {k: float(v.get("noul", 0.0))
             for k, v in (r.get("answers") or {}).items()}
    return nouls, dt, (r.get("usage") or {}).get("input_tokens", 0)


def run_batched_claim(key):
    groups = defaultdict(list)
    for pid, cid, claim, ev, label in PAIRS:
        groups[cid].append((pid, claim, ev, label))
    out, calls, dt_tot, tokens = {}, 0, 0.0, 0
    for cid, items in groups.items():
        qs = {pid: q_for(claim) for pid, claim, _e, _l in items}
        state = "\n\n".join(f"EVIDENCE {pid}: {e}" for pid, _c, e, _l in items)
        r, dt = post(key, {"state": state, "model": "jev-latest", "questions": qs})
        dt_tot += dt
        calls += 1
        if "__http" in r:
            continue
        tokens += (r.get("usage") or {}).get("input_tokens", 0)
        for pid, a in (r.get("answers") or {}).items():
            out[pid] = float(a.get("noul", 0.0))
        time.sleep(0.15)
    return out, calls, dt_tot, tokens


def run_isolated(key):
    out, calls, dt_tot, tokens = {}, 0, 0.0, 0
    for pid, _cid, claim, ev, _l in PAIRS:
        r, dt = post(key, {"state": f"CLAIM: {claim}\n\nEVIDENCE: {ev}",
                           "model": "jev-latest", "questions": {pid: q_for(claim)}})
        dt_tot += dt
        calls += 1
        if "__http" in r:
            continue
        tokens += (r.get("usage") or {}).get("input_tokens", 0)
        a = (r.get("answers") or {}).get(pid) or {}
        out[pid] = float(a.get("noul", 0.0))
        time.sleep(0.15)
    return out, calls, dt_tot, tokens


def verdicts(nouls):
    def is_support(pid, lab):
        return nouls.get(pid, -1) >= THRESHOLD
    hit = sum(1 for pid, _c, _cl, _e, lab in PAIRS
              if is_support(pid, lab) == (lab == "support"))
    tp = sum(1 for pid, _c, _cl, _e, lab in PAIRS
             if lab == "support" and is_support(pid, lab))
    fp = sum(1 for pid, _c, _cl, _e, lab in PAIRS
             if lab != "support" and is_support(pid, lab))
    n_sup = sum(1 for *_r, lab in PAIRS if lab == "support")
    n_ns = len(PAIRS) - n_sup
    return hit, len(PAIRS), tp / max(1, n_sup), fp / max(1, n_ns)


def main():
    load_env()
    key = os.environ.get("JEV_API_KEY")
    if not key:
        print("JEV_API_KEY not set - skipping (network-gated test)")
        return 0

    iso, n_iso, t_iso, tok_iso = run_isolated(key)
    ba, t_ba, tok_ba = run_batched_all(key)
    bc, n_bc, t_bc, tok_bc = run_batched_claim(key)
    print(f"isolated      : {n_iso:2} calls {t_iso:6.2f}s  in={tok_iso} tok")
    print(f"batched_claim : {n_bc:2} calls {t_bc:6.2f}s  in={tok_bc} tok")
    print(f"batched_all   :  1 call {t_ba:6.2f}s  in={tok_ba} tok")

    print(f"\n  {'pair':24} {'want':12} {'isolated':>9} {'b/claim':>9} {'b/all':>7}")
    modes = {"iso": iso, "bc": bc, "ba": ba}
    for pid, _cid, _c, _e, label in PAIRS:
        row = f"  {pid:24} {label:12}"
        for k in ("iso", "bc", "ba"):
            v = modes[k].get(pid)
            row += f" {v:9.3f}" if v is not None else f" {'-':>9}"
        marks = "".join("X" if (modes[k].get(pid, -1) >= THRESHOLD) != (label == "support")
                        else " " for k in ("iso", "bc", "ba"))
        row += "  " + (f"MISSED:{marks.count('X')}" if "X" in marks else "ok")
        print(row)

    print()
    out = {}
    for name, nn in (("isolated", iso), ("batched_claim", bc), ("batched_all", ba)):
        hit, n, rec, fg = verdicts(nn)
        out[name] = (hit, rec, fg)
        print(f"  {name:14} correct {hit:2}/{n}  support recall {rec:.3f}  "
              f"FALSE-GREEN {fg:.3f}")

    cross_iso_bc = sum(1 for pid, *_ in PAIRS
                       if pid in iso and pid in bc
                       and (iso[pid] >= THRESHOLD) != (bc[pid] >= THRESHOLD))
    print(f"\n  batched_claim vs isolated threshold crossings: {cross_iso_bc}")

    # WHAT IS ASSERTED, AND WHY
    # ISOLATED is the only shape CheckMato will use, so that is the only shape
    # gated on correctness: a false green there would become evidence. The
    # batched shapes are already DISPROVEN above (0.182 / 0.364 false-green) —
    # asserting they were safe would be asserting a falsehood, which is how a
    # test ends up encoding the bug it was written to catch. They are instead
    # held to their RECORDED baseline, so the comparison stays meaningful and a
    # silent regression is still caught. Jev is nondeterministic (measured noise
    # floor 0.090), so these are slack ceilings, not exact values.
    fails = []
    missing = [pid for pid, *_ in PAIRS if pid not in iso]
    if missing:
        fails.append(f"isolated returned no score for {len(missing)} pairs "
                     f"(first: {missing[0]}) — endpoint/format problem, not a verdict")
    elif out["isolated"][2] > 0:
        fails.append(f"isolated false-green {out['isolated'][2]:.3f} > 0")
    if not missing and out["isolated"][0] < len(PAIRS) - 1:
        fails.append(f"isolated correct {out['isolated'][0]}/{len(PAIRS)}")
    if out["batched_claim"][2] > REC_BATCHED_CLAIM_FG:
        fails.append(f"batched_claim false-green {out['batched_claim'][2]:.3f} "
                     f"worse than recorded {REC_BATCHED_CLAIM_FG:.2f}")
    if out["batched_all"][2] > REC_BATCHED_ALL_FG:
        fails.append(f"batched_all false-green {out['batched_all'][2]:.3f} "
                     f"worse than recorded {REC_BATCHED_ALL_FG:.2f}")
    print("\nJEV GATE:", "PASS" if not fails else "FAIL " + "; ".join(fails))
    print("NOTE: isolated is the ONLY sanctioned shape (rule 2: evidence or "
          "honesty — batching admits false greens). Batched numbers are held to\n"
          "      their recorded baseline for regression detection only; a PASS "
          "here does not license batching.")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
