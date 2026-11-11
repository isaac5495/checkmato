"""W5 precision gate: different metrics are not contradictions.

Synthetic only (fictional Acme). Pins the false-positive classes found in the
real 19-item residual:
- revenue vs gross profit vs net profit in adjacent paragraphs;
- shares vs voting rights for percentages;
- different product versions launched in different years.
The true-positive controls must still fire.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def claim(i, raw, value, sentence, para=0, typ="amount", currency="CNY"):
    return {"id": f"p{i:02d}", "type": typ, "raw": raw, "value": value,
            "currency": currency if typ == "amount" else None,
            "sentence": sentence, "para": para}


def main():
    from app import checks

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"PRECISION FAIL: {msg}"
        n += 1

    # 1. Revenue vs gross profit vs net profit: three metrics, no conflict.
    cs = [
        claim(1, "2亿", 2.0, "Acme 2020年全年营收为2亿元。", 0),
        claim(2, "3.7亿", 3.7, "Acme 2020年全年毛利为3.7亿元。", 1),
        claim(3, "8亿", 8.0, "Acme 2020年全年净利为8亿元。", 2),
    ]
    cs[1]["value"] = 3.7
    cs[2]["value"] = 8.0
    ok(not checks.internal_conflicts(cs),
       "revenue / gross profit / net profit must not conflict")

    # 2. Same metric, different value: a real conflict.
    cs = [
        claim(1, "2亿", 2.0, "Acme 2020年全年营收为2亿元。", 0),
        claim(2, "3.7亿", 3.7, "Acme 2020年全年营收为3.7亿元。", 1),
    ]
    ok(bool(checks.internal_conflicts(cs)),
       "two revenue figures for the same year must conflict")

    # 3. Shares vs voting rights: different bases, no conflict.
    cs = [
        claim(1, "20%", 20.0, "Acme 2020年向投资者发行20%的股权。", 0, "pct"),
        claim(2, "22.89%", 22.89, "Acme 2020年投资者持有22.89%的投票权。", 1, "pct"),
    ]
    ok(not checks.internal_conflicts(cs),
       "shares and voting rights must not conflict")

    # 4. Same base (shares), different percentage: a real conflict.
    cs = [
        claim(1, "20%", 20.0, "Acme 2020年向投资者发行20%的股权。", 0, "pct"),
        claim(2, "22.89%", 22.89, "Acme 2020年向投资者发行22.89%的股权。", 1, "pct"),
    ]
    ok(bool(checks.internal_conflicts(cs)),
       "two share percentages for the same year must conflict")

    # 5. Different product versions launched in different years: no conflict.
    tls = checks.entity_timelines([
        "Acme Suite 1.0 launched in 1989.",
        "Acme Suite 97 launched in 1997.",
    ], ["Acme Suite"])
    ok(not checks.timeline_conflicts(tls),
       "different product versions are not one launch")

    # 5b. Company-level vs department-level revenue: different facts.
    cs = [
        claim(1, "2亿", 2.0, "Acme 2020年全年营收为2亿元。", 0),
        claim(2, "3.7亿", 3.7, "Acme研发一部2020年全年营收为3.7亿元。", 1),
    ]
    ok(not checks.internal_conflicts(cs),
       "a department's revenue is not the group's revenue")

    # 5c. Different people's bonuses are not a contradiction.
    cs = [
        claim(1, "8万", 8.0, "王屹 2008年的奖金为8万元。", 0),
        claim(2, "200万", 200.0, "雷军给团队发放200万元奖金。", 1),
    ]
    ok(not checks.internal_conflicts(cs),
       "different people's bonuses must not conflict")

    # 5c2. The SAME person's bonus stated twice with different values: conflict.
    cs = [
        claim(1, "8万", 8.0, "王屹 2008年的奖金为8万元。", 0),
        claim(2, "10万", 10.0, "王屹 2008年的奖金为10万元。", 1),
    ]
    ok(bool(checks.internal_conflicts(cs)),
       "the same person's bonus cannot be two values")

    # 5d. A date-range endpoint is not a standalone date.
    ok(checks._in_date_range(
        claim(1, "2018", 2018.0, "2017年12月至2018年1月完成融资。", 0, "year")),
       "a range endpoint is recognised")

    # 5e. Sibling companies' milestones are not the parent's.
    tls = checks.entity_timelines([
        "Acme Cloud was founded in 2012.",
        "Acme Mobile was founded in 2014.",
    ], ["Acme", "Acme Cloud", "Acme Mobile"])
    ok(not checks.timeline_conflicts(tls),
       "a subsidiary's founding is not the parent's founding")

    # 5f. A date range spanning two years is one event, not two launches.
    tls = checks.entity_timelines([
        "Acme Cloud closed a Series D round across December 2017 and January 2018.",
    ], ["Acme Cloud"])
    ok(not checks.timeline_conflicts(tls),
       "a two-year range is not two conflicting dates")

    # 6. Same version, two launch years: a real conflict.
    tls = checks.entity_timelines([
        "Acme Suite 97 launched in 1997.",
        "Acme Suite 97 launched in 1998.",
    ], ["Acme Suite"])
    ok(bool(checks.timeline_conflicts(tls)),
       "the same product version cannot launch in two years")

    # 7. Metric extraction itself is closest-word, not first-word.
    ok(checks._metric("Acme revenue was 2 billion and gross profit was 3.7 billion",
                      "3.7 billion") == "gross_profit",
       "the metric closest to the figure wins")
    ok(checks._pct_base(claim(1, "20%", 20.0, "20% of the shares", 0, "pct")) ==
       {"shares"}, "English percentage base is read")

    print(f"PRECISION TESTS: PASS ({n} assertions)")


if __name__ == "__main__":
    main()
