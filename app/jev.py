"""Jev (TypeSafe System One) — the ONE dimension a model may own in a verdict.

WHAT THIS IS NOT
    Not a judge. Jev cannot generate strings; it returns a probability per
    question. It therefore never writes a verdict, never writes evidence text,
    and never produces a `file:line` (design rules 2 and 14).

WHY IT EXISTS AT ALL
    The corpus judge's subject bar is `shared_n >= 2` shared NON-NUMERIC tokens
    between claim and line. That bar is what stops a coincidental year on an
    unrelated line from becoming a false green, and it is deliberately
    lexical. Measured cost of that lexicalism: correct cross-script lines get
    rejected for sharing only ONE token ("金山" / "wps"), which reads as
    `unverified` on facts the user can see in their own source.

    Jev judges subject identity better than the bar does (0.97/0.95 on exactly
    those pairs) and, on the adversarial set where a false green would need
    same event + same figure + WRONG entity, it scored 0/7 wrong
    (tests/test_jev_entity_risk.py, network-gated). So it is allowed to stand
    in for the ENTITY check and nothing else.

THE CONTRACT (this is the safety argument, in full)
    A Jev-assisted `supported` still requires ALL of:
      1. the FIGURE to match, deterministically (`num_matches`)
      2. the PREDICATE to agree, deterministically (`_predicate_ok`)
      3. the model to confirm the entity, above a conservative threshold
    Only the lexical-overlap requirement is replaced. Contradiction power is
    never delegated (rule 14). And because this runs ONLY after the
    deterministic path has already returned `unverified`, the change is
    MONOTONE: no existing verdict can flip, the worst case is a missed recall
    gain, and every failure mode (no key, timeout, 4xx, malformed answer)
    degrades to "no change" rather than to a guess.

NONDETERMINISM
    Jev is a classifier, not a calculator: a serial-vs-serial noise floor of
    0.090 was measured, so a single run proves nothing on its own. The
    threshold below sits far from both observed populations (genuine supports
    0.97-0.99, the one false negative 0.42) rather than near a 0.5 midpoint.
"""
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("checkmato.jev")

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")

# Genuine supports measured 0.97-0.99; the only observed error was a false
# NEGATIVE at 0.42. Sitting at 0.60 rather than 0.50 keeps margin on both
# sides of that gap and costs nothing on the real positives.
SUBJECT_T = float(os.environ.get("JEV_SUBJECT_T", "0.60"))
REQ_TIMEOUT = int(os.environ.get("CHECKMATO_JEV_TIMEOUT", "12"))
# At most this many lines per claim are worth a model call. The candidates are
# pre-filtered deterministically and arrive best-lexical-first, so the cap
# costs recall only in the rare case where the subject match sits deeper in
# the list — and it bounds worst-case latency to ONE round trip.
MAX_LINES = int(os.environ.get("JEV_MAX_LINES", "4"))

INSTR = ("Is the EVIDENCE about the same subject as the CLAIM — the same "
         "organisation, product or person? Answer the probability that the "
         "claim's subject and the evidence's subject are the same entity. "
         "A different organisation, product or person is NOT the same subject, "
         "even when the year, figure or event match.")


def _load_env_file():
    p = Path(__file__).resolve().parents[1] / ".env"
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


def available():
    """True only if a key is configured and the path is not switched off.

    Offline -> the whole path is inert and the corpus judge behaves exactly as
    it did before Jev existed. `JEV_SUBJECT_FALLBACK=0` is the kill switch.
    """
    _load_env_file()
    if os.environ.get("JEV_SUBJECT_FALLBACK", "1").strip() in ("0", "false", "no"):
        return False
    return bool(os.environ.get("JEV_API_KEY"))


def same_subject(claim_sentence, line):
    """P(claim's subject == line's subject), or None if unanswerable.

    None is a first-class answer meaning "no opinion": no key, network error,
    timeout, HTTP status, or a response missing the field. Callers must treat
    None as 'do not use', never as 0.0 — a 0.0 would silently read as a
    confident "different subject" and is not what an outage means.
    """
    _load_env_file()
    key = os.environ.get("JEV_API_KEY")
    if not key:
        return None
    payload = {
        "state": f"CLAIM: {claim_sentence}\n\nEVIDENCE: {line}",
        "model": MODEL,
        "questions": {"q": {"type": "noul", "instructions": INSTR}},
    }
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        # a rate limit or a revoked key must degrade to silence, loudly
        log.debug("jev http %s — subject check skipped", e.code)
        return None
    except Exception as e:  # noqa: BLE001
        log.debug("jev unavailable (%s) — subject check skipped", e)
        return None
    try:
        return float((data.get("answers", {}).get("q") or {})["noul"])
    except (KeyError, TypeError, ValueError):
        log.debug("jev answer missing 'noul' — subject check skipped")
        return None
