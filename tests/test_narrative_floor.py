"""W1.2 eligibility gate: commentary/analysis -> narrative, facts untouched.

Synthetic only (fictional 华光), no private case material. The rule is a
deterministic floor for sources_only runs, where no LLM triage is available.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.enrich import mark_commentary

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"NARRATIVE FLOOR FAIL: {msg}"
        n += 1

    def claim(text, ctype="event"):
        return {"id": f"c{n}", "type": ctype, "sentence": text,
                "verdict": "unverified", "confidence": "low",
                "evidence": [], "suggestion": ""}

    commentary = [
        "38年来，华光历经了一系列足以使整个公司覆灭的巨大挑战。",
        "历经多次危机的管理层描述了如出一辙的破局轨迹。",
        "已逐渐凝聚为一种坚定的信念：生存依赖于持续更新。",
        "本文将深入剖析文化、领导力与组织设计如何相互作用。",
        "决定是否继续研发的，从来不是财务预测，而是公司的抱负。",
    ]
    controls = [
        "华光的食堂每天提供四餐，直到凌晨。",
        "华光于2011年在卑尔根开设了一家工厂。",
        "华光的创始人把电脑搬进病房继续写代码。",
    ]

    claims = [claim(s) for s in commentary] + [claim(s) for s in controls]
    # a numeric claim with a temporal phrase must NOT be demoted: the figure is
    # exactly what a fact-checker needs to keep
    numeric = claim("38年来，华光的营业收入在2019年达到1.25亿美元。", "amount")
    claims.append(numeric)

    mark_commentary(claims)

    for c, text in zip(claims[:len(commentary)], commentary):
        ok(c["verdict"] == "narrative",
           f"commentary became narrative: {text[:30]} ({c['verdict']})")
        ok("commentary/analysis" in (c.get("_skip_reason") or ""),
           "narrative carries a reason")
    for c, text in zip(claims[len(commentary):len(commentary) + len(controls)],
                       controls):
        ok(c["verdict"] == "unverified",
           f"factual control stays unverified: {text[:30]} ({c['verdict']})")
    ok(numeric["verdict"] == "unverified",
       "numeric claim with a temporal phrase is not demoted")

    # the existing heading/question floor still works and is not replaced
    from app.enrich import mark_narrative
    h = claim("华光为什么能活下来？")
    mark_narrative([h])
    ok(h["verdict"] == "narrative", "question still becomes narrative")

    print(f"NARRATIVE FLOOR TESTS: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
