"""Generate tests/corpus/annual_report.pdf — synthetic BYOS PDF evidence source
proving the corpus ingests PDFs (page-precision). Re-run anytime; deterministic."""
import pymupdf

TEXT = [
    "Nimbus Cloud Annual Report (Excerpt)",
    "Nimbus Cloud opened its Singapore office in 2019.",
    "R&D spending reached US$45 million in 2020.",
]

doc = pymupdf.open()
page = doc.new_page()  # A4-ish default
page.insert_text((72, 90), TEXT[0], fontsize=14)
for i, t in enumerate(TEXT[1:], start=1):
    page.insert_text((72, 90 + i * 28), t, fontsize=11)
doc.save("tests/corpus/annual_report.pdf")
print("wrote tests/corpus/annual_report.pdf")
