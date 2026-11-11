"""Subject-guard regressions found by the adversarial dataset.

Three independent leaks, each previously reported as `supported`:
  * a name on a neighbouring line of the same passage satisfied the guard
  * a shared year bridged two different milestones (certification/clearance)
  * two Chinese companies sharing a 2-char prefix looked like one subject

All fixtures are synthetic.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _judge(sentence, sources, entities):
    from app.extract import extract_claims
    from app.judge import judge
    from app.library import Library

    with tempfile.TemporaryDirectory() as td:
        lib = Path(td) / "lib"
        lib.mkdir()
        for i, text in enumerate(sources):
            (lib / f"s{i}.md").write_text(text + "\n", encoding="utf-8")
        corpus = Library(lib).corpus
        claims = extract_claims([sentence])
        for c in claims:
            c["_doc_entities"] = list(entities)
        judge(claims, corpus)
        return [c["verdict"] for c in claims]


def main():
    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"SUBJECT GUARD FAIL: {msg}"
        n += 1

    # 1. A name on the next line of a 3-line passage must not support this
    #    line's figure (the passage window is not a subject match).
    v = _judge(
        "Orion Labs generated US$90 million in 2021.",
        ["Orion Cloud generated US$90 million in 2021.",
         "Orion Labs opened a research office in 2022."],
        ["Orion Labs", "Orion Cloud"])
    ok("supported" not in v, f"passage neighbour must not support ({v})")

    # 2. Same company, same year, different milestone: clearance != certification.
    v = _judge(
        "Orion Labs achieved safety certification in 2021.",
        ["Orion Labs achieved military clearance in 2021."],
        ["Orion Labs"])
    ok("supported" not in v, f"milestone mismatch must not support ({v})")

    # 3. Two Chinese sisters share 宁宇; the claim names the health arm and the
    #    source names the technology arm. 2-char overlap is not the subject.
    v = _judge(
        "宁宇健康拥有研发人员共600人。",
        ["宁宇科技为集团子公司，研发人员共600人。"],
        ["宁宇健康", "宁宇科技"])
    ok("supported" not in v, f"CJK sibling must not support ({v})")

    # 4. Controls: the same subject and milestone must still support.
    v = _judge(
        "Orion Labs achieved safety certification in 2021.",
        ["Orion Labs achieved safety certification in 2021."],
        ["Orion Labs"])
    ok("supported" in v, f"same subject/milestone must support ({v})")

    v = _judge(
        "宁宇健康拥有研发人员共600人。",
        ["宁宇健康拥有研发人员共600人。"],
        ["宁宇健康", "宁宇科技"])
    ok("supported" in v, f"CJK same subject must support ({v})")

    # 5. The CJK entity detector must return the sisters separately.
    from app.textproc import detect_cjk_entities
    ents = detect_cjk_entities([
        "宁宇集团总部位于北京。",
        "宁宇集团旗下有两家子公司。",
        "宁宇科技为集团子公司。",
        "宁宇健康运营互联网医院。",
        "宁宇科技与宁宇健康均为独立法人。",
    ])
    ok("宁宇科技" in ents and "宁宇健康" in ents and "宁宇集团" in ents,
       f"CJK org names are detected separately ({ents})")

    # 6. LLM placeholder strings ("None", "??") are never entity anchors: a
    #    scraped annual report containing the literal word "None" must not
    #    "name the subject" and turn an unrelated page into evidence.
    from app.textproc import clean_name
    ok(clean_name("None") == "" and clean_name("??") == ""
       and clean_name("Nimbus Cloud") == "Nimbus Cloud",
       "placeholder names must not become web anchors")

    print(f"SUBJECT GUARD: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
