"""FX conversion verifier (F4c) — $0 via Frankfurter (ECB reference rates,
no key, historical). Detects "X in one currency (about Y in another)" pairs,
recomputes the implied rate against the official year-end rate, and shows the
arithmetic. Skipped (deferred) without web access."""
import json
import re
import urllib.request
from collections import defaultdict


API = "https://api.frankfurter.app/{date}?from={base}&to={quote}"

# Official USD->CNY annual-average rates, 1978-1998 (dual-track era): no free
# API covers them (ECB/Frankfurter data starts 1999). Widely published values
# (People's Bank of China / IMF International Financial Statistics yearbooks).
# Provenance is shown in the evidence so the user can double-check the table.
_HIST_USD_CNY = {
    1978: 1.686, 1979: 1.555, 1980: 1.530, 1981: 1.705, 1982: 1.892,
    1983: 2.000, 1984: 2.320, 1985: 2.937, 1986: 3.453, 1987: 3.722,
    1988: 3.722, 1989: 3.762, 1990: 4.783, 1991: 5.323, 1992: 5.515,
    1993: 5.762, 1994: 8.619, 1995: 8.278, 1996: 8.300, 1997: 8.289,
    1998: 8.279,
}


class FX:
    def __init__(self, tolerance=0.10, rates=None, allow_http=True):
        self.tol = tolerance
        self.allow_http = allow_http
        self.overrides = rates or {}  # {(base, quote, year): rate} — for offline eval/tests
        self._cache = {}
        self.checks = 0

    def rate(self, base, quote, year):
        v, _src = self.rate_with_source(base, quote, year)
        return v

    def rate_with_source(self, base, quote, year):
        """Returns (rate, source-label): API data first, then the curated
        pre-1999 table (USD<->CNY). None,None when neither covers it."""
        key = (base, quote, year)
        if key in self.overrides:
            return self.overrides[key], "override"
        rev = (quote, base, year)
        if rev in self.overrides:
            return 1.0 / self.overrides[rev], "override"
        if key in self._cache:
            return self._cache[key]
        val, src = None, None
        if self.allow_http:
            url = API.format(date=f"{year}-12-28", base=base, quote=quote)
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "CheckMato/0.1 (fact-check research)"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    val = json.load(r)["rates"][quote]
                    src = f"frankfurter.app {year}-12-28"
            except Exception:
                val = None
        if val is None and year in _HIST_USD_CNY:  # free APIs stop at 1999
            if (base, quote) == ("USD", "CNY"):
                val, src = _HIST_USD_CNY[year], "PBoC/IMF official annual average"
            elif (base, quote) == ("CNY", "USD"):
                val, src = 1.0 / _HIST_USD_CNY[year], "PBoC/IMF official annual average"
        self._cache[key] = (val, src)
        self.checks += 1
        return val, src


_CONV_SIGNAL = re.compile(r"\(\s*(?:about|approx\.?|roughly|~)?|→|->|≈|equivalent|converted"
                          r"|约合|折合|换成|\(约|（约", re.I)


def _conversion_pairs(claims):
    """Two amount claims in different currencies within one sentence, where the
    SECOND is an explicit conversion of the FIRST (parenthetical/arrow/≈ within
    25 chars). Two unrelated figures in one sentence must NOT match."""
    by_sent = defaultdict(list)
    for c in claims:
        if c["type"] == "amount" and c["currency"]:
            by_sent[(c["para"], c["sentence"])].append(c)
    pairs = []
    for (_para, sent), cs in by_sent.items():
        cs.sort(key=lambda c: c["span"][0])
        for i in range(len(cs) - 1):
            a, b = cs[i], cs[i + 1]
            if a["currency"] == b["currency"]:
                continue
            gap = sent[a["span"][1]:b["span"][0]]
            if len(gap) <= 25 and (_CONV_SIGNAL.search(gap) or not gap.strip(" ,;")):
                pairs.append((a, b))
    return pairs


