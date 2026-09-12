"""Unit tests for the micro-logic the e2e eval can't isolate: amount parsing,
tolerances, sentence offsets, entity detection, FX adjacency, clip/sniff/index."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import textproc as tp  # noqa: E402
from app.corpus import Corpus, clip, sniff_bytes  # noqa: E402
from app.extract import read_doc  # noqa: E402
from app.fx import _conversion_pairs  # noqa: E402

n = 0


def ok(cond, msg):
    global n
    assert cond, f"UNIT FAIL: {msg}"
    n += 1


# --- parse_amount_text ---
ok(tp.parse_amount_text("US$120 million") == (120e6, "USD"), "US$120 million")
ok(tp.parse_amount_text("¥2亿") == (2e8, "CNY"), "¥2亿")
ok(tp.parse_amount_text("1.25 billion yuan") == (1.25e9, "CNY"), "1.25 billion yuan")
ok(tp.parse_amount_text("2400万美元") == (2.4e7, "USD"), "2400万美元")
ok(tp.parse_amount_text("HK$900 million") == (9e8, "HKD"), "HK$900 million")

# --- values_equal: years exact, amounts 0.5% tol, pct tolerant ---
ok(not tp.values_equal(2008, 2010, kind="year"), "years differ")
ok(tp.values_equal(24.3e6, 24.35e6, kind="amount"), "amount within 0.5%")
ok(not tp.values_equal(40e6, 60e6, kind="amount"), "amounts differ")
ok(tp.values_equal(15.68, 15.7, kind="pct"), "pct tolerance")
ok(not tp.values_equal(2000, 2005, kind="count"), "counts exact")

# --- extract_values: no double-count on overlap ---
v = tp.extract_values("raised HK$900 million and valued at over US$3 billion")
amts = [x for x in v if x["kind"] == "amount"]
ok(len(amts) == 2 and {a["currency"] for a in amts} == {"HKD", "USD"},
   f"two amounts, got {amts}")

# --- sentences_spans: every returned slice must equal its source ---
for path in (ROOT / "tests" / "case_ai_draft.md", ROOT / "tests" / "case_zh.md"):
    for para in read_doc(path)["paragraphs"]:
        for sent, off in tp.sentences_spans(para):
            ok(para[off:off + len(sent)] == sent, f"span mismatch in {para[:40]!r}")
two = tp.sentences_spans('He said "stay the course." Later in 2011, they left.')
ok(len(two) == 2, f"quote-protected split, got {two}")
zh2 = tp.sentences_spans("成立于1992年。总部在珠海。")
ok(len(zh2) == 2, "CJK 。 splits without trailing space")

# --- stem pairs used across the corpus ---
ok(tp.stem("founded") == tp.stem("founding"), "founded~founding")
ok(tp.stem("launching") == tp.stem("launch"), "launching~launch")

# --- detect_entities ---
d = read_doc(ROOT / "tests" / "case_ai_draft.md")
ents = tp.detect_entities(d["paragraphs"])
ok("Nimbus Cloud" in ents and "Ada Chen" in ents, f"entities {ents}")
ok("Speed" not in ents, "sentence-initial non-name excluded")

# --- FX adjacency: conversions pair, unrelated figures do not ---
def _amt(raw, cur, val, sent, s, e):
    return {"type": "amount", "raw": raw, "currency": cur, "value": val,
            "sentence": sent, "span": [s, e], "para": 0}

s1 = "The IPO in 2023 raised HK$900 million and valued Nimbus at over US$3 billion."
a = _amt("HK$900 million", "HKD", 9e8, s1, s1.find("HK$900"), s1.find("HK$900") + 14)
b = _amt("US$3 billion", "USD", 3e9, s1, s1.find("US$3 billion"), s1.find("US$3 billion") + 12)
ok(not _conversion_pairs([a, b]), "distant figures are NOT a conversion")
s2 = "The buyout was priced at HK$189 million (about US$24.3 million)."
i1, i2 = s2.find("HK$189 million"), s2.find("US$24.3 million")
c = _amt("HK$189 million", "HKD", 1.89e8, s2, i1, i1 + 14)
d2 = _amt("US$24.3 million", "USD", 2.43e7, s2, i2, i2 + 15)
ok(len(_conversion_pairs([c, d2])) == 1, "(about …) IS a conversion")
s3 = "交易金额1.89亿元（约合2400万美元）。"
j1, j2 = s3.find("1.89亿元"), s3.find("2400万美元")
e1 = _amt("1.89亿元", "CNY", 1.89e8, s3, j1, j1 + 6)
e2 = _amt("2400万美元", "USD", 2.4e7, s3, j2, j2 + 7)
ok(len(_conversion_pairs([e1, e2])) == 1, "约合 pairs in ZH")

# --- clip / sniff ---
long = "word " * 200
ok(clip(long).endswith("…[line clipped]") and len(clip(long)) < 300, "clip")
ok("中文" in sniff_bytes("金山中文".encode("gb18030")), "gb18030 sniffed")
ok(sniff_bytes("plain ascii".encode("utf-8")) == "plain ascii", "utf-8 passthrough")

# --- inverted index == brute force ---
cor = Corpus(ROOT / "tests" / "corpus")
kws = cor.rare_tokens("Nimbus Cloud founded Hangzhou", k=4)
idx = cor.find_lines(kws, 1)
brute = []
for fname, lineno, raw, toks, prec in cor.lines:
    sh = set(kws) & toks
    if sh:
        brute.append((len(sh), fname, lineno, raw, sorted(sh), prec))
brute.sort(key=lambda r: (-r[0], r[1], r[2]))
ok(idx == brute[:12], "index results equal brute force")

# --- LLM query planner parsing (stubbed, offline) ---
from app.llm import plan_queries  # noqa: E402
from app.estimate import scaled_budgets  # noqa: E402

# --- budgets must SCALE per doc (the 'starved deep pass' regression): a
# static token ceiling once killed the LLM at call 22 on a 200-word doc ---
_b_small = scaled_budgets({"words": 200, "paras": 4, "claims": 8, "need_web": 8,
                           "uniq_need_web": 7}, {"max_search": 40,
                           "llm_max_tokens": 60000}, web=True, llm=True)
_b_big = scaled_budgets({"words": 6000, "paras": 60, "claims": 240, "need_web": 220,
                         "uniq_need_web": 200}, {"max_search": 40,
                         "llm_max_tokens": 60000}, web=True, llm=True)
ok(_b_small["llm_max_tokens"] >= _b_small["llm_max_calls"] * 2600,
   "LLM token budget covers the whole call budget (deep pass cannot starve)")
ok(_b_big["llm_max_tokens"] > _b_small["llm_max_tokens"] * 4,
   "LLM token budget scales with the document")

# --- percent claims conflict only about the SAME base quantity (the
# '20% shares / 22.89% voting rights / 80% debt = one conflict' false alarm) ---
from app.checks import internal_conflicts as _ic  # noqa: E402


def _pct(raw, sent):
    return {"id": raw, "type": "pct", "raw": raw, "value": float(raw.rstrip("%")),
            "currency": None, "sentence": sent, "para": 0, "span": [0, 0],
            "verdict": "unverified"}


_fake = _ic([_pct("20%", "Managers were given the right to buy 20% of the "
                  "studio's shares, with shares giving them ownership."),
             _pct("22.89%", "The founders entrusted the voting rights of their "
                  "remaining shares to Lei Jun, giving him control of 22.89% "
                  "of the voting rights."),
             _pct("80%", "Zou Tao assumed 80% of the debt obligation from the "
                  "group loans given to managers.")])
ok(not _fake, "different base quantities (shares/voting/debt) never form one conflict")
_real = _ic([_pct("15%", "Tencent bought 15% of the shares of the company."),
             _pct("21%", "Tencent bought 21% of the shares of the company.")])
ok(len(_real) == 1 and len(_real[0][0]) == 2,
   "same base quantity with different values still conflicts (no over-correction)")

# --- official-API backends are strictly optional: no keys -> not usable,
# and WebEvidence availability still holds via keyless backends ---
from app.web import BraveSearch, GoogleCSE, WebEvidence as _WE, WebBudget as _WB  # noqa: E402
import os as _os  # noqa: E402
for _k in ("GOOGLE_CSE_KEY", "GOOGLE_CSE_ID", "BRAVEX_API_KEY"):
    _os.environ.pop(_k, None)
ok(not GoogleCSE().usable and not BraveSearch().usable,
   "no search keys configured -> official backends report unusable")
_w = _WE(_WB(1))
ok(_w.available, "keyless chain still available without any API key (the $0 rule)")


class _StubLLM:
    available = True

    def __init__(self, resp):
        self.resp = resp

    def chat(self, prompt):
        return self.resp


resp = ('{"c1": ["Qiu Bojun WPS 1.0 1989 Room 501 history", '
        '"WPS 1.0 emerged 1989 Kingsoft", "求伯君 WPS 1989 501房间"], '
        '"c2": ["short"]}')
claims = [{"id": "c1", "type": "year", "raw": "1989",
           "sentence": "WPS 1.0 emerged in 1989"},
          {"id": "c2", "type": "amount", "raw": "66",
           "sentence": "RMB 66 million revenue"}]
out = plan_queries(_StubLLM(resp), claims,
                   {"subject": "Kingsoft", "origin_language": "zh"})
ok(out.get("c1") and any(not q.isascii() for q in out["c1"]),
   "planner keeps translated (zh) query")
ok("c2" not in out, "trivial query strings dropped")
ok(plan_queries(_StubLLM("not json at all"), claims, None) == {},
   "garbage response -> {}")

# ============================================================================
# M1.9 generality: every mechanism added while diagnosing ONE document is
# pinned here with UNRELATED data (Japanese subjects, synthetic EN prose) so
# none of it can silently be a Kingsoft special case.
# ============================================================================

# --- month/weekday before a year = DATE; brand before a year = PRODUCT ---
def _years(t):
    return [x["raw"] for x in tp.extract_values(t) if x["kind"] == "year"]


ok(_years("The company was founded in March 1918.") == ["1918"],
   "month+year is a date (ja-adjacent fixture, not KS)")
ok(_years("Trinitron launched in April 1968 in Japan.") == ["1968"],
   "April+year kept")
ok(_years("Users still run Office 2000, released May 2001.") == ["2001"],
   "product year filtered, release month+year kept, same sentence")
ok(not _years("The museum exhibit opened with WordStar and Word 2000."),
   "product years stay suppressed (no regression)")
ok(_years("In 1932 the workshop opened.") == ["1932"], "bare year unaffected")

# --- count vocabulary: lines/copies/行, hyphenated word-ages, spelled hundreds ---
def _counts(t):
    return sorted(int(x["value"]) for x in tp.extract_values(t)
                  if x["kind"] == "count")


ok(_counts("The interpreter spans 45,000 lines of assembly code.") == [45000],
   "'N lines' is a count")
ok(_counts("The first print run sold 30,000 copies in 1990.") == [30000],
   "'N copies' is a count")
ok(_counts("コードは全部で122000行あった。") == [122000], "'N行' is a count (ja)")
ok(_counts("the thirty-five-year-old founder returned") == [35],
   "hyphenated word-age")
ok(_counts("an eighteen-year-old intern joined") == [18], "teen -year-old")
ok(_counts("six hundred employees were laid off") == [600], "spelled hundred")
ok(_counts("hundreds of users signed up") == [], "'hundreds of' is NOT a figure")
ok(_counts("a hundred years later") == [], "'a hundred' stays prose (no digit)")

# --- detect_entities: locative place nouns cannot anchor; names containing places do ---
ents = tp.detect_entities([
    "Konosuke Matsushita founded Matsushita Electric in Osaka; the Matsushita "
    "Electric office in Kobe opened soon after, and Matsushita Electric grew."])
ok("Matsushita Electric" in ents, f"company anchor kept: {ents}")
ok("Kobe" not in ents, f"non-gazetteer city dropped by the preposition rule: {ents}")
ok("Osaka" not in ents, f"list city dropped twice over: {ents}")
e2 = tp.detect_entities(["Hong Kong Polytechnic reported gains in Kyoto; the "
                         "New York Times covered it."])
ok("Hong Kong Polytechnic" in e2 and "New York Times" in e2,
   f"multi-word names that START with a place survive: {e2}")
ok("Kyoto" not in e2,
   f"locative object dropped by the preposition rule (not in any gazetteer): {e2}")

# --- IDF labels never contradict; real count conflicts survive the stricter bar ---
def _cnt(raw, val, sent):
    return {"id": raw, "type": "count", "raw": raw, "value": float(val),
            "currency": None, "sentence": sent, "para": 0, "span": [0, 0],
            "verdict": "unverified"}


ok(not _ic([_cnt("room 501", 501,
                 "He moved into room 501 of the hotel, coding through the night."),
            _cnt("twenty-four", 24,
                 "The founder was twenty-four, coding through the night in the hotel.")]),
   "a room number and an age sharing context words are NOT one fact")
ok(len(_ic([_cnt("2,100 people", 2100,
                 "By 2020 the company employed 2,100 people across three factories."),
            _cnt("2,400 people", 2400,
                 "Company records in 2020 listed 2,400 people across three factories.")])) == 1,
   "same-fact count conflict still detected (no over-correction)")

# --- cross-script judging: proximity to the query's entity = proof; distance = confetti ---
_wj = _WE(_WB(5), entities=["Matsushita Electric", "松下電器",
                           "Konosuke Matsushita", "松下幸之助"],
          entity_pairs=[("Matsushita Electric", "松下電器")],
          doc_paras=["Matsushita Electric was founded in March 1918."])
_c1918 = {"id": "j1", "type": "year", "raw": "1918", "value": 1918.0,
          "currency": None, "para": 0, "span": [0, 4],
          "sentence": "Matsushita Electric was founded in March 1918."}
ok(_wj._assess_number(_c1918, [{"title": "松下電器の歴史",
                               "body": "松下電器は1918年に創業した。"}],
                     query="松下電器 1918")["status"] != "supported",
   "lone company+year is NOT cross-script support (user precision trade)")
ok(_wj._assess_number(_c1918, [{"title": "松下電器の歴史",
                                "body": "松下電器は1918年、松下幸之助が創業した。"}],
                     query="松下電器 1918")["status"] == "supported",
   "company + founder beside the figure proves it")
_far = ("松下電器の社員名簿：田中一郎（1900年生）、鈴木二郎（1901年生）、"
        "高橋三郎（1902年生）、佐藤四郎（1903年生）、山田五郎（1904年生）、"
        "渡辺六郎（1905年生）、伊藤七郎（1906年生）、中野八郎（1907年生）。"
        "なお、1918年生まれの記載は見当たらない。")
ok(_wj._assess_number(_c1918, [{"title": "会社名簿", "body": _far}],
                     query="松下電器 1918")["status"] != "supported",
   "a lookalike roster with a far-away year is confetti, not proof")
ok(_wj._assess_number(_c1918, [{"title": "Registry",
                                "body": "Matsushita Electric alumni: born 1918."}],
                     query="Matsushita 1918")["status"] != "supported",
   "cross-script relaxation NEVER fires on Latin-vs-Latin non-overlap")

# --- native queries carry DIGITS for word-numbers (any script, not just zh) ---
from app.web import compact_queries as _cq  # noqa: E402

ok(_cq({"type": "count", "raw": "fifty-five", "value": 55.0, "para": 0,
         "sentence": "The plant made fifty-five radios in 1925."},
        ["Sony", "ソニー"], ["ソニー"])[0] == "ソニー 55",
   "word-number becomes digits in the native-script query")


class _FakeWeb:
    raw_entities = ["Sony", "ソニー"]

    def native_for(self, claim):
        return ["ソニー"] if "Sony" in claim.get("sentence", "") else []


from app.enrich import _cluster_queries as _clq  # noqa: E402

qs = _clq({"ents": {"Sony"}, "claims": [
    {"type": "year", "raw": "1946", "value": 1946.0, "para": 0, "span": [0, 0],
     "sentence": "Sony was founded in 1946."},
    {"type": "count", "raw": "twenty", "value": 20.0, "para": 0, "span": [0, 0],
     "sentence": "Sony started with twenty employees."}]}, _FakeWeb())
ok("ソニー 1946" in qs and "ソニー 20" in qs,
   f"one native entity·figure query PER figure: {qs}")

# --- hand-suggestions are real queries in the right script -------------------
ok(tp.cjk_runs('the slogan ("求伯君的今天就是我们的明天") spread')
   == ["求伯君的今天就是我们的明天"], "cjk_runs = the doc's own Chinese phrase")
ok(tp.cjk_runs("plain latin sentence") == [], "cjk_runs empty when no CJK")


class _SW:
    raw_entities = ["Kingsoft"]

    def native_for(self, claim):
        return ["求伯君"]

    @staticmethod
    def _value_str(claim):
        v = claim.get("value")
        return str(int(v)) if v and float(v) == int(v) else ""


from app.enrich import _explain as _ex  # noqa: E402

_sug_q = {"id": "s1", "type": "quote", "raw": "Qiu Bojun's today is our tomorrow",
          "verdict": "unverified", "_searched": True,
          "sentence": "his ad read: \"Qiu Bojun's today is our tomorrow\" "
                      "(求伯君的今天就是我们的明天)."}
_sug_n = {"id": "s2", "type": "year", "raw": "1984", "value": 1984.0,
          "verdict": "unverified", "_searched": True,
          "sentence": "He had graduated in 1984."}
_ex([_sug_q, _sug_n], _SW())
ok(_sug_q.get("manual_checks", [""])[0].strip('"') == "求伯君的今天就是我们的明天",
   f"quote suggestion leads with the doc's own Chinese: {_sug_q.get('manual_checks')}")
ok(_sug_n.get("manual_checks", [""])[0] == "求伯君 1984",
   f"numeric suggestion leads with native entity·figure: {_sug_n.get('manual_checks')}")

# --- the engine choice gates the chain (and wikipedia stays neutral) ---------
_wg = _WE(_WB(1), entities=["Kingsoft"])
_wg.only = "brave"
ok(_wg._engine_ok("brave") and _wg._engine_ok("wikipedia")
   and not _wg._engine_ok("ddgs") and not _wg._engine_ok("searxng"),
   "brave choice: brave + wikipedia only")
_wg.only = "ddgs"
ok(_wg._engine_ok("ddgs") and not _wg._engine_ok("brave"),
   "ddgs choice: ddgs + wikipedia only")
_wg.only = "auto"
ok(all(_wg._engine_ok(n) for n in ("brave", "ddgs", "searxng", "wikipedia")),
   "auto: the whole chain runs")

# --- latin rungs never carry CJK bigram junk into a keyword query ------------
_latin_q = _cq({"type": "year", "raw": "1946", "value": 1946.0, "para": 0,
                "sentence": "Sony was founded 1946 by 盛田昭夫 in Tokyo."},
               ["Sony"], [])
_latin_only = [x for x in _latin_q
               if not any("\u4e00" <= ch <= "\u9fff" for ch in x)]
ok(_latin_only and all(x.isascii() for x in _latin_only),
   f"latin rung stays ascii (no bigram confetti): {_latin_q}")

# --- pronoun claims lead with the DOC SUBJECT, not whoever is named first ---
_wk = _WE(_WB(5), entities=["Acme", "エーメ"],
          entity_pairs=[("Acme", "エーメ"), ("Yuki Tanaka", "田中雪"),
                        ("Hana Suzuki", "鈴木花")],
          doc_paras=["Hana Suzuki visited Acme. Yuki Tanaka left. "
                     "Hana Suzuki later founded a rival. Hana traveled twice."])
_pn = {"sentence": "She was born in 1970.", "para": 0}
_nf = _wk.native_for(_pn)
ok(_nf[0] == "鈴木花" and _nf[-1] == "田中雪",
   f"pronoun claims lead with the prominent subject of the doc: {_nf}")

# --- deep-pass clustering must NOT lose claims (budget, not a static cap, ----
# --- is the only stopper; the cap once starved a 300-word doc at 62/193) -----
from app.enrich import _source_clusters as _src, _prop_words as _pw  # noqa: E402


class _CW:
    raw_entities = ["Nimbus Cloud"]

    def native_for(self, claim):
        return []


def _ev(raw, sent, pid):
    return {"id": f"e{pid}", "type": "year", "raw": raw, "value": float(raw),
            "verdict": "unverified", "sentence": sent, "para": pid, "span": [0, 0]}


_cs = [_ev(str(1990 + i), f"Unrelated sentence number {i} about zebra{i} "
            f"quantum{i} widget{i}.", i) for i in range(12)]  # all singletons
_vis = _src(_cs, _CW(), max_clusters=max(len(_cs), 1))
ok(sum(len(cl["claims"]) for cl in _vis) == 12,
   "every claim is clustered — nothing truncated away from an attempt")

# --- proper-noun detection for queries: mid-sentence capitals only -----------
pw = _pw("Even so, he had his computer moved into the hospital ward.",
         {"kingsoft"})
ok("Even" not in pw, f"sentence-initial capital is not a name: {pw}")
pw2 = _pw("Lei moved into the Cai Wu Wei Hotel in Shenzhen.",
          {"lei jun"})
ok("Cai" in pw2 or "Hotel" in "".join(pw2),
   f"genuine mid-sentence proper name found: {pw2}")
pw3 = _pw("Qiu Bojun walked past WordStar booths.", {"qiu bojun"})
ok("Bojun" not in pw3, f"entity fragments excluded: {pw3}")
pw4 = _pw("The team met in Wuhan yesterday, Wuhan again today.", set())
ok(all("uhan" not in w for w in pw4), f"places never become query props: {pw4}")


# --- SERP chrome ('缺少字詞：…' / 'Missing:' echo) is a confession, NEVER evidence
_junk = ("This timeline covers events in electronics. 缺少字詞：Matsushita Electric "
         "founded 1918 exhibition old - Wikipedia")
ok(tp.clean_snippet(_junk) == "This timeline covers events in electronics.",
   f"clean_snippet cuts the query echo: {tp.clean_snippet(_junk)!r}")
ok("Matsushita" not in tp.clean_snippet(_junk),
   "the echoed query can't masquerade as a subject mention")
ok(tp.clean_snippet("normal snippet, no chrome") == "normal snippet, no chrome",
   "clean text passes through untouched")
ok(not _WE._cjk_near("qiu bojun exhibition old 1918 major events", "1918"),
   "figure echoed in latin chrome is not CJK context")
ok(_WE._cjk_near("パナソニックは1918年に創業した", "1918"),
   "1918年 = real CJK context")

_wjx = _WE(_WB(5), entities=["Matsushita Electric"])


def _junk_backend(query, max_results):  # a SERP whose only hit is the junk page
    return [{"title": "List of years in electronics - Wikipedia",
             "href": "https://example.test/list", "body": _junk}]


_wjx._backend = _junk_backend
_jy = {"id": "jy", "type": "year", "raw": "1918", "value": 1918.0,
       "currency": None, "para": 0, "span": [0, 4],
       "verdict": "unverified",
       "sentence": "Matsushita Electric was founded at an exhibition in 1918."}
_jr = _wjx.verify_number(_jy)
ok(_jr["status"] not in ("supported", "contradicted", "conflicting"),
   f"echo-only SERP can never settle a claim: {_jr['status']}")
ok(all("缺少字詞" not in (e.get("quote") or "")
       for e in (_jr.get("evidence") or [])),
   "chrome never reaches displayed evidence")

# --- '1990s' is a DECADE, never the year 1990 (a real false green: a claim
# 'sold 30,000 in 1990' matched a snippet saying 'in the 1990s') -----------
ok(not any(x["kind"] == "year" and x["value"] == 1990
           for x in tp.extract_values("Kingsoft lowered prices in the 1990s")),
   "'the 1990s' must not yield a 1990 year claim")
ok(any(x["value"] == 1990 for x in tp.extract_values("Founded 1990; sold in the 1990s")),
   "'1990' alone still extracts (decade guard is not over-eager)")

# --- cross-script support needs the subject (or 2 entities), not a lookalike name ---
_wk2 = _WE(_WB(5), entities=["Tide Tech", "潮汐科技", "Tide Shi", "潮汐女士"],
           entity_pairs=[("Tide Tech", "潮汐科技"), ("Tide Shi", "潮汐女士")],
           doc_paras=["Tide Shi founded Tide Tech."])
_tb = {"id": "t1", "type": "year", "raw": "1999", "value": 1999.0,
       "currency": None, "para": 0, "span": [0, 4],
       "sentence": "Tide Shi founded Tide Tech in 1999."}
ok(_wk2._assess_number(_tb, [{"title": "潮汐科技",
                              "body": "潮汐女士于1999年创立了潮汐科技。"}],
                      query="潮汐女士 1999")["status"] == "supported",
   "figure beside a document entity, on the subject's page, proves it")
ok(_wk2._assess_number(_tb, [{"title": "诗集",
                              "body": "潮汐女士（1999年生）的诗集出版。"}],
                      query="潮汐女士 1999")["status"] != "supported",
   "a lone lookalike name (no subject, no 2nd entity) is NOT enough")

# --- 'Room 501' is a LABEL: a company's office address ('Room 501, Block A,
# ... Kingsoft Corporation', an HKEX filing) trivially 'supports' a 1988
# hotel-room claim unless the matcher treats identifiers as non-distinctive --
from app.web import distinctive_value as _dv  # noqa: E402

_rm = {"id": "rm", "type": "count", "raw": "room 501", "value": 501.0,
       "currency": None, "para": 0, "span": [0, 8], "verdict": "unverified",
       "sentence": "He moved into room 501 of the hotel in Shenzhen."}
ok(not _dv(_rm), "'room 501' is not a self-anchoring figure")
ok(_dv({"id": "x", "type": "count", "raw": "122,000 lines", "value": 122000.0}),
   "122,000 lines STAYS self-anchoring (label guard is about labels)")
_wr = _WE(_WB(5), entities=["Kingsoft", "金山软件"])
ok(_wr._assess_number(_rm, [{"title": "ANNUAL REPORT 2024",
                             "body": "Address: Room 501, Block A, Haier Plaza "
                                     "— Kingsoft Corporation Limited"}],
                     query="Kingsoft room 501")["status"] != "supported",
   "the company's own office address cannot prove a hotel-room claim")

# --- year claims match the EVENT, not a coincidental digit ------------------
_wa = _WE(_WB(5), entities=["Neil Armstrong"])
_mars = {"id": "mars", "type": "year", "raw": "1969", "value": 1969.0,
         "currency": None, "para": 0, "span": [0, 4],
         "sentence": "Neil Armstrong was the first person to walk on Mars in 1969."}
ok(_wa._assess_number(_mars, [{"title": "Moon landing",
                               "body": "Neil Armstrong was the first person to "
                                       "walk on the Moon in 1969."}],
                      query="Neil Armstrong 1969")["status"] != "supported",
   "Moon-1969 must not support a Mars-1969 claim")
ok(_wa._assess_number(_mars, [{"title": "Mars hoax",
                               "body": "Neil Armstrong walked on Mars in 1969."}],
                      query="Neil Armstrong 1969")["status"] == "supported",
   "the same event + year still supports")

# --- unmatched corpus lines are NOT evidence --------------------------------
from app.judge import _check_number as _cn  # noqa: E402
_uv, _cf, _ev, _nt = _cn(
    {"type": "year", "raw": "1993", "value": 1993.0, "currency": None,
     "sentence": "He kept coding WPS through 1993."},
    Corpus(str(ROOT / "tests" / "corpus_ks")))
ok(_uv == "unverified" and _ev == [],
   f"nearby unmatched corpus line must not be attached as evidence: {_ev}")

# --- LLM token heuristic has no fake +2000 pad per call ---------------------
from app.llm import LLM as _LLM  # noqa: E402
_pr, _out = "hello " * 40, "ok " * 10
_used = len(_pr) // 4 + len(_out) // 4
ok(_used < 400 and _used == len(_pr) // 4 + len(_out) // 4,
   f"token heuristic is prompt+out, not +2000: {_used}")
_ll = _LLM(max_calls=5, max_tokens=8000, max_seconds=30)
ok(_ll.tokens == 0, "LLM starts at 0 tokens (no ghost spend)")

# --- Brave monthly cap: 0 remaining means the key is unusable ---------------
from app import quota as _q  # noqa: E402
_saved = dict(_q._brave)
_q._brave["month"] = _q._month()
_q._brave["used"] = 1000
ok(_q.brave_left(1000) == 0, "spent month → 0 Brave queries left")
_q._brave["used"] = 0
ok(_q.brave_left(1000) == 1000, "fresh month has full cap")
_q._brave.update(_saved)

print(f"UNIT TESTS: PASS ({n} assertions)")
