"""Free-tier LLM abstraction (optional — every feature degrades without keys).

Provider picked from environment: GEMINI_API_KEY > GROQ_API_KEY > OPENAI_API_KEY.
Plain REST via urllib; no SDK, no cost (all three have usable free tiers).

Discipline: LLM output is only ever used two ways — (1) propose claim candidates
that MUST be found verbatim in the document (else dropped, so the extractor
cannot hallucinate its own inputs), (2) judge evidence snippets that are then
cited back; a bare LLM opinion never becomes a verdict.
"""
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from . import textproc as tp


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


_load_env_file()

GEMINI_MODELS = [m for m in (os.environ.get("GEMINI_MODEL", "").split(",")
                             + ["gemini-3.6-flash", "gemini-2.5-flash",
                                "gemini-2.0-flash"]) if m.strip()]
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{model}:generateContent")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
AGNES_URL = "https://apihub.agnes-ai.com/v1/chat/completions"
AGNES_MODEL = os.environ.get("AGNES_MODEL", "agnes-2.5-flash")
# strict per-request socket timeout: a tarpit/half-closed connection must fail
# in seconds, not 90s x 3 models x N claims (that was the 5-10 min hang)
REQ_TIMEOUT = int(os.environ.get("CHECKMATO_LLM_TIMEOUT", "20"))
# hard wall-clock cap per attempt REGARDLESS of socket activity: a server that
# trickles the response in slow chunks never trips a socket timeout, but must
# never hold a run hostage either (the "13-minute plan, 2 hours actual" trap)
CALL_DEADLINE = int(os.environ.get("CHECKMATO_LLM_DEADLINE", "90"))


class CallTimeout(Exception):
    pass