def _year_for(sent, claims):
    y = re.search(r"\b(19\d{2}|20\d{2})\b", sent)
    return int(y.group(1)) if y else None


def tag_conversions(claims):
    """Run BEFORE web enrichment: mark both halves of a stated conversion so
    the converted figure is never judged alone out of context. The primary
    (a) gets normal checking; the secondary (b) is judged by arithmetic."""
    pairs = _conversion_pairs(claims)
    for a, b in pairs:
        a["fx_lead"] = True
        b["fx_secondary"] = True
        b["fx_of"] = a["id"]
    return pairs


def verify_conversions(claims, fx):
    """Annotate both claims of each detected conversion; verdict upgrades only
    with a clean arithmetic result, and is never softened beyond evidence."""
    results = []
    for a, b in _conversion_pairs(claims):
        year = _year_for(a["sentence"], claims)
        if not year:
            results.append((a, b, "no_year"))
            continue
        src, tgt = a, b  # b is stated as the conversion of a
        implied = src["value"] / tgt["value"]  # src currency per 1 tgt currency
        official, source = fx.rate_with_source(tgt["currency"], src["currency"], year)
        if official is None:
            # cannot settle by arithmetic — say exactly that; never web-
            # contradict a conversion that merely restates a checked figure
            b["suggestion"] = (
                f"Parenthetical conversion of {a['id']}: implies "
                f"{implied:.2f} {src['currency']} per {tgt['currency']} ({year}) — "
                f"no free official rate for {year}; verify that rate by hand.")
            b["_skip_reason"] = f"conversion of {a['id']} (rate for {year} unavailable)"
            results.append((a, b, "deferred"))
            continue
        dev = abs(implied - official) / official
        calc = (f"{src['raw']} = {tgt['raw']} implies {src['currency']} "
                f"{implied:.2f}/{tgt['currency']}; official {year} rate "
                f"{official:.2f}/{tgt['currency']} (dev {dev:.0%}, source: {source})")
        if dev <= fx.tol:
            # arithmetic agrees; but a correct conversion of a contradicted
            # base figure is still in doubt — context-aware verdicts:
            a_bad = a["verdict"] in ("contradicted", "internal_conflict",
                                     "conflicting")
            b["verdict"] = "unverified" if a_bad else "supported"
            b["confidence"] = "medium" if a_bad else "high"
            b["evidence"] = (b.get("evidence") or []) + [{
                "kind": "fx", "ref": f"{source} {tgt['currency']}->{src['currency']}",
                "quote": calc, "precision": "primary_source"}]
            b["suggestion"] = ("FX arithmetic checks out: " + calc +
                               (f" — BUT the underlying {a['id']} figure was "
                                "contradicted, so this restatement inherits that doubt."
                                if a_bad else ""))
            if not a_bad:
                a["evidence"] = (a.get("evidence") or []) + [{
                    "kind": "fx", "ref": f"{source} {tgt['currency']}->{src['currency']}",
                    "quote": calc, "precision": "primary_source"}]
                if a["verdict"] == "unverified":
                    a["verdict"], a["confidence"] = "supported", "high"
                    a["suggestion"] = "FX arithmetic checks out: " + calc
        else:
            # arithmetic disagrees: the CONVERSION is wrong even if the web
            # supported the converted number elsewhere at a different rate
            b["verdict"] = "contradicted"
            b["confidence"] = "high"
            b["evidence"] = (b.get("evidence") or []) + [{
                "kind": "fx", "ref": f"{source} {tgt['currency']}->{src['currency']}",
                "quote": calc, "precision": "primary_source"}]
            b["suggestion"] = "FX arithmetic off: " + calc
            a["evidence"] = (a.get("evidence") or []) + [{
                "kind": "fx", "ref": f"{source} {tgt['currency']}->{src['currency']}",
                "quote": calc, "precision": "primary_source"}]
        results.append((a, b, "checked"))
    return results
