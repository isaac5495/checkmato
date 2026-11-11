"""W1.4 semantic-prose benchmark: 25 true paraphrases + 25 near-misses.

Network benchmark, not part of the offline gate. It answers the W1.4 exit
question directly: of the prose claims a passage genuinely entails, how many
does the semantic judge support, and how many near-misses does it wrongly
support?

Fixtures are synthetic (fictional Nimbus Cloud / 金山-style Chinese examples);
no private case material. Run:
    .venv\\Scripts\\python.exe -X utf8 tests\\bench_nli_prose.py
Exit 0 only when recall >= 80% and false support <= 2%.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import nli  # noqa: E402
from app.llm import LLM  # noqa: E402

# (claim, passage, gold) — gold="support" means the passage entails the claim;
# "reject" means it is topically/entity related but does not entail it.
CASES = [
    # ---- true paraphrases (English) ----
    ("Nimbus Cloud opened its first overseas office in Singapore in 2019.",
     "The company's first base outside China was established in Singapore in 2019.",
     "support"),
    ("Ada Chen founded Nimbus Cloud in 2008.",
     "Nimbus Cloud was established by Ada Chen in 2008.", "support"),
    ("Nimbus Cloud went public in 2023.",
     "The company listed on the stock exchange in 2023.", "support"),
    ("Nimbus Cloud raised US$40 million in its Series C round.",
     "Its Series C financing brought in US$40 million.", "support"),
    ("The company's revenue reached US$210 million in 2021.",
     "In 2021 Nimbus Cloud reported revenue of US$210 million.", "support"),
    ("Nimbus Cloud released the Lingxi engine in 2015.",
     "The Lingxi engine was launched by Nimbus Cloud in 2015.", "support"),
    ("Bo Liu said the company would not return to the hardware market.",
     "Bo Liu stated that Nimbus Cloud had no plans to re-enter hardware.", "support"),
    ("Nimbus Cloud had 2,000 employees across six offices by 2022.",
     "By 2022 the group employed 2,000 people in six offices.", "support"),
    ("The Hangzhou team of 1,200 handled most of the platform's core work.",
     "Most core platform work was done by the 1,200-person Hangzhou team.", "support"),
    ("Nimbus Cloud opened a research centre in Beijing in 2020.",
     "A Beijing research centre was opened by the company in 2020.", "support"),
    ("Ada Chen stepped down as CEO in 2022.",
     "In 2022 Ada Chen resigned from the chief executive role.", "support"),
    ("Nimbus Cloud acquired a data-analytics startup in 2021.",
     "The company bought a data-analytics startup in 2021.", "support"),
    ("The company's headcount grew by 30% in 2020.",
     "Nimbus Cloud expanded its workforce by 30% during 2020.", "support"),
    ("Nimbus Cloud partnered with TechWatch to publish an industry report.",
     "A joint industry report was published by Nimbus Cloud and TechWatch.", "support"),
    ("The Lingxi engine was discontinued in 2019.",
     "Nimbus Cloud retired the Lingxi engine in 2019.", "support"),
    ("The company moved its headquarters to Shenzhen in 2018.",
     "Nimbus Cloud relocated its head office to Shenzhen in 2018.", "support"),
    ("Nimbus Cloud's IPO raised HK$900 million.",
     "The listing raised HK$900 million for the company.", "support"),
    ("The 2014 infrastructure fund committed CNY 1.25 billion.",
     "A CNY 1.25 billion commitment was made by the 2014 infrastructure fund.",
     "support"),
    ("Nimbus Cloud closed its Singapore office in 2021.",
     "The Singapore office was shut down by the company in 2021.", "support"),
    ("Ada Chen said the company would focus on enterprise customers.",
     "According to Ada Chen, Nimbus Cloud would prioritise enterprise clients.",
     "support"),
    ("Nimbus Cloud launched a cloud-storage product in 2017.",
     "A cloud-storage product was introduced by Nimbus Cloud in 2017.", "support"),
    # ---- true paraphrases (Chinese) ----
    ("金山于2019年在新加坡开设了首个海外办事处。",
     "公司第一家海外办公室于2019年在新加坡设立。", "support"),
    ("雷军于2022年卸任金山CEO。",
     "2022年，雷军辞去金山首席执行官职务。", "support"),
    ("金山在2021年收购了一家数据分析初创公司。",
     "2021年，金山收购了一家数据分析领域的初创企业。", "support"),
    ("金山2020年的员工人数增长了30%。",
     "2020年，金山员工规模扩大了30%。", "support"),

    # ---- near-misses (English): one predicate/value differs ----
    ("Nimbus Cloud opened its first overseas office in Singapore in 2019.",
     "Nimbus Cloud opened an office in Tokyo in 2019.", "reject"),
    ("Ada Chen founded Nimbus Cloud in 2008.",
     "Ada Chen joined Nimbus Cloud in 2008.", "reject"),
    ("Nimbus Cloud went public in 2023.",
     "Nimbus Cloud was acquired in 2023.", "reject"),
    ("Nimbus Cloud raised US$40 million in its Series C round.",
     "Nimbus Cloud raised US$40 million in its Series B round.", "reject"),
    ("The company's revenue reached US$210 million in 2021.",
     "The company's revenue reached US$210 million in 2020.", "reject"),
    ("Nimbus Cloud released the Lingxi engine in 2015.",
     "Nimbus Cloud released the Lingxi engine in 2016.", "reject"),
    ("Bo Liu said the company would not return to the hardware market.",
     "Bo Liu said the company would return to the hardware market.", "reject"),
    ("Nimbus Cloud had 2,000 employees across six offices by 2022.",
     "Nimbus Cloud had 1,200 employees across six offices by 2022.", "reject"),
    ("The Hangzhou team of 1,200 handled most of the platform's core work.",
     "The Beijing team of 1,200 handled most of the platform's core work.", "reject"),
    ("Nimbus Cloud opened a research centre in Beijing in 2020.",
     "Nimbus Cloud opened a research centre in Beijing in 2021.", "reject"),
    ("Ada Chen stepped down as CEO in 2022.",
     "Ada Chen stepped down as CTO in 2022.", "reject"),
    ("Nimbus Cloud acquired a data-analytics startup in 2021.",
     "Nimbus Cloud acquired a cybersecurity startup in 2021.", "reject"),
    ("The company's headcount grew by 30% in 2020.",
     "The company's revenue grew by 30% in 2020.", "reject"),
    ("Nimbus Cloud partnered with TechWatch to publish an industry report.",
     "Nimbus Cloud partnered with TechWatch to run a developer survey.", "reject"),
    ("The Lingxi engine was discontinued in 2019.",
     "The Lingxi engine was upgraded in 2019.", "reject"),
    ("The company moved its headquarters to Shenzhen in 2018.",
     "The company opened a branch in Shenzhen in 2018.", "reject"),
    ("Nimbus Cloud's IPO raised HK$900 million.",
     "Nimbus Cloud's IPO raised HK$189 million.", "reject"),
    ("The 2014 infrastructure fund committed CNY 1.25 billion.",
     "The 2014 infrastructure fund committed CNY 1.25 million.", "reject"),
    ("Nimbus Cloud closed its Singapore office in 2021.",
     "Nimbus Cloud expanded its Singapore office in 2021.", "reject"),
    ("Ada Chen said the company would focus on enterprise customers.",
     "Ada Chen said the company would focus on consumer customers.", "reject"),
    ("Nimbus Cloud launched a cloud-storage product in 2017.",
     "Nimbus Cloud launched a cloud-security product in 2017.", "reject"),
    # ---- near-misses (Chinese) ----
    ("金山于2019年在新加坡开设了首个海外办事处。",
     "金山于2019年在东京开设了首个海外办事处。", "reject"),
    ("雷军于2022年卸任金山CEO。",
     "雷军于2022年卸任金山CTO。", "reject"),
    ("金山在2021年收购了一家数据分析初创公司。",
     "金山在2021年收购了一家网络安全初创公司。", "reject"),
    ("金山2020年的员工人数增长了30%。",
     "金山2020年的收入增长了30%。", "reject"),
]


class CaseCorpus:
    """One passage per claim: isolates the semantic judge from retrieval."""

    def __init__(self, by_claim):
        self.by_claim = by_claim

    def find_prose_candidates(self, text, top=3):
        passage = self.by_claim.get((text or "").strip())
        if not passage:
            return []
        return [{"fname": "case.md", "start": 1, "end": 1, "text": passage}]


def make_claim(i, text):
    return {"id": f"n{i:02d}", "type": "event", "verdict": "unverified",
            "raw": text, "sentence": text, "sentence_context": text,
            "context_sentence": text, "origin": "sentence",
            "evidence": [], "confidence": "low", "suggestion": ""}


def main():
    claims = []
    for i, (claim, passage, gold) in enumerate(CASES):
        c = make_claim(i, claim)
        c["_gold"] = gold
        c["_passage"] = passage
        claims.append(c)

    llm = LLM(max_calls=24, max_tokens=80000, max_seconds=300)
    if not llm.available:
        print("NLI BENCH: no LLM key configured")
        return 2

    started = time.monotonic()
    rescued = 0
    # Run the true and near-miss groups separately. A true case and its
    # near-miss twin share the claim text but not the passage, so a single
    # text->passage map would collide; each group's texts are unique.
    for gold in ("support", "reject"):
        group = [c for c in claims if c["_gold"] == gold]
        corpus = CaseCorpus({c["sentence_context"]: c["_passage"]
                             for c in group})
        rescued += nli.judge(llm, group, corpus=corpus,
                             max_claims=len(group), batch=10)
    elapsed = time.monotonic() - started

    rows, true_ok, reject_bad = [], 0, 0
    true_total = sum(1 for _c, _p, g in CASES if g == "support")
    reject_total = len(CASES) - true_total
    for (claim, passage, gold), c in zip(CASES, claims):
        hit = c["verdict"] == "supported"
        if gold == "support" and hit:
            true_ok += 1
        if gold == "reject" and hit:
            reject_bad += 1
        rows.append({"id": c["id"], "gold": gold, "verdict": c["verdict"],
                     "claim": claim, "passage": passage,
                     "note": c.get("suggestion", "")[:200]})
        print(f"{c['id']} {gold:7s} -> {c['verdict']:10s} | {claim[:78]}")

    recall = true_ok / true_total if true_total else 0.0
    false_rate = reject_bad / reject_total if reject_total else 0.0
    print(f"\nrecall {true_ok}/{true_total} = {recall:.1%}")
    print(f"false support {reject_bad}/{reject_total} = {false_rate:.1%}")
    print(f"llm calls {llm.calls} | tokens {llm.tokens} | {elapsed:.1f}s | "
          f"provider {llm.provider or '?'}")

    out = {"total": len(CASES), "true_total": true_total,
           "reject_total": reject_total, "true_supported": true_ok,
           "false_support": reject_bad, "recall": recall,
           "false_support_rate": false_rate, "llm_calls": llm.calls,
           "llm_tokens": llm.tokens, "seconds": round(elapsed, 1),
           "provider": llm.provider, "rescued": rescued, "rows": rows}
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "nli-prose-eval.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (reports / "nli-prose-eval.md").write_text(
        "# W1.4 semantic-prose benchmark\n\n"
        f"- Cases: {len(CASES)} ({true_total} true, {reject_total} near-miss)\n"
        f"- Recall: {true_ok}/{true_total} = {recall:.1%}\n"
        f"- False support: {reject_bad}/{reject_total} = {false_rate:.1%}\n"
        f"- LLM calls: {llm.calls}; tokens: {llm.tokens}; {elapsed:.1f}s\n"
        f"- Provider: {llm.provider or '?'}\n"
        f"- Exit gate: {'PASS' if recall >= 0.8 and false_rate <= 0.02 else 'FAIL'}\n",
        encoding="utf-8")

    passed = recall >= 0.80 and false_rate <= 0.02
    print("EXIT GATE:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
