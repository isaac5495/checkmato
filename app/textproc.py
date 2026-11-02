import re
import unicodedata

CJK = re.compile(r"[\u4e00-\u9fff]")

STOP = {
    "a", "an", "the", "is", "was", "were", "are", "been", "being", "be", "in", "on",
    "at", "by", "for", "to", "of", "and", "or", "said", "says", "that", "this", "it",
    "its", "with", "from", "as", "after", "before", "during", "over", "under", "more",
    "than", "then", "them", "they", "their", "there", "here", "when", "where", "which",
    "who", "whom", "whose", "what", "how", "also", "into", "about", "per", "up",
    "he", "his", "her", "hers", "him", "even", "only", "just", "own", "much",
    # never search keywords, only sentence connectives (they polluted
    # hand-suggestions: "Kingsoft even his computer moved hospital")
    "down", "out", "off", "such", "most", "very", "not", "no", "nor", "so", "if", "but",
    "while", "because", "though", "although", "between", "among", "across", "through",
    "company", "companies", "group", "firm", "business", "year", "years", "one", "two",
    "three", "four", "five", "six", "seven", "eight", "nine", "ten", "first", "second",
    "third", "new", "old", "each", "every", "all", "any", "both", "had", "has", "have",
    "did", "does", "do", "would", "could", "should", "will", "shall", "may", "might",
    "must", "can",     "case", "study", "section", "chapter", "page", "footnote",
    # unit/currency words are never subject keywords (they made amounts collide)
    "million", "billion", "trillion", "yuan", "dollar", "dollars", "cent",
    "us", "hk", "rmb", "cny", "eur", "gbp", "roughly",
    "nearly", "around", "almost", "exceeding", "crossed", "reached", "reach",
    "的了在是我有和就不人这上他她它们与或为很个无之其已所",
}

CUR_MAP = {"US$": "USD", "$": "USD", "HK$": "HKD", "RMB": "CNY", "¥": "CNY",
           "€": "EUR", "£": "GBP", "yuan": "CNY", "元": "CNY", "美元": "USD",
           "港元": "HKD", "DKK": "DKK", "SEK": "SEK", "JPY": "JPY",
           "CAD": "CAD", "AUD": "AUD"}

UNIT_MAP = {"trillion": 1e12, "billion": 1e9, "million": 1e6,
            "亿": 1e8, "万": 1e4, "千": 1e3}

CUR_PREFIX = r"(?:US\$|HK\$|RMB|¥|\$|€|£|DKK|SEK|JPY|CAD|AUD)"
AMT_RE = re.compile(CUR_PREFIX + r"\s*([\d][\d,]*(?:\.\d+)?)\s*(billion|million|trillion|亿|万|千)?", re.I)
AMT2_RE = re.compile(r"([\d][\d,]*(?:\.\d+)?)\s*(billion|million|trillion|亿|万|千)\s*(yuan|元|美元|港元|RMB)?", re.I)
PCT_RE = re.compile(r"([\d][\d,]*(?:\.\d+)?)\s*(?:%|百分之)")
COUNT_RE = re.compile(r"(?<![\dA-Za-z.,%])([\d][\d,]*)\s*-?\s*(?:employees|people|person|persons|staff|users|offices|lines|copies|downloads|units|items|pieces|pages|characters|volumes|subscribers|members|visitors|years?\s+old|year-old|人|名|位|岁|行|本|册|台|部|份)(?![0-9A-Za-z])", re.I)
ROOM_RE = re.compile(r"\b(?:room|suite|ward|apartment|apt\.?)\s+(\d{1,4})\b", re.I)
# labels, not quantities: a room/floor number can never "contradict" an age
IDF_LABEL = re.compile(r"(?i)\b(room|suite|ward|apartment|apt|floor|unit)\b")
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
          "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS_WORDS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_UNITS_WORDS = "one|two|three|four|five|six|seven|eight|nine"
_TEEN_WORDS = "ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
# spelled-out ages/counts ONLY after an explicit age context — bare number
# words would explode with false claims ("was one of the first...")
WORD_NUM_RE = re.compile(
    r"\b(?:was|were|is|aged|at the age of|remained|still)\s+(?:only\s+)?"
    r"((?:" + _TENS_WORDS + r")(?:-(?:" + _UNITS_WORDS + r"))?|" + _TEEN_WORDS + r")\b",
    re.I)
