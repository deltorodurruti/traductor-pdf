#!/usr/bin/env python3
"""Completa los bloques que el traductor dejó en inglés.

Si se agota la cuota o falla la red a mitad de un libro, algunos bloques quedan sin traducir y
en el HTML solo-español se ven como párrafos en inglés. Esta herramienta los busca, los traduce
con el mismo motor del traductor (translate_and_review, con el glosario enmascarado) y los
reescribe en el HTML. Sin --aplicar solo informa (simulacro) y no llama a ningún motor.

Detecta un bloque como «en inglés» cuando sus palabras funcionales inglesas (the, and, of…)
superan a las españolas; con --relajado también atrapa los bloques mezclados.
--forzar "frase1|frase2" traduce además los bloques que contengan esas frases.

Uso: python herramientas/completar_bloques.py libro_es.html [--glosario g.txt] [--motor groq]
         [--modelo openai/gpt-oss-120b] [--razonamiento medium] [--relajado] [--forzar "a|b"] [--aplicar]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

EN = set("the and of to in is that for with as by on this which from are was be or it an at not have "
         "their they also his its were been shall thou thee unto".split())
ES = set("el la los las de que y en un una para con por se del al es son como sus su más pero o muy "
         "este esta fue lo le".split())


def es_ingles(texto: str, relajado: bool = False, forzar: tuple = ()) -> bool:
    """True si el bloque está (mayormente) en inglés. Sin palabras suficientes no se juzga."""
    if any(f and f in texto for f in forzar):
        return True
    w = re.findall(r"[A-Za-z']+", texto.lower())
    en, es = sum(x in EN for x in w), sum(x in ES for x in w)
    if len(w) < 8:
        return bool(w) and en > es and en / len(w) >= 0.5
    return (en >= 5 and en * 2 > es) if relajado else (en >= 4 and en > es)


def bloques_en_ingles(soup, relajado: bool = False, forzar: tuple = ()) -> list:
    """[(etiqueta de página, elemento, texto)] de los bloques de traducción que siguen en inglés."""
    out = []
    for pg in soup.select("section.page"):
        pn = pg.select_one(".page-num")
        etiqueta = pn.get_text(strip=True) if pn else "?"
        for d in pg.select(".solo, .col.tgt"):
            if d.has_attr("data-intraducible"):
                continue
            t = d.get_text("\n", strip=True)
            if es_ingles(t, relajado, forzar):
                out.append((etiqueta, d, t))
    return out


def traducir(texto: str, cfg, backend, masker) -> str:
    from translate import translate_and_review
    masked, mapping = masker.mask(texto)
    trad, _perdidos, _pasadas = translate_and_review(masked, mapping, backend, cfg.review_passes, cfg.review_early_stop)
    return trad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("html")
    ap.add_argument("--glosario", default="")
    ap.add_argument("--motor", default="groq")
    ap.add_argument("--modelo", default="")
    ap.add_argument("--razonamiento", default="medium")
    ap.add_argument("--relajado", action="store_true")
    ap.add_argument("--forzar", default="")
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--yes-cloud", action="store_true")
    ap.add_argument("--guardar-cada", type=int, default=20,
                    help="cada cuántos bloques se reescribe el HTML (0 = solo al final)")
    a = ap.parse_args()

    soup = BeautifulSoup(open(a.html, encoding="utf-8").read(), "html.parser")
    forzar = tuple(a.forzar.split("|")) if a.forzar else ()
    pend = bloques_en_ingles(soup, a.relajado, forzar)
    print(f"{os.path.basename(a.html)}: {len(pend)} bloques en inglés")
    for etiqueta, _d, t in pend:
        print(f"   [{etiqueta}] {len(t)} car.")
    if not a.aplicar or not pend:
        return

    import config
    import main as tr_main
    from translate import make_backend
    cfg = config.Config()
    modelo = a.modelo or ("openai/gpt-oss-120b" if a.motor == "groq" else "")
    cfg.backend, cfg.cloud_model, cfg.reasoning_effort = a.motor, modelo, a.razonamiento
    cfg.review_passes = 1
    cfg.book_type = "especializado"
    glosario = tr_main.load_glossary(cfg.glossary_path)
    if a.glosario:
        glosario += [t for t in tr_main.load_glossary(a.glosario) if t not in glosario]
    masker = tr_main.make_masker(cfg, glosario)
    import remoto
    if remoto.es_remoto(a.motor):
        try:
            remoto.exigir_consentimiento_nube("completar_bloques", aceptado=a.yes_cloud)
        except remoto.SinConsentimiento as e:
            print(f"✗ falta --yes-cloud / TRADUCTOR_NUBE_OK=1: {e}", file=sys.stderr, flush=True)
            raise SystemExit(78)
    backend = make_backend(cfg)
    ok, msg = backend.available()
    if not ok:
        sys.exit(f"✗ motor no disponible: {msg}")

    respaldo = a.html + ".antes"
    if not os.path.exists(respaldo):
        shutil.copy2(a.html, respaldo)
    def guarda():
        tmp = a.html + ".escribiendo"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(str(soup))
        os.replace(tmp, a.html)

    marcados = []
    for i, (etiqueta, d, t) in enumerate(pend, 1):
        nuevo = ""
        valido = False
        for intento in range(2):
            candidato = traducir(t, cfg, backend, masker)
            if candidato.strip() and not tr_main.bad_translation(t, candidato, cfg) and not tr_main._is_refusal(candidato):
                nuevo = candidato
                valido = True
                break
        if not valido:
            print(f"   inválido [{etiqueta}]: se conserva el bloque y se deja pendiente", flush=True)
            continue
        d.clear()
        for k, parte in enumerate(nuevo.split("\n")):
            if k:
                d.append(soup.new_tag("br"))
            d.append(parte)
        if es_ingles(nuevo, a.relajado, forzar):
            d["data-intraducible"] = "1"
            marcados.append(etiqueta)
        print(f"   traducido [{etiqueta}]  {i}/{len(pend)}", flush=True)
        if a.guardar_cada and i % a.guardar_cada == 0:
            guarda()
            print(f"   ·· guardado con {i} de {len(pend)} hechos", flush=True)
    guarda()
    print(f"✔ reescrito {a.html} (respaldo: {respaldo})")
    if marcados:
        print(f"⚠ {len(marcados)} bloque(s) siguen pareciendo inglés después de traducirse y quedan "
              f"marcados como intraducibles; conviene mirarlos: páginas {', '.join(marcados)}")


if __name__ == "__main__":
    main()
