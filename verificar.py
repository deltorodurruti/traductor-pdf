#!/usr/bin/env python3
"""Verifica una traducción bilingüe con 3 métodos, de barato a caro:

  1) Filtro (instantáneo, sin red): vacíos, inglés sin traducir, largo anómalo.
  2) Round-trip (Google): re-traduce ES->EN y compara con el original;
     marca los bloques que cambiaron de SIGNIFICADO.
  3) Llama (Ollama): juzga SOLO los bloques que 1 o 2 marcaron sospechosos
     (no los cientos), así es rápido aun en CPU.

Uso:  python3 verificar.py "<libro>.bilingue.html" [--sample N] [--no-llama]
Sale con código 0 siempre; el informe es para leer, no para romper un pipeline.
"""
from __future__ import annotations
import argparse
import os, sys, re, html as _html, json, random, urllib.request
from difflib import SequenceMatcher

import remoto

OLLAMA = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b"
GEMINI_MODEL = "gemini-2.5-flash"

_EN = set("the of and to in a is that it was for with as his he be not by this "
          "but they which you have from are on at or an we all their her".split())


def _clean(x: str) -> str:
    x = re.sub(r"<span class='lbl'>.*?</span>", "", x, flags=re.S)
    x = re.sub(r"<[^>]+>", " ", x)
    return re.sub(r"\s+", " ", _html.unescape(x)).strip()


def pairs_from_html(path: str) -> list[tuple[str, str]]:
    doc = open(path, encoding="utf-8").read()
    out = []
    for m in re.finditer(
            r"<div class='col src'>(.*?)</div>\s*<div class='col tgt'>(.*?)</div>",
            doc, re.S):
        s, t = _clean(m.group(1)), _clean(m.group(2))
        if s or t:
            out.append((s, t))
    return out


_BOILER = re.compile(
    r"rights reserved|all rights|copyright|\bisbn\b|first published|printed in|"
    r"library of congress|weiser|red wheel|no part of this|may be reproduced|"
    r"derechos reservados|impreso en|ninguna parte", re.I)


def _is_boilerplate(s: str) -> bool:
    """Créditos/legales/colofón: no es contenido, se ignora en la verificación."""
    return bool(_BOILER.search(s))


def _looks_english(t: str) -> bool:
    w = re.findall(r"[a-zA-Z]+", t.lower())
    if len(w) < 6:
        return False
    return sum(x in _EN for x in w) / len(w) > 0.20


def filtro(pairs) -> dict[int, str]:
    """Método 1: chequeos instantáneos. Devuelve {índice: motivo}."""
    flags = {}
    for i, (s, t) in enumerate(pairs):
        if _is_boilerplate(s):
            continue
        if s and not t.strip():
            flags[i] = "traducción vacía"
        elif s and (len(t) / max(1, len(s)) < 0.5 or len(t) / max(1, len(s)) > 2.2):
            flags[i] = f"largo anómalo (x{len(t)/max(1,len(s)):.1f})"
        elif _looks_english(t):
            flags[i] = "inglés sin traducir"
    return flags


def _jaccard(a: str, b: str) -> float:
    wa = set(re.findall(r"[a-z]+", a.lower()))
    wb = set(re.findall(r"[a-z]+", b.lower()))
    return len(wa & wb) / len(wa | wb) if (wa | wb) else 1.0


def round_trip(pairs, idxs) -> dict[int, str]:
    """Método 3: ES->EN de vuelta y comparar con el original (sentido)."""
    from deep_translator import GoogleTranslator
    back = GoogleTranslator(source="es", target="en")
    flags = {}
    for i in idxs:
        s, t = pairs[i]
        if len(s) < 40 or not t.strip() or _is_boilerplate(s):
            continue
        try:
            en2 = back.translate(t[:4900]) or ""
        except Exception:
            continue
        sim = max(_jaccard(s, en2), SequenceMatcher(None, s.lower(), en2.lower()).ratio())
        if sim < 0.30:
            flags[i] = f"sentido divergente (sim {sim:.2f})"
    return flags