# "a twenty-two-year-old Lei Jun": the hyphenated -year-old tail is itself an
# explicit age signal — no verb needed, no false-positive risk
WORD_AGE_RE = re.compile(
    r"\b((?:" + _TENS_WORDS + r")(?:-(?:" + _UNITS_WORDS + r"))?|" + _TEEN_WORDS +
    r")-year-old\b", re.I)
# "four hundred days": spelled hundreds are deterministic, bounded values
WORD_HUNDREDS_RE = re.compile(
    r"\b(" + _UNITS_WORDS + r"|ten)\s+hundred\b", re.I)
# 'the 1990s' is a DECADE, never a year claim — matching '1990' inside it
# was a false green the auditor caught ('sold 60,000 copies in the 1990s')
YEAR_RE = re.compile(r"(?<![\d.,%])((?:19|20)\d{2})(?![\d%]|'?[sS]\b)")
QUOTE_RE = re.compile(r"[\"“「『]([^\"“”「」『』]{10,})[\"”」』]")
PLACEHOLDER_RES = [
    re.compile(r"\[\?[^\]]*\?\]"),
    re.compile(r"\[\?[^\]]*\]"),
    re.compile(r"\b(?:TBD|TODO)\b", re.I),
    re.compile(r"\bxxx+\b", re.I),
    re.compile(r"\[insert[^\]]*\]", re.I),
]
URL_RE = re.compile(r"https?://[^\s\)\]，。]+")

# SERP chrome = search-engine UI text that leaks into snippet bodies. The
# '缺少字詞：X Y Z' / 'Missing: X Y Z' line ECHOES THE QUERY into the snippet
# as a CONFESSION that the page lacks those terms — left in, the echo makes
# the page 'name the entity and carry the figure' and junk pages become
# 'evidence' for claims they do not mention at all.
SERP_CHROME = re.compile(
    r"缺[少失]?字|missing\s*(?:words?)?\s*[:：]|did you mean|"
    r"one universal result|view as google cache|people also (?:ask|search)",
    re.I)


def clean_snippet(text):
    """Truncate a SERP snippet where the engine's UI chrome begins."""
    if not text:
        return ""
    m = SERP_CHROME.search(text)
    if m:
        text = text[:m.start()]
    return re.sub(r"\s{2,}", " ", text).strip()

GENERIC_PLACES = {  # 2nd line of defense: subject-position countries/capitals
    "china", "japan", "korea", "america", "usa", "europe", "india",
    "russia", "england", "london", "paris", "moscow", "seoul", "tokyo",
    "beijing", "shanghai", "shenzhen", "wuhan", "taiwan", "singapore",
}
# Generic syntactic guard (1st line): a capitalized noun right after a
# locative preposition is a place ("founded ... in Osaka", "moved to Wuhan",
# "orders from Reuter") — no world gazetteer can be complete, but this
# covers EVERY city/village the document mentions incidentally. Bare
# surnames caught by the same rule (asked Qiu to…) are exactly the weak
# anchors that let lookalike pages "prove" numbers.
_LOC_PREP = {"in", "at", "from", "to", "near", "around", "across"}
_PREP_BEFORE = re.compile(r"([a-z]+)[\s,]*$")

WORD_RE = re.compile(r"[a-z0-9]+")

_CC = None


def _t2s(s):
    """Traditional->Simplified normalization (F9) so 主人/主人 等 match across
    script. No-op if OpenCC is absent."""
    global _CC
    if not CJK.search(s):
        return s
    if _CC is None:
        try:
            from opencc import OpenCC
            _CC = OpenCC("t2s")
        except Exception:
            _CC = False
    return _CC.convert(s) if _CC else s


def has_cjk(s):
    return bool(CJK.search(s))


_WORDISH = re.compile(r"[A-Za-z0-9$%\u2019'\.,-]+")


def count_words(paragraphs):
    """MS-Word-compatible count: each latin/digit run = 1 word, each CJK
    CHARACTER = 1 word (Word's own rule for Chinese/Japanese/Korean)."""
    return sum(len(_WORDISH.findall(p)) + len(CJK.findall(p)) for p in paragraphs)


