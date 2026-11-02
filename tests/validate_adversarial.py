"""Adversarial + format-matrix validation of the improved deterministic engine."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main():
    import pymupdf

    from eval_en_holdout import suite
    from app.byos import footnote_audit
    from app.extract import extract_claims, read_doc
    from app.glossary import same_entity
    from app.judge import judge
    from app.library import Library

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"ADVERSARIAL FAIL: {msg}"
        n += 1

    with tempfile.TemporaryDirectory() as td:
        libdir = Path(td) / "lib"
        libdir.mkdir()
        for name, text in suite.SOURCES.items():
            (libdir / name).write_text(text, encoding="utf-8")
        lib = Library(libdir)
        corpus = lib.corpus

        # 1. A decade is not a year claim.
        decade = extract_claims(["In the 1990s Meridian Health expanded."])
        ok(not any(c["type"] == "year" and c["raw"] == "1990" for c in decade),
           "a decade ('1990s') is not extracted as the year 1990")

        # 2. Currency mismatch is never support.
        cny = extract_claims(
            ["Meridian Health reported revenue of 52 million yuan in 2020."])
        amt = next(c for c in cny if c["type"] == "amount")
        judge([amt], corpus)
        ok(amt["verdict"] != "supported",
           f"USD fact cannot support a CNY claim ({amt['verdict']})")

        # 3. Subsidiary is not the parent.
        ok(not same_entity("Meridian Health", "Meridian Health Cloud",
                           cooccur=True),
           "parent and Cloud subsidiary are different entities")

        # 4. Lookalike name is not the subject.
        look = extract_claims(
            ["Meridian Hospitals reported revenue of US$68 million in 2022."])
        lamt = next(c for c in look if c["type"] == "amount")
        judge([lamt], corpus)
        ok(lamt["verdict"] != "supported",
           f"lookalike name cannot borrow the fact ({lamt['verdict']})")

        # 5. Wrong footnote anchor still reports misattributed.
        doc = read_doc(ROOT / "tests" / "byos" / "wrong_anchor.docx")
        byos_lib = Library(ROOT / "tests" / "byos" / "lib")
        rows = footnote_audit(doc, byos_lib)
        ok(rows and rows[0]["verdict"] == "misattributed",
           "wrong footnote anchor is misattributed")

        # 6. A scan is flagged, not silently empty.
        ok(any(x["path"] == "scanned.pdf" for x in byos_lib.no_text_layer),
           "scanned PDF is reported as no_text_layer")

        # 7. Determinism: same input, same verdicts and locators twice.
        def run_once():
            cs = extract_claims(
                ["Meridian Health reported revenue of US$45 million in 2018."])
            c = next(x for x in cs if x["type"] == "amount")
            judge([c], corpus)
            return (c["verdict"], tuple(e.get("ref") for e in c["evidence"]))

        ok(run_once() == run_once(), "two runs produce identical verdict/locator")

        # 8. Format matrix: md, txt, docx, text-layer PDF.
        fact = "Meridian Health reported revenue of US$45 million in 2018."
        for fmt in ("md", "txt", "docx", "pdf"):
            fdir = Path(td) / f"lib_{fmt}"
            fdir.mkdir()
            path = fdir / f"fact.{fmt}"
            if fmt in ("md", "txt"):
                path.write_text(fact + "\n", encoding="utf-8")
            elif fmt == "docx":
                md = Path(td) / "fact.md"
                md.write_text(fact + "\n", encoding="utf-8")
                subprocess.run(["pandoc", str(md), "-o", str(path)], check=True)
            else:
                pdf = pymupdf.open()
                page = pdf.new_page()
                page.insert_text((72, 72), fact, fontsize=11)
                pdf.save(str(path))
                pdf.close()
            flib = Library(fdir)
            fclaims = extract_claims([fact])
            fc = next(x for x in fclaims if x["type"] == "amount")
            judge([fc], flib.corpus)
            ok(fc["verdict"] == "supported",
               f"{fmt}: the same fact is supported")
            ok(fc["evidence"] and fc["evidence"][0]["precision"]
               in ("line", "para", "page"),
               f"{fmt}: evidence carries a valid locator precision")

    print(f"ADVERSARIAL: PASS ({n} assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
