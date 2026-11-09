"""Limpieza conservadora del texto extraído, para traducir mejor.

Arregla artefactos comunes de PDF que ensucian la traducción:
  * guiones de fin de línea:  "funda- mentals" -> "fundamentals",  soft-hyphen "ancient"
  * espacios duros / raros (NBSP, thin/narrow/ideographic...) y espacios múltiples
  * descarta líneas basura (rutas file://, URLs sueltas) que no son contenido

Es CONSERVADORA: no intenta adivinar palabras mal separadas ("o f" -> "of"),
eso se lo deja al LLM. Solo aplica reglas seguras y deterministas.
"""
from __future__ import annotations

import re

_SOFT_HYPHEN = "­"

_WEIRD_SPACE = re.compile(
    "[   -     　]")

_BARE_URL = re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)

_HYPHEN_BREAK = re.compile(r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ-]*)-(\s+)([A-Za-zÀ-ÿ]+)")


def is_junk(text: str) -> bool:
    """True si el bloque es una ruta file:// o una URL suelta (no es contenido)."""
    t = (text or "").strip()
    if not t:
        return False
    if t.lower().startswith("file://"):
        return True
    return bool(_BARE_URL.match(t))


def clean(text: str, glossary=()) -> str:
    if not text:
        return text
    text = text.replace(_SOFT_HYPHEN, "")
    text = _WEIRD_SPACE.sub(" ", text)
    def join(m):
        left, gap, right = m.group(1), m.group(2), m.group(3)
        if ("-" in left or left.lower() == "self" or left + "-" + right in glossary or right.lower() == "and"
                or (right[:1].isupper() and "\n" not in gap)):
            return m.group(0)
        return left + right
    text = _HYPHEN_BREAK.sub(join, text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