def normalize(s):
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = _t2s(s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff%$.]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def stem(t):
    if len(t) <= 4:
        return t
    for suf in ("ing", "ed", "es", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            return t[: len(t) - len(suf)]
    return t


def _cjk_tokens(run):
    if len(run) == 1:
        return [run]
    return [run[i : i + 2] for i in range(len(run) - 1)]


def tokens(text):
    """Matching tokens: stemmed latin words + CJK bigrams (deterministic, no NLP)."""
    norm = normalize(text)
    out = set()
    for m in re.finditer(r"[a-z0-9]+", norm):
        t = m.group()
        out.add(stem(t) if not t.isdigit() else t)
    for m in re.finditer(r"[\u4e00-\u9fff]+", norm):
        out.update(_cjk_tokens(m.group()))
    return out


def rare_raw_tokens(text, k=6):
    """Subject keywords not filtered by corpus existence (for internal consistency)."""
    ts = [t for t in tokens(text) if t not in STOP and not t.isdigit() and len(t) > 1]
    return sorted(set(ts))


def cjk_runs(text, min_len=4):
    """Whole CJK character runs (min_len+) in reading order: the document's
    OWN native-script phrases (a slogan quoted beside its translation) — the
    only Chinese a Latin document supplies without machine translation, and
    the exact string real sources carry."""
    return re.findall(r"[\u4e00-\u9fff]{%d,}" % min_len, text or "")


def rare_phrase(text, k=5):
    """Distinctive words IN READING ORDER (not sorted): produces human-like
    search queries and hand-search suggestions. 'folk hero name screen' reads
    like a query; 'appear bojun close folk hero' does not."""
    seen, out = set(), []
    for w in re.findall(r"[A-Za-z0-9’'-]+|[\u3400-\u9fff]+", text):
        lw = w.lower().strip("'-.")
        if len(lw) < 3 or lw.isdigit() or lw in STOP:
            continue
        if lw not in seen:
            seen.add(lw)
            out.append(lw)
        if len(out) >= k:
            break
    return " ".join(out)


_PUNCT_SENT_END = ".!?。！？；;"
_QUOTE_SPAN = re.compile(r"[\"“「『][^\"”」』\n]{10,}[\"”」』]")


def sentences_spans(text):
    """[(sentence, char_start_in_text)] — split without breaking inside quoted
    passages. A terminator splits when followed by whitespace/end; a closing
    quote also ends a sentence when the next word is capitalised/CJK."""
    spans = [(m.start() + 1, m.end() - 1) for m in _QUOTE_SPAN.finditer(text)]
    right_closers = {'\u201d', '\u300d', '\u300f'}  # ” 」 』 (directional quotes)

    def protected(i):
        return any(a <= i < b for a, b in spans)

    def prev_nonspace(i):
        k = i - 1
        while k >= 0 and text[k].isspace():
            k -= 1
        return text[k] if k >= 0 else ""

    def new_word_after(j):
        while j < len(text) and text[j].isspace():
            j += 1
        if j >= len(text):
            return True
        c = text[j]
        return c.isupper() or c.isdigit() or bool(CJK.match(c))

    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        ch = text[i]
        boundary = False
        if not protected(i):
            if ch in _PUNCT_SENT_END:
                boundary = (ch in "。！？；" or i + 1 >= n or text[i + 1].isspace())
            elif ch in right_closers:
                boundary = new_word_after(i + 1)
            elif ch == '"' and prev_nonspace(i) in _PUNCT_SENT_END:
                # straight quote closing a quoted sentence (opening quotes are
                # not preceded by a terminator) — only then is it a boundary
                boundary = new_word_after(i + 1)
        if boundary:
            raw = text[start:i + 1]
            seg = raw.strip()
            if seg:
                out.append((seg, start + raw.index(seg)))
            start = i + 1
            while start < n and text[start].isspace():
                start += 1
            i = start
            continue
        i += 1
    raw = text[start:]
    tail = raw.strip()
    if tail:
        out.append((tail, start + raw.index(tail)))
    return out


def sentences(text):
    return [s for s, _ in sentences_spans(text)]


def parse_amount_text(s):
    """Return (value, currency) for a raw amount string like 'US$120 million'."""
    s = s.strip()
    currency = None
    m = re.match(CUR_PREFIX, s)
    if m:
        currency = CUR_MAP.get(m.group(0), m.group(0))
    m2 = re.search(r"(yuan|元|美元|港元|RMB)\s*$", s)
    if m2:
        currency = CUR_MAP.get(m2.group(1), m2.group(1))
    num = re.search(r"[\d][\d,]*(?:\.\d+)?", s)
    if not num:
        return None, currency
    val = float(num.group(0).replace(",", ""))
    low = s.lower()
    for u, mult in UNIT_MAP.items():
        if u in low:
            val *= mult
            break
    return val, currency


_YEAR_PRE_WORD = re.compile(r"([A-Za-z][A-Za-z0-9.'\-]*)\s*$")
_DATE_PRE_WORDS = {
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august", "sep", "sept",
    "september", "oct", "october", "nov", "november", "dec", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "spring", "summer", "autumn", "winter", "q1", "q2", "q3", "q4",
}


def _is_product_year(text, m):
    """'WPS 2000', 'Office 2000', 'Server 2003': a four-digit year glued to a
    capitalized name is a PRODUCT VERSION, not a date. Checking it as a year
    floods the report with unsearchable noise claims (each burning budget).
    Month/weekday names are dates ("in September 1989"), never brands."""
    pre = text[:m.start()]
    w = _YEAR_PRE_WORD.search(pre)
    if not w:
        return False
    word = w.group(1)
    if word.lower().rstrip(".") in _DATE_PRE_WORDS:
        return False
    return word[0].isupper() and bool(pre[:w.start(1)].strip())


def _word_num_val(w):
    parts = w.split("-")
    return (_TENS.get(parts[0], 0)
            + (_UNITS.get(parts[-1], 0) if len(parts) > 1 else _UNITS.get(w, 0)))


def extract_values(text):
    """All machine-readable values in a text: years, percents, counts, amounts.

    Returns list of dicts {kind, value, currency, raw, start, end}.
    Overlapping matches are resolved longest-first.
    """
    # "122 000" is one number, not 122 and 000. Replace the separator with a
    # comma (same length, so offsets stay valid) instead of dropping it.
    text = re.sub(r"(?<=\d)[ \u00a0](?=\d{3}(?!\d))", ",", text)
    found = []
    for m in YEAR_RE.finditer(text):
        if _is_product_year(text, m):
            continue
        found.append({"kind": "year", "value": float(m.group(1)), "currency": None,
                      "raw": m.group(0), "start": m.start(), "end": m.end()})
    for m in PCT_RE.finditer(text):
        val = float(m.group(1).replace(",", ""))
        found.append({"kind": "pct", "value": val, "currency": None,
                      "raw": m.group(0), "start": m.start(), "end": m.end()})
    for m in COUNT_RE.finditer(text):
        val = float(m.group(1).replace(",", ""))
        found.append({"kind": "count", "value": val, "currency": None,
                      "raw": m.group(0), "start": m.start(), "end": m.end()})
    for m in ROOM_RE.finditer(text):
        found.append({"kind": "count", "value": float(m.group(1)), "currency": None,
                      "raw": m.group(0), "start": m.start(), "end": m.end()})
    for m in WORD_NUM_RE.finditer(text):
        w = m.group(1).lower()
        val = _word_num_val(w)
        if not val:
            continue
        found.append({"kind": "count", "value": float(val), "currency": None,
                      "raw": m.group(1), "start": m.start(1), "end": m.end(1)})
    for m in WORD_AGE_RE.finditer(text):
        val = _word_num_val(m.group(1).lower())
        if not val:
            continue
        found.append({"kind": "count", "value": float(val), "currency": None,
                      "raw": m.group(0), "start": m.start(0), "end": m.end(0)})
    for m in WORD_HUNDREDS_RE.finditer(text):
        val = _UNITS.get(m.group(1).lower(), 0) * 100
        if not val:
            continue
        found.append({"kind": "count", "value": float(val), "currency": None,
                      "raw": m.group(0), "start": m.start(0), "end": m.end(0)})
    for rx in (AMT_RE, AMT2_RE):
        for m in rx.finditer(text):
            val, cur = parse_amount_text(m.group(0))
            if val is None:
                continue
            if rx is AMT2_RE and not (m.group(3) or "").strip():
                # bare "2 million"/"6600万" with NO currency suffix: an amount
                # only with money context (销售额/revenue/raised...); otherwise
                # it's a quantity ("2 million COPIES") — misclassifying it as
                # an amount manufactures fake contradictions against revenue
                after = text[m.end():m.end() + 20].lower()
                around = text[max(0, m.start() - 25):m.end() + 8].lower()
                if re.search(r"\b(copies|copy|sets|units|lines|例|套|册|部)\b", after):
                    found.append({"kind": "count", "value": val, "currency": None,
                                  "raw": m.group(0), "start": m.start(), "end": m.end()})
                    continue
                if not re.search(
                        r"销售额|销售|收入|营收|市值|价值|金额|赚|售价|revenue|sales|"
                        r"earned|worth|raised|funding|cost|price|budget", around):
                    found.append({"kind": "count", "value": val, "currency": None,
                                  "raw": m.group(0), "start": m.start(), "end": m.end()})
                    continue
                if cur is None and re.search(r"(亿|万|千)", m.group(0)):
                    cur = "CNY"  # Chinese convention: 销售额逾6600万 ⇒ CNY
            found.append({"kind": "amount", "value": val, "currency": cur,
                          "raw": m.group(0), "start": m.start(), "end": m.end()})
    found.sort(key=lambda d: (d["start"], -d["end"]))
    kept = []
    last_end = -1
    for f in found:
        if f["start"] >= last_end:
            kept.append(f)
            last_end = f["end"]
    return kept


def values_equal(a, b, kind=None):
    if a is None or b is None:
        return False
    if kind == "year" or (a < 10000 and b < 10000 and kind != "pct"):
        return a == b
    tol = max(1e-9, 0.005 * max(abs(a), abs(b)))
    return abs(a - b) <= tol


def currency_compatible(c1, c2):
    return c1 is None or c2 is None or c1 == c2


CAP_GRAM = re.compile(r"\b([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,3})\b")
_HEAD_SKIP = {"the", "a", "an", "this", "that", "these", "those", "in", "on", "at",
              "for", "and", "but", "if", "when", "while", "many", "some", "all",
              "both", "however", "moreover", "therefore", "as", "it", "its"}


def detect_entities(paragraphs, max_n=6):
    """Named entities: capitalized n-grams, accepted when seen mid-sentence or
    repeated (rejects one-off sentence-initial capitals like 'Speed' or 'This').
    Used to anchor web evidence: a snippet that never names one of them is
    irrelevant to this document."""
    stats = {}  # cand -> [count, mid_sentence_count, strong_name_count]

    def note(cand, mid, strong):
        s = stats.setdefault(cand, [0, 0, 0])
        s[0] += 1
        s[1] += mid
        s[2] += strong

    for p in paragraphs:
        for m in CAP_GRAM.finditer(p):
            full = m.group(1)
            words = full.split()
            n_head = 0
            while n_head < len(words) and words[n_head].lower() in _HEAD_SKIP:
                n_head += 1
            words = [w[:-2] if w.lower().endswith("'s") else w
                     for w in words[n_head:]]  # possessives fold into the
            # entity itself ("Qiu Bojun's" -> "Qiu Bojun"); a bare surname
            # ("Qiu") then loses to coverage-drop instead of anchoring random
            # drama-cast pages
            if not words:
                continue
            pos = m.start() + full.index(words[0])
            before = p[:pos].rstrip()
            mid = bool(before) and before[-1] not in '.!?:—#"\'“‘「『'
            for n in (4, 3, 2, 1):
                if n > len(words):
                    continue
                cand = " ".join(words[:n])
                if len(cand) < 3 or not re.search(r"[A-Za-z\u4e00-\u9fff]", cand):
                    continue
                if all(w.lower().strip("'-.") in STOP for w in cand.split()):
                    continue  # generic phrase ("Case Study"), not a name
                if n == 1:
                    lw = cand.lower().replace("'s", "").rstrip("'-.")
                    pm = _PREP_BEFORE.search(p[:pos].lower())
                    place = lw in GENERIC_PLACES or (
                        pm and pm.group(1) in _LOC_PREP)
                    if place:
                        continue  # a place (list OR locative-preposition) is a
                # weak anchor: random pages naming the same city must not be
                # able to "prove" a figure (HRW mentioning Beijing ≠ Kingsoft)
                # consecutive capitalized words that are neither stopwords nor
                # sentence connectives = almost certainly a proper name
                strong = n >= 2 and words[1].lower() not in STOP \
                    and words[1].lower() not in _HEAD_SKIP
                note(cand, mid, strong)
    ents = [e for e, (c, m, s) in stats.items() if m >= 1 or c >= 2 or s >= 1]
    ents.sort(key=lambda e: (-(stats[e][2] or stats[e][1]), -stats[e][0], -len(e)))
    out = []
    for e in ents:  # prefer longer forms; drop covered sub-strings
        if not any(e != k and e in k for k in out):
            out.append(e)
    return out[:max_n]


# Chinese names have no capitalisation to anchor on, so the subject guard needs
# an organisation-suffix detector. Without it every 恒宇* company looks like the
# same subject (the 2-char 恒宇 bigram is shared), which is how a subsidiary's
# fact was showing up as a parent's support.
_CJK_ORG_SUFFIXES = (
    "集团", "集團", "公司", "控股", "实业", "實業", "科技", "健康",
    "医疗", "醫療", "医院", "醫院", "银行", "銀行", "保险", "保險",
    "证券", "證券", "电子", "電子", "网络", "網絡", "软件", "軟件",
    "半导体", "半導體", "通信", "物流", "能源", "汽车", "汽車",
    "地产", "地產", "基金", "资本", "資本", "投资", "投資", "大学",
    "大學", "学院", "學院", "研究院", "研究所", "实验室", "實驗室",
    "药业", "藥業", "生物", "传媒", "傳媒", "航空", "航天", "建设",
    "建設", "工程", "咨询", "諮詢", "会计", "會計", "办公", "辦公",
    "云", "雲",
)
_CJK_BAD_HEAD_START = set("该該本其这這那一个各子分母总總全共两兩几幾每团團")
_CJK_BAD_HEADS = {"全资", "全資", "资子", "資子", "团全", "團全", "集团",
                  "集團", "公司", "控股", "参股", "參股", "旗下", "母子",
                  "分公", "办公", "辦公", "计算", "計算", "服务", "服務",
                  "智能", "数据", "數據", "信息", "国际", "國際"}
_CJK_BAD_CHARS = set(
    "加入当时當就对于對於味着著回看实實是了的在和与與及或而但却都也还還"
    "又很更最将被將把从從向为為以因由这這那他她它我你您们們个個些种種位名"
    "到給有讓助來自")


def detect_cjk_entities(paragraphs, max_n=200):
    """CJK organisation names, anchored on a suffix (集团/科技/健康/银行…).

    Capitalised n-grams find nothing in Chinese, so without this the subject
    guard sees only 2-char bigrams and cannot tell 恒宇健康 from 恒宇科技.
    A candidate is accepted when it repeats or is quoted (a product line such
    as “恒宇云” may be named once). Frequent short names outrank long quoted
    phrases, otherwise a 6,000-line book fills the list with sentence
    fragments before 金山办公 is ever seen.
    """
    counts = {}
    quoted = set()
    for p in paragraphs or ():
        text = p if isinstance(p, str) else str(p)
        for suf in _CJK_ORG_SUFFIXES:
            for m in re.finditer(re.escape(suf), text):
                i = m.start()
                for k in (2, 3, 4):
                    j = i - k
                    if j < 0:
                        continue
                    head = text[j:i]
                    if not all("\u4e00" <= ch <= "\u9fff" for ch in head):
                        continue
                    if head[0] in _CJK_BAD_HEAD_START or head in _CJK_BAD_HEADS:
                        continue
                    if any(ch in _CJK_BAD_CHARS for ch in head):
                        continue
                    cand = head + suf
                    counts[cand] = counts.get(cand, 0) + 1
        for m in re.finditer(r"[“「『]([\u4e00-\u9fff]{2,10})[”」』]", text):
            quoted.add(m.group(1))
    ents = [e for e, n in counts.items() if n >= 2 or e in quoted]
    ents.extend(q for q in quoted if q not in ents)

    def score(e):
        return (counts.get(e, 0) + (3 if e in quoted else 0), len(e))

    ents.sort(key=score, reverse=True)
    return list(dict.fromkeys(ents))[:max_n]


def entity_head(entity):
    """The name part of an organisation entity (恒宇健康 -> 恒宇, Caelum Labs
    -> Caelum). Used only to permit a documented short form when no sibling
    entity is named in the same evidence."""
    e = normalize(entity)
    if not e:
        return ""
    for suf in _CJK_ORG_SUFFIXES:
        if e.endswith(suf) and len(e) > len(suf):
            return e[:-len(suf)]
    return e.split()[0]


def detect_language(paragraphs):
    total = sum(len(p) for p in paragraphs) or 1
    cjk = sum(len(CJK.findall(p)) for p in paragraphs)
    return "zh" if cjk / total > 0.15 else "en"


# Event anchors: surface variants that denote the SAME milestone. Used by the
# timeline builder to detect "entity did EVENT in two different years", and by
# the BYOS judge's predicate guard to stop a matching year confirming a
# DIFFERENT milestone ('founded 2011' must not support 'opened its plant 2011').
# The surface lists must be wide enough to recognize how the events are
# actually written: an unrecognized event reads as "no event", which silently
# disables the guard on exactly the claims that need it.
EVENT_ANCHORS = {
    "founding": ["found", "founding", "founded", "establish", "start", "beg",
                 "成立", "创办", "創立", "创立", "设立"],
    "ipo": ["ipo", "listed", "listing", "go public", "went public", "debut",
            "上市", "掛牌", "挂牌"],
    "acquisition": ["acquir", "bought", "take over", "took over", "merger",
                    "收购", "收購", "并购"],
    "launch": ["launch", "unveil", "release", "debuts", "roll out", "announce",
               "announc", "introduc", "open",
               "发布", "發佈", "推出", "宣布", "宣佈", "问世", "問世"],
    "naming": ["named", "renamed", "became name", "改名", "命名", "更名"],
    "funding_round": ["series a", "series b", "series c", "series d", "funding",
                      "round", "rais", "融资", "融資"],
    "certification": ["certif", "airworthiness", "认证", "認證", "资质",
                      "資質"],
    "clearance": ["clearance", "clearanc", "核准", "批准"],
    "shutdown": ["shut down", "closed", "dissolv", "liquidat", "bankrupt",
                 "破产", "倒閉", "关闭"],
}


def event_of(sentence_norm):
    hits = [ev for ev, kws in EVENT_ANCHORS.items() if any(k in sentence_norm for k in kws)]
    return hits[0] if len(hits) == 1 else (hits[0] if hits else None)


_YEAR_GENERIC = STOP | {
    "first", "person", "people", "man", "woman", "one", "year", "years",
    "time", "later", "early", "late", "mid", "about", "around", "over",
    "only", "even", "still", "also", "then", "when", "after", "before",
    "during", "through", "until", "since", "just", "well", "much", "many",
    "new", "old", "own", "same", "such", "walk", "went", "come", "came",
    "make", "made", "take", "took", "said", "say",
    "company", "corp", "corporation", "group", "firm", "inc", "ltd",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}


def year_fact_tokens(sentence, year_raw, radius=56):
    """Content words next to a year that identify WHICH event (Mars vs Moon,
    Fudan vs another school). Generic fillers and the year itself are dropped
    so a matching digit cannot green-light a different fact."""
    s = sentence or ""
    y = str(year_raw or "").replace(".0", "")
    i = s.find(y) if y else -1
    window = s if i < 0 else s[max(0, i - radius): i + len(y) + radius]
    return {t for t in tokens(window)
            if t not in _YEAR_GENERIC and not t.isdigit() and len(t) > 2}


def years_in(sentence):
    return sorted({int(m.group(1)) for m in YEAR_RE.finditer(sentence)})


_SPEAK_ZH = re.compile(
    r"([\u4e00-\u9fff]{1,4}?)(?:说|称|表示|回忆|回憶|指出)")
_SPEAK_EN = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})(?:\W+\w+){0,4}?\W*"
    r"(?:said|says|wrote|told|noted|argued|stated|remarked|motto|according to)")


