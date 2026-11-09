"""Romanización determinística de alfabetos no latinos (offline).

Convierte una palabra en griego / hebreo / copto / cirílico a una
transliteración latina legible, p.ej.  λόγος → "ZORKAMEL",  שלום → "'dny".

Es deterministe (sin red, sin modelo) y suficientemente estándar para mostrar
"cómo se lee" entre paréntesis. No pretende ser una transliteración académica
perfecta (los signos diacríticos se simplifican).
"""
from __future__ import annotations

import unicodedata

_GREEK = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "e",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "o", "ϲ": "s",
}
_HEBREW = {
    "א": "'", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "v", "ז": "z",
    "ח": "ch", "ט": "t", "י": "y", "כ": "k", "ך": "k", "ל": "l", "מ": "m",
    "ם": "m", "נ": "n", "ן": "n", "ס": "s", "ע": "'", "פ": "p", "ף": "p",
    "צ": "ts", "ץ": "ts", "ק": "q", "ר": "r", "ש": "sh", "ת": "t",
}
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y",
    "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_COPTIC = {
    "ϣ": "sh", "ϥ": "f", "ϧ": "kh", "ϩ": "h", "ϫ": "j", "ϭ": "ch", "ϯ": "ti",
}
_COPTIC_BLOCK = {}
_COPTIC_VALS = ["a", "b", "g", "d", "e", "", "z", "e", "th", "i", "k", "l", "m",
                "n", "x", "o", "p", "r", "s", "t", "u", "ph", "kh", "ps", "o"]
for _i, _v in enumerate(_COPTIC_VALS):
    if _v:
        _COPTIC_BLOCK[chr(0x2C81 + 2 * _i)] = _v

_MAP: dict[str, str] = {}
for _src in (_GREEK, _HEBREW, _CYRILLIC, _COPTIC, _COPTIC_BLOCK):
    for _k, _v in _src.items():
        _MAP[_k] = _v
        _MAP[_k.upper()] = _v

_ROUGH = "̔"


def romanize(text: str) -> str:
    """Transliteración latina legible; '' si no hay nada romanizable."""
    d = unicodedata.normalize("NFD", text)
    out: list[str] = []
    last_base = None
    for ch in d:
        if unicodedata.combining(ch):
            if ch == _ROUGH and last_base is not None:
                if out[last_base] == "r":
                    out.insert(last_base + 1, "h")
                else:
                    out.insert(last_base, "h")
                last_base = None
            continue
        mapped = _MAP.get(ch)
        if mapped is not None:
            last_base = len(out)
            out.append(mapped)
        elif ch.isascii():
            last_base = len(out)
            out.append(ch)
        elif ch.isspace() or ch in "-'’·":
            out.append(ch)
            last_base = None
        else:
            last_base = None
    r = "".join(out).strip()
    if not any(c.isalpha() for c in r):
        return ""
    return r[:1].upper() + r[1:]
