r"""JEV concurrency experiment — can isolated calls be safely parallelised?

Network-gated, NOT in run_all.py. Run:
    .venv\Scripts\python.exe -X utf8 tests\test_jev_concurrency.py [max_workers]

WHY
test_jev_gate.py proved that ISOLATED calls (one claim+evidence per request)
have a 0.000 false-green rate over 18 labelled pairs, while batching unrelated
pairs into one state is unsafe. But isolated calls at 0.27s each would add
~97s of serial wall clock to a single deep-pass cluster (24 claims x ~15
snippets), which would more than double a 60-140s run.

So the question is whether concurrency can recover the speed WITHOUT
reintroducing contamination. Two things could break:

  1. ANSWER DRIFT — if the service degrades or cross-talk appears under
     parallel load, answers shift and thresholds cross. That is the failure
     that would poison verdicts, so it is asserted, not just reported.
  2. RATE LIMITS — TypeSafe is early access and publishes no numbers. A 429
     storm under load would make concurrency unusable regardless of (1).

Fixtures are imported from test_jev_gate so both files judge the same pairs.

MEASURED RESULT (jev-1.13.0, 18 pairs)
  serial noise floor (serial vs serial, zero load) : max drift 0.090, 0 crossings
  w=2  3.1x  max drift 0.090  0 crossings  0 errors
  w=4  5.8x  max drift 0.070  0 crossings  0 errors
  w=8  9.7x  max drift 0.060  0 crossings  0 errors
  w=16 13.8x max drift 0.070  0 crossings  0 errors
  score distribution is bimodal and far from the threshold: lowest support
  0.750 (+0.25 headroom), highest non-support 0.060 (+0.44 headroom).

Drift under load is SMALLER than the idle noise floor, so concurrency adds no
measurable contamination — Jev is simply not temperature-0. Conclusion: isolated
calls may be threaded. 360 pairs (one deep-pass cluster) cost ~11s at 16
workers instead of ~97s serial.

CAVEATS, honestly
  - n=18 fixtures; the wide margin is why nothing crosses, and the margin was
    measured on those same 18 points.
  - No 429s at 16 concurrent, but early-access limits are unpublished and 18x16
    is a small absolute burst. A sustained 360-pair burst is untested.
  - Nondeterminism means a gate answer is not reproducible run to run, so gate
    output must never be cached as a verdict across runs.
"""
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_jev_gate import PAIRS, THRESHOLD, load_env, post, q_for  # noqa: E402

N = len(PAIRS)


def one(key, pid, claim, ev):
    """Returns (pid, noul, model, error). Never raises."""
    r, _dt = post(key, {"state": f"CLAIM: {claim}\n\nEVIDENCE: {ev}",
                        "model": "jev-latest", "questions": {pid: q_for(claim)}})
    if "__http" in r:
        return pid, None, r.get("model"), f"HTTP {r.get('__http')}: {str(r.get('__body'))[:90]}"
    a = (r.get("answers") or {}).get(pid) or {}
    return pid, float(a.get("noul", 0.0)), r.get("model"), None


def run_serial(key):
    out, models, errs, t0 = {}, set(), [], time.monotonic()
    for pid, _cid, claim, ev, _l in PAIRS:
        p, v, m, e = one(key, pid, claim, ev)
        out[p] = v
        if m:
            models.add(m)
        if e:
            errs.append(e)
        time.sleep(0.15)
    return out, models, errs, time.monotonic() - t0


def run_pool(key, workers):
    out, models, errs, t0 = {}, set(), [], time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, key, pid, claim, ev)
                for pid, _cid, claim, ev, _l in PAIRS]
        for f in futs:
            p, v, m, e = f.result()
            out[p] = v
            if m:
                models.add(m)
            if e:
                errs.append(e)
    return out, models, errs, time.monotonic() - t0


def compare(ref, got, label):
    drifts, cross, missing, worst = [], [], [], []
    for pid, _cid, _c, _e, lab in PAIRS:
        r, g = ref.get(pid), got.get(pid)
        if r is None or g is None:
            missing.append(pid)
            continue
        d = abs(r - g)
        drifts.append(d)
        worst.append((d, pid, r, g, lab))
        if (r >= THRESHOLD) != (g >= THRESHOLD):
            cross.append((pid, r, g, lab))
    if drifts:
        print(f"  {label:10} n={len(drifts):2}  max drift {max(drifts):.4f}  "
              f"mean {statistics.fmean(drifts):.4f}  "
              f">0.10: {sum(1 for d in drifts if d > 0.10)}  "
              f"crossings: {len(cross)}  missing: {len(missing)}")
        for d, pid, r, g, lab in sorted(worst, reverse=True)[:3]:
            print(f"      drift {d:.4f}  {pid:24} {r:.3f}->{g:.3f} "
                  f"(truth {lab})")
    for pid, r, g, lab in cross:
        print(f"      CROSS {pid:24} serial={r:.3f} {label}={g:.3f} "
              f"(truth {lab})")
    for e in missing:
        print(f"      MISSING {e}")
    return cross, missing, (max(drifts) if drifts else 0.0)


