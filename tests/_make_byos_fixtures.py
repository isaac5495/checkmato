"""Generate the synthetic BYOS fixtures (no case material).

Run once; the generated binaries are what the tests consume:

    .venv\\Scripts\\python.exe -X utf8 tests\\_make_byos_fixtures.py

Requires pymupdf (already a runtime dependency) and pandoc on PATH for the
docx footnotes; pandoc is a fixture-building tool, not a runtime dependency.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "byos" / "lib"

ACME = """# Acme Systems

Acme Systems reported revenue of 125 million dollars for the 2019 fiscal year.

Acme Systems was founded in 1998 in Bergen by two engineers.

The Bergen plant opened in 2011.

Acme Software, hereafter Acme, employs 400 people in three offices.
"""

LEDGER = """# Harbor Ledger

Acme Systems was founded in 1998 by two engineers in Bergen.
"""

PAGES = [
    "Acme Systems reported revenue of 125 million dollars "
    "for the 2019 fiscal year.",
    "Acme Systems was founded in 1998 in Bergen by two engineers.",
    "The Bergen plant opened in 2011.",
    "Acme Software, hereafter Acme, employs 400 people in three offices.",
]

BOOK_DOCX = """# Acme Systems

Acme Systems reported revenue of 125 million dollars in 2019.[^1]

[^1]: 《Harbor Ledger》, "Acme Systems annual results", 2019.
"""

WRONG_DOCX = """# Acme Systems

Acme Systems opened its Bergen plant in 2011.[^1]

[^1]: 《Harbor Ledger》, "Acme Systems founded in 1998."
"""


def make_pdf(path, pages):
    import pymupdf
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    doc.save(str(path))
    doc.close()


def make_docx(md_text, path):
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "draft.md"
        src.write_text(md_text, encoding="utf-8")
        subprocess.run(["pandoc", str(src), "-f", "markdown",
                        "-t", "docx", "-o", str(path)], check=True)


def main():
    LIB.mkdir(parents=True, exist_ok=True)
    (LIB / "acme_history.md").write_text(ACME, encoding="utf-8")
    (LIB / "harbor_ledger.md").write_text(LEDGER, encoding="utf-8")
    make_pdf(LIB / "acme_history.pdf", PAGES)
    make_pdf(LIB / "scanned.pdf", ["", ""])   # no text layer at all
    make_docx(BOOK_DOCX, ROOT / "byos" / "book_only.docx")
    make_docx(WRONG_DOCX, ROOT / "byos" / "wrong_anchor.docx")
    print("fixtures written to", ROOT / "byos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