def speaker_before_quote(text):
    """Person named in the attribution clause before the first quote mark
    (EN or ZH), or None. Name candidates stay capitalization-anchored; a few
    filler words are tolerated between name and speech verb."""
    cuts = [text.find(q) for q in '"“「『' if q in text]
    if not cuts:
        return None
    before = text[:min(cuts)]
    best, pos = None, -1
    zh = list(_SPEAK_ZH.finditer(before))
    en = list(_SPEAK_EN.finditer(before))
    if zh and zh[-1].start() > pos:
        best, pos = zh[-1].group(1), zh[-1].start()
    if en and en[-1].start() > pos:
        best, pos = en[-1].group(1), en[-1].start()
    return best.strip() if best else None


def names_conflict(name_a, name_b):
    """True when two speaker strings are both present and share no name token."""
    if not name_a or not name_b:
        return False
    ta, tb = tokens(name_a), tokens(name_b)
    return not (ta & tb)


def person_mentions(text):
    """[(name, sentence)] for every speech-verb attribution in a paragraph
    (EN: 'X said/wrote'; ZH: 'X说/称/表示/回忆/指出')."""
    out = []
    for s in sentences(text):
        for m in _SPEAK_ZH.finditer(s):
            out.append((m.group(1), s))
        for m in _SPEAK_EN.finditer(s):
            out.append((m.group(1), s))
    return out


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def name_tokens(text):
    """Tokens belonging to person/org/place names in a text — shared *subject*
    evidence, never *predicate* evidence."""
    toks = set()
    for e in detect_entities([text]):
        toks |= tokens(e)
    for m in _SPEAK_ZH.finditer(text):
        toks |= tokens(m.group(1))
    for m in re.finditer(r"([\u4e00-\u9fff]{2,4}?)(?=于|在|从)", text):
        toks |= tokens(m.group(1))
    return toks


