"""Genera sample.pdf para pruebas: 1 página de texto+imagen y 1 página 'escaneada'."""
import fitz

doc = fitz.open()

p1 = doc.new_page()
p1.insert_textbox(
    fitz.Rect(50, 60, 545, 220),
    "This introductory chapter describes how rivers shape the surrounding landscape. "
    "The researcher compares several measurements collected over many years. "
    "The results highlight the relationship between soil, rainfall, and plant growth.",
    fontsize=12, fontname="helv")
pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 220, 120))
pix.set_rect(pix.irect, (60, 40, 90))
p1.insert_image(fitz.Rect(180, 240, 400, 360), pixmap=pix)
p1.insert_textbox(
    fitz.Rect(50, 380, 545, 480),
    "After the survey, the researcher records the measurements and closes the notebook. "
    "The observations must be copied exactly as recorded.",
    fontsize=12, fontname="helv")

tmp = fitz.open()
tp = tmp.new_page()
tp.insert_textbox(
    fitz.Rect(40, 60, 555, 400),
    "This page simulates a scanned book. Here the term ZORKAMEL appears, "
    "along with a short note. A simple diagram is shown below.",
    fontsize=14, fontname="helv")
scan_png = tp.get_pixmap(dpi=150).tobytes("png")
tmp.close()

p2 = doc.new_page()
p2.insert_image(p2.rect, stream=scan_png)

doc.save("sample.pdf")
doc.close()
print("sample.pdf creado (2 páginas: texto+imagen, escaneada)")