def _ollama(s: str, t: str) -> str:
    prompt = (f"Original (inglés):\n{s[:1200]}\n\nTraducción (español):\n{t[:1200]}\n\n"
              "¿La traducción conserva el sentido y suena natural? "
              "Responde SOLO 'OK' o 'PROBLEMA: <razón breve>'.")
    data = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(OLLAMA, data=data,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300))["response"].strip()


def _gemini(s: str, t: str) -> str:
    """Juez de alta calidad vía Gemini (lee la key de un archivo privado)."""
    key = remoto.clave_gemini()
    if not key:
        return "(sin key Gemini)"
    prompt = (f"Original (inglés):\n{s[:1500]}\n\nTraducción (español):\n{t[:1500]}\n\n"
              "¿La traducción conserva el sentido y suena natural en español? "
              "Responde SOLO 'OK' o 'PROBLEMA: <razón breve>'.")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    r = json.load(urllib.request.urlopen(req, timeout=60))
    return r["candidates"][0]["content"]["parts"][0]["text"].strip()


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("path", nargs="?")
    parser.add_argument("--sample", type=int, default=40)
    parser.add_argument("--no-llama", action="store_true")
    parser.add_argument("--gemini", action="store_true")
    parser.add_argument("--yes-cloud", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    path = args.path
    if not path:
        print("Uso: python3 verificar.py <libro>.bilingue.html [--sample N] [--no-llama]")
        return
    sample = args.sample
    use_gemini = args.gemini
    if use_gemini:
        try:
            remoto.exigir_consentimiento_nube("Verificación con Gemini", aceptado=args.yes_cloud)
        except remoto.SinConsentimiento as e:
            print(e)
            use_gemini = False
    use_llama = not args.no_llama and not use_gemini

    pairs = pairs_from_html(path)
    print(f"Bloques leídos: {len(pairs)}")

    f1 = filtro(pairs)
    print(f"\n[1] Filtro instantáneo → {len(f1)} sospechosos")
    for i, r in list(f1.items())[:12]:
        print(f"    · bloque {i}: {r}")

    universe = set(f1)
    try:
        remoto.exigir_consentimiento_nube("Verificación round-trip con Google",
                                          aceptado=args.yes_cloud)
    except remoto.SinConsentimiento as e:
        print(f"\n[3] Round-trip omitido: {e}")
        f3 = {}
    else:
        universe |= set(random.sample(range(len(pairs)), min(sample, len(pairs))))
        f3 = round_trip(pairs, sorted(universe))
    print(f"\n[3] Round-trip (Google, {len(universe)} revisados) → {len(f3)} con sentido dudoso")
    for i, r in list(f3.items())[:12]:
        print(f"    · bloque {i}: {r}")

    flagged = sorted(set(f1) | set(f3))
    if not use_llama and not use_gemini:
        print(f"\n[2] Juicio omitido (--no-llama). Total sospechosos: {len(flagged)}")
        return
    judge, name = (_gemini, "Gemini") if use_gemini else (_ollama, "Llama")
    est = "rápido" if use_gemini else f"~{len(flagged)*90//60} min en CPU"
    print(f"\n[2] {name} juzga {len(flagged)} bloques sospechosos ({est})...")
    problemas = []
    for n, i in enumerate(flagged, 1):
        s, t = pairs[i]
        try:
            v = judge(s, t)
        except Exception as e:
            v = f"(sin veredicto: {e})"
        mark = "✔" if v.upper().startswith("OK") else "✗"
        print(f"    {mark} [{n}/{len(flagged)}] bloque {i}: {v[:90]}")
        if not v.upper().startswith("OK"):
            problemas.append((i, v))

    print("\n" + "=" * 60)
    print(f"RESUMEN: {len(pairs)} bloques | {len(flagged)} revisados por {name} | "
          f"{len(problemas)} con problema real")
    print("=" * 60)


if __name__ == "__main__":
    main()