# Placeholders that stand in for a subject without naming one. A line saying
# "The company was founded in 2011" is about SOME company, which is not the
# same claim as one about a named one.
_GENERIC_SUBJECT = {
    "company", "companies", "firm", "firms", "corporation", "corp", "co",
    "organization", "organisation", "group", "business", "startup",
    "start-ups", "venture", "the", "it", "they", "this", "that", "inc",
    "ltd", "plc", "gmbh", "sdn", "bv", "ab", "as",
    "公司", "企业", "企業", "集团", "集團", "该", "該", "这", "這", "那",
    "本公司", "本集团", "本企業",
}

_PRED_VOCAB = None


def _predicate_vocab():
    """Every token that appears inside an EVENT_ANCHORS entry."""
    global _PRED_VOCAB
    if _PRED_VOCAB is None:
        s = set()
        for kws in EVENT_ANCHORS.values():
            for k in kws:
                s |= tokens(k)
        _PRED_VOCAB = s
    return _PRED_VOCAB


def shares_subject(claim_text, line):
    """Do these two texts share a token that could only be the SUBJECT?

    Surviving a token requires it to be non-numeric, not a stopword, not a
    generic placeholder, and not part of any event anchor. That is deliberate:
    on anaphoric evidence the ONLY thing two texts share is the predicate
    ("the company" vs "Northwind Systems" share just "found"), so excluding
    predicate vocabulary is what separates "names the same thing" from "is
    about some thing".

    Used to decide whether asking a model "are these about the same subject?"
    is a question with an answer. It is NOT a name matcher — `name_tokens`
    misses single-word subjects and returns predicate fragments in Chinese, so
    it cannot answer this (measured: "Helio" -> [], "远景出版社正式成立" ->
    ['式成', '成立', '正式']).
    """
    pred = _predicate_vocab()
    for t in (tokens(claim_text) & tokens(line)):
        if t.isdigit() or t in STOP or t in _GENERIC_SUBJECT or t in pred:
            continue
        if len(t) < 2 and t.isascii():
            continue
        return True
    return False