def _with_deadline(fn, seconds=None):
    """Run fn in a worker thread and give up after `seconds` — the daemon
    thread may linger harmlessly, but the run always proceeds on time."""
    box = {}

    def run():
        try:
            box["out"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(CALL_DEADLINE if seconds is None else seconds)
    if th.is_alive():
        cap = seconds or CALL_DEADLINE
        raise CallTimeout(f"LLM response exceeded {cap}s")
    if "err" in box:
        raise box["err"]
    return box.get("out")

TYPES = ("year", "quote", "number", "fx", "name", "event", "citation", "timeline")


class LLM:
    MIN_GAP = float(os.environ.get("CHECKMATO_LLM_MIN_GAP", "3.2"))  # 20 RPM free tiers

    def __init__(self, max_calls=20, max_tokens=60000, max_seconds=150):
        import time as _t
        self._start = _t.monotonic()
        self._last_call = 0.0
        self.max_seconds = max_seconds
        self.key_gemini = os.environ.get("GEMINI_API_KEY")
        self.key_groq = os.environ.get("GROQ_API_KEY")
        self.key_openai = os.environ.get("OPENAI_API_KEY")
        self.key_agnes = os.environ.get("AGNES_API_KEY")
        self.key = (self.key_gemini or self.key_groq or self.key_openai
                    or self.key_agnes)
        self.gemini_dead = False
        self.gemini_models = list(GEMINI_MODELS)
        self.calls = 0
        self.tokens = 0
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.fail_streak = 0
        self.net_dead = False  # circuit breaker: LLM endpoint unreachable
        self._lock = threading.Lock()
        self._last_tokens = 0

    @property
    def available(self):
        return bool(self.key)

    @property
    def exhausted(self):
        import time as _t
        return (self.net_dead or self.calls >= self.max_calls
                or self.tokens >= self.max_tokens
                or _t.monotonic() - self._start > self.max_seconds)

    def _chat_gemini(self, prompt):
        """Returns text, or None to signal 'fall through to another provider'."""
        for model in self.gemini_models:
            try:
                req = urllib.request.Request(
                    GEMINI_URL.format(model=model) + f"?key={self.key_gemini}",
                    data=json.dumps(
                        {"contents": [{"parts": [{"text": prompt}]}],
                         "generationConfig": {"temperature": 0}}).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as r:
                    out = json.load(r)
                self.gemini_models.remove(model)
                self.gemini_models.insert(0, model)
                um = out.get("usageMetadata") or {}
                self._last_tokens = int(um.get("totalTokenCount") or 0)
                return out["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as e:
                if e.code not in (404, 400, 429):
                    return None
                continue
            except OSError:
                # timeout / dropped connection / DNS: the endpoint is sick —
                # stop the model chain now and fall through to another provider
                self.gemini_dead = True
                return None
        self.gemini_dead = True  # every model failed (retired or geo-blocked)
        return None

    def _chat_openai_style(self, prompt):
        if self.key_openai:
            url, key, model = OPENAI_URL, self.key_openai, "gpt-4o-mini"
        elif self.key_groq:
            url, key, model = GROQ_URL, self.key_groq, "llama-3.3-70b-versatile"
        elif self.key_agnes:
            url, key, model = AGNES_URL, self.key_agnes, AGNES_MODEL
        else:
            return None
        url = os.environ.get("OPENAI_BASE_URL") or url
        model = os.environ.get("OPENAI_MODEL") or model
        req = urllib.request.Request(
            url,
            data=json.dumps({"model": model, "temperature": 0,
                             "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as r:
            out = json.load(r)
        usage = out.get("usage") or {}
        self._last_tokens = int(usage.get("total_tokens") or 0)
        return out["choices"][0]["message"]["content"]

    def chat(self, prompt):
        import time as _t
        if not self.available or self.exhausted:
            return None
        # WHOLE-call cap: per-attempt deadlines still allowed 90s x attempts +
        # 15/30/60 backoffs to accumulate into an 844s single call that froze a
        # deep-check worker (observed). No chat() may exceed CALL_DEADLINE.
        t_all = _t.monotonic()

        def left():
            return CALL_DEADLINE - (_t.monotonic() - t_all)

        with self._lock:
            wait = self.MIN_GAP - (_t.monotonic() - self._last_call)
            self._last_call = max(self._last_call + wait, _t.monotonic())
        if wait > 0:
            _t.sleep(max(0.0, min(wait, max(0.0, left()))))  # 20-RPM free tiers
        with self._lock:
            self.calls += 1
        self._last_tokens = 0
        out = None
        rate_limited = False
        if self.key_gemini and not self.gemini_dead and left() > 10:
            try:
                out = _with_deadline(lambda: self._chat_gemini(prompt),
                                     max(5, left()))
            except Exception:
                out = None
        if not out and left() > 5:
            waits = (15, 30, 60)  # free-tier RPM windows: ride out 429s with backoff
            rate_limited, w = False, 0
            while True:
                try:
                    out = _with_deadline(lambda: self._chat_openai_style(prompt),
                                         max(5, left()))
                    break
                except CallTimeout:
                    out, rate_limited = None, False
                    break  # deadlined: never re-pay the timer for the same prompt
                except urllib.error.HTTPError as e:
                    if (e.code == 429 and w < len(waits)
                            and left() > waits[w] + 15):
                        _t.sleep(waits[w])
                        w += 1
                        rate_limited = True
                        continue
                    out, rate_limited = None, e.code == 429
                    break
                except Exception:
                    out, rate_limited = None, False
                    break
        with self._lock:
            if out:
                self.fail_streak = 0
                used = self._last_tokens or (len(prompt) // 4 + len(out) // 4)
                self.tokens += max(1, used)
            elif rate_limited:
                pass  # rate window is environmental — never trips the breaker
            else:
                self.fail_streak += 1
                if self.fail_streak >= 3:
                    self.net_dead = True  # give up: run degrades, but finishes fast
        return out


def extract_semantic_claims(llm, paragraphs, existing_types_by_para, progress=None):
    """Ask the LLM for checkable assertions the regex floor missed. Every returned
    quote must appear verbatim in its paragraph or it is discarded. Chunked
    (10 paragraphs/call): one giant whole-document call is the slowest, most
    timeout-prone prompt of the run and emits no progress — chunks keep each
    round-trip small, recoverable, and visible on the progress line."""
    if not llm.available:
        return []
    _p = progress or (lambda e: None)
    out = []
    CH = 10
    nchunks = (len(paragraphs) + CH - 1) // CH
    for ci in range(nchunks):
        base = ci * CH
        ch = paragraphs[base:base + CH]
        if llm.exhausted:
            break
        _p({"stage": "thinking", "batches": nchunks, "done": ci + 1,
            "item": f"scanning prose for numberless claims ({ci + 1}/{nchunks})"})
        doc = "\n".join(f"[{base + i}] {p}" for i, p in enumerate(ch))
        prompt = (
            "You are a fact-checking claim extractor. From the numbered document below, "
            "list factual assertions that a checker should verify and that involve NO "
            "digits (skip years, amounts, percentages — already handled). Focus on: "
            "who said/did what, causal or superlative claims ('first', 'largest', 'only'), "
            "entity attributes, quotes, and timeline orderings.\n"
            f'Types allowed: {", ".join(TYPES)}.\n'
            "Return ONLY a JSON array of objects: "
            '{"para": <int>, "type": "<type>", "quote_text": "<exact substring copied from that paragraph, max 220 chars>"}.\n\n'
            f"{doc}\n\nJSON:")
        raw = llm.chat(prompt)
        if not raw:
            continue
        m = re_json(raw)
        for c in m if isinstance(m, list) else []:
            try:
                pidx, q, ctype = int(c["para"]), str(c["quote_text"]).strip(), str(c["type"])
            except (KeyError, ValueError, TypeError):
                continue
            if not (0 <= pidx < len(paragraphs)) or q.lower() not in paragraphs[pidx].lower():
                continue  # not in the document -> drop (anti-hallucination guard)
            i = paragraphs[pidx].lower().find(q.lower())
            if i < 0:
                continue
            raw_txt = paragraphs[pidx][i:i + len(q)]
            out.append({"id": f"x{len(out) + 1:03d}",
                        "type": ctype if ctype in TYPES else "event",
                        "raw": raw_txt, "value": None, "currency": None,
                        "sentence": raw_txt, "para": pidx,
                        "span": [i, i + len(raw_txt)], "anchored": True,
                        "origin": "llm"})
    return out


def resolve_subject(llm, excerpt):
    """Infer what the document is ABOUT (company, people, ORIGIN LANGUAGE) so
    web checks can anchor on 'Kingsoft' and search in the right language even if
    the paragraph never names the company or is English about a Chinese subject."""
    if not llm.available:
        return None
    raw = llm.chat(
        "What organisation (company) is this text about, and which people does it "
        "name (list EVERY named person, up to 15)? Use world knowledge to resolve "
        "people to their company. Respond "
        'ONLY JSON {"subject": "<org name or null>", '
        '"subject_native": "<the same org name written in its OWN native '
        'script/language, e.g. 金山软件 for Kingsoft, or null if same>", '
        '"people": ["<names>"], '
        '"people_native": ["<each person name in its OWN native script, in the '
        'same order as people — use ONLY spellings you are sure of, else null>"], '
        '"origin_language": "<ISO 639-1 code of the company home country '
        "language, e.g. zh, en, ja, fr, or null>\"}\n\n"
        + excerpt[:3500])
    if not raw:
        return None
    i, j = raw.find("{"), raw.rfind("}")
    try:
        d = json.loads(raw[i:j + 1]) if i >= 0 else {}
    except json.JSONDecodeError:
        return None
    return d if d.get("subject") else None


def plan_queries(llm, claims, context):
    """ONE batched call: turn each unverified claim into 1-3 meaningful web
    searches -- the assertion with its entities, a keyword subset, and when the
    subject originates in another language, a query translated into that
    language with proper nouns in native script (Qiu Bojun -> 求伯君)."""
    if not llm.available or not claims:
        return {}
    origin = (context or {}).get("origin_language") or "en"
    subject = (context or {}).get("subject") or "unknown company"
    # authoritative native spellings (subject + people): a planner asked to
    # "translate names from memory" WILL sometimes invent look-alike characters
    # (求伯君->邱伯均), and every CJK query then silently searches the wrong
    # person. Hand it the exact strings instead — same idea as verbatim quotes.
    natives = [str(x).strip() for x in
               ((context or {}).get("people_native") or [])
               + [(context or {}).get("subject_native") or ""]
               if x and str(x).strip().lower() != "null"]
    native_rule = (
        " AUTHORITATIVE native spellings: when writing queries in the origin "
        "language, use these exact names verbatim and NEVER invent or "
        "re-transliterate any other form; for a person NOT listed here keep "
        "the Latin spelling untouched: " + ", ".join(dict.fromkeys(natives))
        + ". " if natives else "")
    has_cjk = any(not q["raw"].isascii() for q in claims)
    doc_lang = "zh" if has_cjk else "en"
    lines = [{"id": c["id"], "text": c["sentence"][:220]} for c in claims]
    translate_rule = (
        f"(c) the claim TRANSLATED into {origin} with proper nouns rendered in "
        "their native form (e.g. Qiu Bojun\u2192求伯君, Room 501\u2192501号房间, "
        "WPS 1.0 stays WPS 1.0). "
        if origin != doc_lang else "")
    raw = llm.chat(
        "You plan web searches to fact-check document claims. "
        f"The document is about: {subject} (origin language: {origin}). "
        f"Claims language: {doc_lang}. For EACH claim produce 1-3 search "
        "queries: (a) the assertion rewritten as a searchable phrase that "
        "includes the key entities and the year/amount, so results address "
        "WHAT HAPPENED, not isolated words; (b) a tight keyword subset — only "
        "content words sources really use: entity names (native script when "
        "origin differs), figures AS DIGITS, event nouns; NEVER stray "
        "adjectives or word fragments (no 'old' from 'twenty-two-year-old'); "
        + translate_rule
        + native_rule
        + "No operators, no URLs. Return ONLY a JSON object mapping claim id "
        "to an array of query strings.\n\nClaims:\n"
        + json.dumps(lines, ensure_ascii=False) + "\n\nJSON:")
    if not raw:
        return {}
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0:
        return {}
    try:
        d = json.loads(raw[i:j + 1])
    except json.JSONDecodeError:
        return {}
    out = {}
    for cid, qs in (d or {}).items():
        if isinstance(qs, str):
            qs = [qs]
        clean = [str(q)[:160] for q in (qs or [])
                 if isinstance(q, str) and len(str(q).strip()) > 8]
        if clean:
            out[str(cid).strip()] = clean[:3]
    return out


def auto_aliases(llm, doc_names, corpus_names):
    """Match names in two languages/scripts: 'Qiu Bojun' (document) ↔
    '求伯君' (source book) so cross-script evidence retrieval works without the
    user hand-writing a glossary. Each returned pair is re-verified to exist in
    its own input list."""
    if not llm.available or not doc_names or not corpus_names:
        return []
    raw = llm.chat(
        "List A = names used in a document. List B = names used in a source book "
        "(possibly another language/script). Pair names that refer to the SAME "
        "person or organisation. Only exact identities — never guess.\n"
        f"A: {doc_names[:20]}\nB: {corpus_names[:30]}\n"
        'Respond ONLY JSON array of pairs: [["A name","B name"], ...]')
    pairs = re_json(raw)
    a_set = {n.lower(): n for n in doc_names}
    b_set = {n.lower(): n for n in corpus_names}
    out = []
    for p in pairs if isinstance(pairs, list) else []:
        try:
            a = a_set[str(p[0]).lower()]
            b = b_set[str(p[1]).lower()]
        except (KeyError, IndexError, TypeError):
            continue
        if tp.tokens(a) == tp.tokens(b):
            continue  # same script/name on both sides is not an alias
        out.append((a, b))
    return out


def re_json(text):
    i, j = text.find("["), text.rfind("]")
    if i < 0 or j <= i:
        return []
    try:
        return json.loads(text[i:j + 1])
    except json.JSONDecodeError:
        return []


def judge_snippets(llm, claim, snippets):
    """LLM reads ONLY the collected evidence snippets and returns a verdict with a
    citation, or None when it declines. Never shown as truth without the snippet."""
    if not llm.available or not snippets:
        return None
    ev = "\n".join(f"- {s['ref']}: {s['quote'][:300]}" for s in snippets[:6])
    prompt = (
        "A fact-checker has these raw evidence snippets about a claim. Decide "
        "supported / contradicted / unverified STRICTLY from the snippets. If the "
        "snippets do not directly address the claim, answer unverified.\n"
        "Rules: (1) evidence about a DIFFERENT organisation that merely shares "
        "part of the name (a subsidiary, spin-off or lookalike) does NOT settle "
        "the claim — answer unverified; (2) a later outcome does not contradict "
        "an earlier intention, refusal or state ('would not return' is not "
        "contradicted by a return that happened afterwards); contradict only "
        "the SAME event with an incompatible value or date.\n"
        f'Claim ({claim["type"]}): {claim["raw"]}\nEvidence:\n{ev}\n'
        'Return ONLY JSON {"verdict":"supported|contradicted|unverified",'
        '"cite":"<ref used>","note":"<one sentence>"}:')
    raw = llm.chat(prompt)
    if not raw:
        return None
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0:
        return None
    try:
        d = json.loads(raw[i:j + 1])
    except json.JSONDecodeError:
        return None
    if d.get("verdict") not in ("supported", "contradicted", "unverified"):
        return None
    return d


def judge_pool(llm, claims, snippets):
    """ONE batched cross-proof pass: every still-unverified claim is checked
    against ALL snippets collected this run. A source fetched for one claim
    often proves another (even in another language — the LLM bridges scripts);
    the mandatory verbatim-quote guard means it still cannot invent evidence."""
    if not llm.available or not claims or not snippets:
        return []
    cl = [{"id": c["id"], "claim": c["sentence"][:200]} for c in claims[:24]]
    ev = [{"i": i + 1, "text": s["text"][:260]} for i, s in enumerate(snippets)]
    raw = llm.chat(
        "Fact-checking. CLAIMS are sentences from one document. EVIDENCE "
        "snippets were collected from the web while checking this document — "
        "a snippet retrieved for one claim may PROVE another, and it may be in "
        "a different language (translate before judging). For each claim you "
        "can settle return {\"id\": <claim id>, \"verdict\": "
        '"supported|contradicted", "ev": <evidence number>, "quote": '
        '"<verbatim substring of that evidence text that proves it>", '
        '"note": "<one short sentence>"}. The quote MUST appear verbatim in '
        "the evidence (in its own language). Rules: evidence about a DIFFERENT "
        "organisation that merely shares part of the subject's name (subsidiary, "
        "spin-off, lookalike) settles NOTHING; a later outcome does not "
        "contradict an earlier intention, refusal or state — contradict only "
        "the same event with an incompatible value or date. If nothing settles "
        "a claim, omit it. NEVER use outside knowledge. Return ONLY a JSON "
        "array.\n\n"
        "CLAIMS:\n" + json.dumps(cl, ensure_ascii=False)
        + "\n\nEVIDENCE:\n" + json.dumps(ev, ensure_ascii=False) + "\n\nJSON:")
    if not raw:
        return []
    by_i = {i + 1: s for i, s in enumerate(snippets)}
    valid_ids = {c["id"] for c in claims}
    out = []
    arr = re_json(raw)
    for d in arr if isinstance(arr, list) else []:
        try:
            cid, i, q = str(d["id"]), int(d["ev"]), str(d["quote"])
        except (KeyError, ValueError, TypeError):
            continue
        if (cid not in valid_ids or i not in by_i
                or d.get("verdict") not in ("supported", "contradicted")):
            continue
        nq = tp.normalize(q)
        if nq[:120] and nq[:120] not in tp.normalize(by_i[i]["text"]):
            continue  # 'proof' not actually inside the snippet -> reject
        out.append({"id": cid, "verdict": d["verdict"], "ev": i,
                    "note": str(d.get("note") or "")[:160]})
    return out