def margin(got):
    """How much headroom the score distribution keeps around THRESHOLD.

    Raw max-drift is the wrong safety criterion here: a pair can drift 0.19
    without any risk if nothing sits near the threshold. What matters is that
    supports stay above it and non-supports stay below it, with room to spare
    for the observed noise.
    """
    sup = [got[pid] for pid, _c, _cl, _e, lab in PAIRS
           if lab == "support" and pid in got]
    ns = [got[pid] for pid, _c, _cl, _e, lab in PAIRS
          if lab != "support" and pid in got]
    if not sup or not ns:
        return None
    return min(sup), max(ns)


def main():
    load_env()
    key = os.environ.get("JEV_API_KEY")
    if not key:
        print("JEV_API_KEY not set - skipping (network-gated test)")
        return 0
    maxw = int(sys.argv[1]) if len(sys.argv) > 1 else 16

    ref, models, errs, t_ref = run_serial(key)
    print(f"serial reference: {N} calls {t_ref:.2f}s "
          f"({t_ref / N:.3f}s each)  models={sorted(models)}  errors={len(errs)}")
    for e in errs:
        print(f"    {e}")
    if len(ref) < N:
        print("serial reference incomplete - aborting, cannot compare")
        return 1

    # --- CONTROL: serial vs serial. Jev samples in parallel internally, so it
    # is not temperature-0. Without this floor, drift under concurrency cannot
    # be attributed to concurrency at all.
    print("\ncontrol (serial vs serial, same width, no load):")
    floor = 0.0
    for i in range(2):
        again, _m, _e, _t = run_serial(key)
        cross, missing, mx = compare(ref, again, f"serial#{i + 2}")
        floor = max(floor, mx)
        if cross or missing:
            print(f"      ^ noise floor is NOT benign ({len(cross)} crossings)")
        time.sleep(0.5)
    print(f"  => serial-vs-serial noise floor: {floor:.4f}")

    print()
    m = margin(ref)
    if m:
        print(f"margin around THRESHOLD={THRESHOLD}: "
              f"lowest support {m[0]:.3f} (headroom {m[0] - THRESHOLD:+.3f})  "
              f"highest non-support {m[1]:.3f} (headroom {THRESHOLD - m[1]:+.3f})")
        print("  distribution is bimodal and far from the threshold, so a "
              "large drift inside the gap is harmless")

    print()
    speedups, bad = [], []
    for w in (2, 4, 8, 16):
        if w > maxw:
            break
        got, gmodels, gerrs, t = run_pool(key, w)
        sp = t_ref / t if t else 0
        speedups.append((w, sp, t))
        flag = ""
        if gerrs:
            flag = f"  <-- {len(gerrs)} ERRORS"
        if sorted(gmodels) != sorted(models):
            flag += f"  <-- MODEL CHANGED {sorted(gmodels)}"
        print(f"  workers={w:<3} {t:6.2f}s  speedup {sp:4.1f}x  "
              f"errors {len(gerrs)}  models={sorted(gmodels)}{flag}")
        cross, missing, mx = compare(ref, got, f"w={w}")
        mg = margin(got)
        headroom = min(mg[0] - THRESHOLD, THRESHOLD - mg[1]) if mg else 0.0
        # the only drift that can change a verdict is one that crosses the
        # threshold; assert that, plus that the distribution keeps clear of it
        if cross or missing or gerrs or headroom <= 0:
            bad.append((w, len(cross), len(missing), len(gerrs), mx, headroom))
        for e in gerrs[:3]:
            print(f"      {e}")
        time.sleep(1.0)  # let any per-window rate limit reset

    print("\n  speedup curve: "
          + "  ".join(f"{w}w={sp:.1f}x" for w, sp, _t in speedups))
    if speedups:
        best_w, best_sp, best_t = max(speedups, key=lambda x: x[1])
        print(f"  best: {best_w} workers -> {best_sp:.1f}x, "
              f"{N} pairs in {best_t:.2f}s "
              f"({best_t / N:.3f}s/pair effective)")
        print(f"  drift under load ({max(b[4] for b in bad) if bad else 0:.3f}) "
              f"vs serial noise floor ({floor:.3f})")

    fails = []
    for w, ncross, nmiss, nerr, mx, hr in bad:
        fails.append(f"w={w}: {ncross} crossings, {nmiss} missing, "
                     f"{nerr} errors, headroom {hr:+.3f}")
    print("\nJEV CONCURRENCY:",
          "PASS" if not fails else "FAIL " + " | ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
