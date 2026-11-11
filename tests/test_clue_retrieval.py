"""Clue-first prose retrieval: figures with units, quotes, names.

A claim's decisive string ('28元', '3.2英寸', 'ALL IN AI', '华光快译') must
survive even when the generic rare-token ranking loses the exact source line.
Synthetic only (fictional 华光), no private case material.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.corpus import Corpus
    from app.textproc import clue_terms

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"CLUE FAIL: {msg}"
        n += 1

    clues = clue_terms("华光在28元定价之后，屏幕只有3.2英寸，媒体称为「白菜价」。")
    ok("28元" in clues, f"figure+unit is a clue ({clues})")
    ok("3.2英寸" in clues, f"decimal+unit is a clue ({clues})")
    ok("白菜价" in clues, f"quoted phrase is a clue ({clues})")
    ok("十年" in clue_terms("这是一场以十年为维度的战略长征。"),
       "Chinese numeral+unit is a clue")
    ok("ALL IN AI" in clue_terms("雷军提出 ALL IN AI。"),
       "all-caps phrase is a clue")
    ok("华光快译" in clue_terms("产品线包括华光快译、华光词霸。"),
       "CJK product name between punctuation is a clue")

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "source.md"
        src.write_text(
            "华光是一家虚构的软件公司。\n"
            "公司在1999年把产品定价为28元，随后引发价格战。\n"
            "当时手机屏幕只有3.2英寸，用户抱怨阅读困难。\n"
            "产品线包括华光影霸、华光快译、华光词霸。\n"
            "2005年，公司提出 ALL IN AI 的内部口号。\n",
            encoding="utf-8")
        corpus = Corpus(td)
        cases = [
            ("华光在28元定价之后做了什么？", "28元"),
            ("手机屏幕只有3.2英寸是否合理？", "3.2英寸"),
            ("华光快译是产品线的一部分吗？", "华光快译"),
            ("公司是否提出 ALL IN AI？", "ALL IN AI"),
        ]
        for claim, needle in cases:
            cands = corpus.find_prose_candidates(claim, top=3)
            ok(any(needle in (p.get("text") or "") for p in cands),
               f"clue lane finds {needle!r} in top-3")

    # A section heading is not a spoken quote: verbatim wording alone is not
    # enough when the source line is a title.
    from app.judge import _check_quote
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "source.md").write_text(
            "##### “不怕死的决心和向死而生的勇气”\n"
            "华光云总裁说：“我们一定要把这件事做成。”\n",
            encoding="utf-8")
        corpus = Corpus(td)
        claim = {"type": "quote", "raw": "不怕死的决心和向死而生的勇气",
                 "sentence": "他强调：不怕死的决心和向死而生的勇气。",
                 "context_sentence": "他强调：不怕死的决心和向死而生的勇气。"}
        verdict, _conf, _ev, _note = _check_quote(claim, corpus)
        ok(verdict != "supported", f"a heading is not a quote ({verdict})")

    print(f"CLUE TESTS: PASS ({n} assertions)")


if __name__ == "__main__":
    main()
