from docx import Document

doc = Document()
doc.add_heading("Smoke Test", 0)
doc.add_paragraph("Nimbus Cloud was founded in 2008 in Hangzhou by Ada Chen.")
doc.add_paragraph('Ada Chen said: "We build infrastructure for people, not for quick profits."')
doc.save("tests/smoke.docx")
print("smoke.docx written")
