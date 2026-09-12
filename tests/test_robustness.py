"""Foundation robustness suite: determinism, empty/adversarial input, and the
G1 performance budget. No network, no KS data."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.cli import run  # noqa: E402

DOC = ROOT / "tests" / "case_ai_draft.md"
CORPUS = ROOT / "tests" / "corpus"
FX = {("USD", "HKD", 2011): 7.7618, ("USD", "CNY", 2014): 6.1190}
TMP = ROOT / "reports" / "robust"


def _ids(findings):
    return [(f["id"], f["type"], f["verdict"], f.get("anchored")) for f in findings]


def determinism():
    a, _ = run(DOC, CORPUS, TMP / "d1", fx_rates=FX)
    b, _ = run(DOC, CORPUS, TMP / "d2", fx_rates=FX)
    assert _ids(a) == _ids(b), "same input produced different verdicts"
    assert all(f.get("anchored") for f in a if f.get("para") is not None), \
        "a deterministic claim lost its anchor"
    print(f"  determinism: OK ({len(a)} findings stable across 2 runs)")


def _run_text(text, tag):
    p = TMP / f"{tag}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    f, m = run(p, None, TMP / tag, fx_rates=FX)
    return f, m


def edge_inputs():
    cases = {
        "empty": "",
        "whitespace": "   \n\n   \t  ",
        "no_claims": "This is a short opinion with no dates or figures.",
        "huge_number": "Revenue was 99999999999999999999 dollars in 2010.",
        "unbalanced_md": "Text with a footnote[^missing] and another[^again].\n\n[^again]: def only",
        "emoji_mixed": "Launch in 2019 🚀 雷军 said hi — 15%↑ and US$2M (¥14M).",
        "cjk_punct": "公司成立于1992年。他说：「我们就是主人」。金额达1.5亿元（约2000万美元）。",
        "nulls_and_tabs": "A\tB 2015\tx\x00bad 100%",
        "one_huge_word": "X" * 5000 + " founded 1990",
    }
    for tag, text in cases.items():
        try:
            _run_text(text, tag)
        except Exception as e:  # noqa: BLE001
            print(f"  edge[{tag}]: CRASH {type(e).__name__}: {e}")
            raise
    print(f"  edge inputs: OK ({len(cases)} cases, no crashes)")


def performance():
    # ~25-page case study: repeated realistic paragraphs
    para = ("In 2011 the company raised HK$189 million (about US$24 million) and "
            "Ada Chen said: \"We build infrastructure for people.\" The team of "
            "2,000 employees grew; revenue reached US$120 million the next year. "
            "It was founded in 2010 in Hangzhou by Ada Chen and Bo Liu. ") * 3
    big = "\n\n".join(f"Section {i}. {para}" for i in range(120))  # ~30k words
    p = TMP / "big.md"
    p.write_text(big, encoding="utf-8")
    t0 = time.time()
    findings, meta = run(p, CORPUS, TMP / "perf", fx_rates=FX)
    dt = time.time() - t0
    print(f"  performance: {meta['words']} words, {len(findings)} findings, {dt:.1f}s "
          f"(G1 budget: 20 pages < 5 min)")
    assert dt < 60, f"25-page doc took {dt:.0f}s (should be seconds offline)"


def main():
    TMP.mkdir(parents=True, exist_ok=True)
    print("Foundation robustness:")
    determinism()
    edge_inputs()
    performance()
    print("ROBUSTNESS: PASS")


if __name__ == "__main__":
    main()
