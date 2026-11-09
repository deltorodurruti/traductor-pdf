"""Dar de alta un PDF suelto: traducir_libro._asegura_carpeta.

Comprueba que una ruta a un PDF se convierte en carpeta del taller, se copia dentro, se registra su
entrega con entregas.alta (sin tildes, sin duplicar filas), y que una carpeta normal pasa tal cual.
"""
import traducir_libro


def test_alta_desde_pdf(tmp_path, monkeypatch):
    taller = tmp_path / "taller"
    taller.mkdir()
    monkeypatch.setattr(traducir_libro, "TRAB", str(taller))
    pdf = tmp_path / "Dragón Rouge - Dracontias [1 eBook - PDF].pdf"
    pdf.write_bytes(b"%PDF-1.4 falso")

    slug = traducir_libro._asegura_carpeta(str(pdf))
    assert slug == "dragon_rouge_dracontias"
    assert (taller / slug / (slug + ".pdf")).exists()
    tsv = (taller / "entregas.tsv").read_text(encoding="utf-8")
    assert slug in tsv and "Dragon_Rouge_Dracontias_ES.pdf" in tsv

    traducir_libro._asegura_carpeta(str(pdf))
    assert (taller / "entregas.tsv").read_text(encoding="utf-8").count(slug + "\t") == 1

    assert traducir_libro._asegura_carpeta("mi_carpeta") == "mi_carpeta"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
