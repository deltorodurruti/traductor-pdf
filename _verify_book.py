#!/usr/bin/env python3
"""Verifica un libro traducido con chequeos DETERMINISTAS (fiables) y produce el
HTML solo-español.

Sin juez LLM: se evaluó (llama3.2:3b) con 50 buenos + 50 malos → solo detecta lo
que ya detecta lo determinista (texto en inglés: 17/17), falla en sentido (1/17) y
truncado (2/16), y da falsas alarmas (7/50). No aporta y estorba. Chequeos usados:
  - bloques en inglés / truncados  (idioma origen + ratio de longitud)
  - basura / repetición            (diversidad léxica muy baja)
  - palabras sueltas en inglés     (residuo por sufijos English-only: -less, -ing…)
La fidelidad de SENTIDO no se verifica por máquina aquí (requiere leer a mano o un
modelo juez fuerte que este equipo no corre rápido).
Uso: python _verify_book.py <bilingue.html> <solo_out.html>
"""
import os
import sys, re
from collections import Counter
from bs4 import BeautifulSoup
import config, main as tr_main
from render import escribir_atomico

EN_SUFFIX = re.compile(r"^[a-z]{3,}(less|ing|ough|ness|ould|ght|tion|ship|ward)$")


def gibberish(t):
    w = t.split()
    if len(w) < 20:
        return False
    if len(set(x.lower() for x in w)) / len(w) < 0.30:
        return True
    c = Counter(x.lower() for x in w if len(x) > 3)
    return bool(c) and c.most_common(1)[0][1] > max(6, len(w) * 0.15)


def residue(t):
    return [w for w in re.findall(r"[a-z]{4,}", t) if EN_SUFFIX.match(w)]


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Uso: python _verify_book.py <bilingue.html> <solo_out.html> [origen]")
    bil, solo = sys.argv[1], sys.argv[2]
    cfg = config.Config()
    if len(sys.argv) > 3:
        cfg.source_lang = sys.argv[3]
    soup = BeautifulSoup(open(bil, encoding="utf-8").read(), "html.parser")
    pairs = []
    for row in soup.select(".row"):
        s = row.select_one(".col.src"); t = row.select_one(".col.tgt")
        if s and t:
            st = s.get_text(" ", strip=True).replace("Original", "", 1).strip()
            tt = t.get_text(" ", strip=True).replace("Español", "", 1).strip()
            pairs.append((st, tt))
    n = len(pairs)
    eng = [i for i, (s, t) in enumerate(pairs) if s and tr_main.bad_translation(s, t, cfg)]
    junk = [i for i, (s, t) in enumerate(pairs) if gibberish(t)]
    resid = Counter()
    for s, t in pairs:
        for w in residue(t):
            resid[w] += 1

    if not n:
        print("✗ entrada inválida: no hay filas traducibles (.row)", flush=True)
        return 1
    print(f"VERIFICACIÓN (determinista) — {n} bloques", flush=True)
    print(f"  · en inglés / truncados: {len(eng)}", flush=True)
    print(f"  · basura / repetición: {len(junk)}", flush=True)
    print(f"  · palabras sueltas en inglés: {sum(resid.values())} ({len(resid)} distintas)", flush=True)
    if resid:
        print("     ej: " + ", ".join(w for w, _ in resid.most_common(15)), flush=True)
    limite_residuos = max(5, n * 0.02)
    if sum(resid.values()) > limite_residuos:
        print(f"  ADVERTENCIA: {sum(resid.values())} residuos; se continúa para completar la pasada", flush=True)

    for el in soup.select(".col.src"): el.decompose()
    for el in soup.select(".lbl"):     el.decompose()
    for el in soup.select(".badge"):   el.decompose()
    for row in soup.select(".row"):
        t = row.select_one(".col.tgt")
        row.replace_with(BeautifulSoup(f"<div class='solo'>{t.decode_contents() if t else ''}</div>",
                                       "html.parser"))
    style = soup.head.find("style") if soup.head else None
    body = soup.body or soup
    html = ('<!doctype html><html lang="es"><head><meta charset="utf-8"><title>libro</title>'
            + (str(style) if style else "") + '</head>'
            '<body>' + "".join(str(c) for c in body.contents) + "</body></html>")
    escribir_atomico(solo, html)

    ok = len(eng) == 0 and len(junk) <= max(2, n * 0.01)
    print(f"  solo-español → {solo}", flush=True)
    print(f"VEREDICTO: {'OK ✓' if ok else 'REVISAR'}", flush=True)
    print("  (nota: la fidelidad de SENTIDO no se verifica por máquina — conviene leer una muestra)", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
