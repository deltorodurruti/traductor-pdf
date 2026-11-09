"""Detección y enmascarado de términos que no se traducen (intraducibles).

Estrategia de enmascarado (funciona con CUALQUIER motor de traducción):
antes de traducir, cada término intraducible se reemplaza por un marcador
`MWTKN<n>` que el traductor no debe tocar; después de traducir se restaura
el término original, intacto y con sus mismas mayúsculas.

Detección:
  1) Glosario del persona y frases de los léxicos (palabras o frases exactas).
  2) Alfabetos no latinos (griego, hebreo, copto, cirílico): se preservan y romanizan.
  3) Auto-detección de tokens en MAYÚSCULAS (opcional, ruidosa).
  4) Identificador de voces: una palabra es término que no se traduce si está en algún léxico
     (corpus curado, voces verificadas, aprendidas) o si no es inglés (ni palabra
     del diccionario ni derivada con sufijo inglés) y además cumple una señal:
     va en MAYÚSCULAS, lleva diacríticos de transliteración (ā ṭ ʿ…), forma
     tirada con otra voz («ZORKAMEL Riv Otan PLUMBATAX»), o es un nombre con
     mayúscula en medio de la frase. Una variante de OCR de una voz conocida
     («Riv0tan») se corrige a la forma del léxico conservando las mayúsculas.

El enmascarado se hace en UNA sola pasada sobre el texto original, resolviendo
solapes, para evitar volver a tocar los marcadores ya insertados.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from romanize import romanize

_NONLATIN_RUN = re.compile(
    "[̀-ͯͰ-ϿЀ-ԯ֐-׿ἀ-῿Ⲁ-⳿]+")

STOPWORDS = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "ANY", "CAN", "HAD",
    "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS", "HOW",
    "MAN", "NEW", "NOW", "OLD", "SEE", "TWO", "WAY", "WHO", "BOY", "DID", "ITS",
    "LET", "PUT", "SAY", "SHE", "TOO", "USE", "WITH", "THIS", "THAT", "THEY",
    "HAVE", "FROM", "WERE", "WHEN", "YOUR", "THEM", "THAN", "THEN", "INTO",
    "ONLY", "OVER", "SUCH", "MOST", "SOME", "WHAT", "WILL", "WOULD", "SHALL",
    "THERE", "WHICH", "THEIR", "ABOUT", "OTHER", "THESE", "UNTO", "UPON",
    "BOOK", "LAW", "PART", "PAGE", "CHAPTER", "SECTION", "INDEX", "CONTENTS",
    "PREFACE", "INTRODUCTION", "APPENDIX", "NOTE", "NOTES", "END", "GOD",
    "USA", "UK", "PDF", "ISBN", "URL", "HTTP", "HTTPS", "WWW", "FAQ", "OK",
    "AND/OR",
}

_DICC: set | None = None
_SUFIJOS_FLEXION = ("ies", "es", "s", "ed", "d", "ing", "ly", "er", "est")
_SUFIJOS_DERIVADOS = ("ical", "ic", "ism", "ist", "ian", "ous", "ity", "tion", "sion", "ment", "ness", "ly", "ive")
_TRANSLIT = set("āīūēōṭṣḥḍẓġḳẖṯʿʾ")
_FIN_FRASE = ".!?:;\"“”'([«¿¡"
_SEPARADOR_TIRADA = re.compile(r"^[\s,:;·.]{1,3}$")
_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]{2,})?", re.UNICODE)


def diccionario_en() -> set:
    """Palabras inglesas (y nombres comunes) en minúscula, del diccionario del sistema."""
    global _DICC
    if _DICC is None:
        try:
            with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as f:
                _DICC = {w.strip().lower() for w in f if w.strip()}
        except OSError:
            _DICC = set()
    return _DICC


def _norm_lex(s: str) -> str:
    """Minúsculas sin diacríticos, para casar «PLUMBATAX»/«PLUMBATAX»/«PLUMBATAX»."""
    d = unicodedata.normalize("NFD", s)
    return "".join(c for c in d if not unicodedata.combining(c)).lower()


def _ocr_norm(s: str) -> str:
    """Confusiones típicas del OCR, para reconocer «Riv0tan» como «RIVOTAN»."""
    t = _norm_lex(s)
    for a, b in (("n1", "m"), ("1n", "m"), ("rn", "m"), ("0", "o"), ("1", "l"), ("|", "l"), ("vv", "w")):
        t = t.replace(a, b)
    return t


try:
    from wordfreq import zipf_frequency as _zipf
except ImportError:
    def _zipf(w: str, lang: str) -> float:
        return 3.0 if w in diccionario_en() else 0.0

ZIPF_CORRIENTE = 2.2
ZIPF_MINIMA = 1.5


def _palabra_inglesa(t: str) -> bool:
    z = _zipf(t, "en")
    return z >= ZIPF_CORRIENTE or (t in diccionario_en() and z >= ZIPF_MINIMA)


def es_ingles(tok: str) -> bool:
    """Inglés corriente (por frecuencia y diccionario), tal cual o quitándole una flexión (-s, -ed, -ing, -ly…).
    El diccionario del sistema trae rarezas como «zorkamel» o «plumbatax»: por eso se exige además frecuencia."""
    t = tok.lower()
    if _palabra_inglesa(t):
        return True
    for suf in _SUFIJOS_FLEXION:
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            raiz = t[:-len(suf)]
            if _palabra_inglesa(raiz) or (suf == "ies" and _palabra_inglesa(raiz + "y")) \
                    or (suf in ("ed", "ing") and _palabra_inglesa(raiz + "e")) \
                    or (suf in ("ed", "ing") and len(raiz) > 3 and raiz[-1] == raiz[-2] and _palabra_inglesa(raiz[:-1])):
                return True
    return False


def es_derivado(tok: str) -> bool:
    """«specialized», «specialized», «specialization»: inglés derivado con sufijo; se traduce, no se congela."""
    t = tok.lower()
    return any(t.endswith(s) and len(t) > len(s) + 2 for s in _SUFIJOS_DERIVADOS)


def cargar_lexicos(rutas: list) -> tuple[dict, list]:
    """({forma normalizada: forma canónica}, frases de varias palabras) desde glosarios .txt y léxicos .json
    (corpus curado: original y translit; voces verificadas: voz; aprendidas: original y translit)."""
    formas: dict[str, str] = {}
    frases: list[str] = []

    def agregar(v: str) -> None:
        v = (v or "").strip()
        if len(v) < 3 or not any(c.isalpha() for c in v) or v.lower().startswith("suf."):
            return
        if " " in v:
            frases.append(v)
        else:
            formas.setdefault(_norm_lex(v), v)
    for r in rutas:
        if not r or not os.path.exists(r):
            continue
        if r.endswith(".json"):
            try:
                d = json.load(open(r, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            entradas = d.get("lexico") or d.get("voces") or [] if isinstance(d, dict) else d
            for e in entradas:
                if isinstance(e, dict):
                    for k in ("voz", "original", "translit"):
                        agregar(str(e.get(k, "")))
                else:
                    agregar(str(e))
        else:
            for linea in open(r, encoding="utf-8"):
                agregar(linea.split("#")[0])
    return formas, frases


def _is_roman(token: str) -> bool:
    """True si el token parece un número romano (I, II, III, IV, XVII, ...)."""
    return bool(re.fullmatch(r"[IVXLCDM]+", token))


def _con_mayusculas_de(modelo: str, forma: str) -> str:
    """La forma canónica con el patrón de mayúsculas del token original."""
    if modelo.isupper():
        return forma.upper()
    if modelo[:1].isupper() and modelo[1:].islower():
        return forma[:1].upper() + forma[1:]
    return forma


@dataclass
class Masker:
    glossary: list
    auto_detect: bool = True
    allcaps_min_len: int = 3
    detect_nonlatin: bool = True
    detect_unknown: bool = False
    lexicon_paths: list = field(default_factory=list)
    _registry: dict = field(default_factory=dict)
    _order: list = field(default_factory=list)
    _meta: dict = field(default_factory=dict)
    lexico: dict = field(default_factory=dict)
    frases_lexico: list = field(default_factory=list)
    correcciones: dict = field(default_factory=dict)
    nuevas: Counter = field(default_factory=Counter)

    def __post_init__(self):
        if self.lexicon_paths:
            self.lexico, self.frases_lexico = cargar_lexicos(self.lexicon_paths)

    def _register(self, term: str, romanization=None) -> int:
        if term not in self._registry:
            self._registry[term] = len(self._registry)
            self._order.append(term)
            self._meta[term] = romanization
        elif romanization and not self._meta.get(term):
            self._meta[term] = romanization
        return self._registry[term]

    def _canonical(self, term: str) -> str:
        """Se conserva la forma del original (sus mayúsculas son parte del texto)."""
        return term

    def _voz_conocida(self, tok: str) -> str | None:
        """Forma canónica si el token es una voz del léxico o una variante de OCR de una; si no, None."""
        if not self.lexico:
            return None
        k = _norm_lex(tok)
        if k in self.lexico:
            return tok
        ko = _ocr_norm(tok)
        if ko != k and ko in self.lexico:
            forma = _con_mayusculas_de(tok, self.lexico[ko])
            self.correcciones[tok] = forma
            return forma
        return None

    def _voces(self, text: str) -> list[tuple[int, int, str, None]]:
        """Paso 4: spans de las términos que no se traducen identificadas en el texto."""
        cands = []
        for m in _TOKEN.finditer(text):
            tok = m.group(0)
            letras = sum(c.isalpha() for c in tok)
            digitos = sum(c.isdigit() for c in tok)
            if letras < 3 or digitos > 1 or _is_roman(tok) or tok.upper() in STOPWORDS:
                continue
            conocida = self._voz_conocida(tok)
            ingles = es_ingles(tok) or es_derivado(tok) or bool(digitos)
            if conocida is None and ingles and not tok.isupper():
                continue
            cands.append([m.start(), m.end(), tok, conocida, ingles])

        def pegada(i: int, j: int) -> bool:
            if not (0 <= j < len(cands)):
                return False
            a, b = (cands[i], cands[j]) if i < j else (cands[j], cands[i])
            return bool(_SEPARADOR_TIRADA.match(text[a[1]:b[0]] or "x"))
        voz = []
        for i, (ini, fin, tok, conocida, ingles) in enumerate(cands):
            prev = text[:ini].rstrip()[-1:]
            medio = bool(prev) and prev not in _FIN_FRASE
            tirada = pegada(i, i - 1) or pegada(i, i + 1)
            senal = (tok.isupper() and len(tok) >= 3) or any(c in _TRANSLIT for c in tok) or tirada \
                or (tok[:1].isupper() and medio)
            if conocida is not None:
                corriente = _zipf(tok.lower(), "en") >= ZIPF_CORRIENTE
                voz.append((senal and not corriente) or (tok.isupper() and len(tok) >= 3)
                           or any(c in _TRANSLIT for c in tok) or not corriente)
            elif ingles:
                voz.append(None)
            else:
                voz.append(senal)
        cambio = True
        while cambio:
            cambio = False
            for i, v in enumerate(voz):
                if v is None and ((pegada(i, i - 1) and voz[i - 1] is True) or (pegada(i, i + 1) and voz[i + 1] is True)):
                    voz[i], cambio = True, True
        voz = [bool(v) for v in voz]
        out = []
        for (ini, fin, tok, conocida, ingles), v in zip(cands, voz):
            if not v:
                continue
            forma = conocida if conocida is not None else tok
            if conocida is None:
                self.nuevas[tok] += 1
            out.append((ini, fin, forma, None))
        return out

    def mask(self, text: str):
        """Devuelve (texto_enmascarado, mapping token->término).

        Cada span es (inicio, fin, término, romanización|None).
        """
        spans: list[tuple[int, int, str, str | None]] = []

        frases = [t for t in self.glossary if t.strip()] + self.frases_lexico
        for term in sorted(set(frases), key=len, reverse=True):
            pat = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
            for m in pat.finditer(text):
                spans.append((m.start(), m.end(), self._canonical(m.group(0)), None))

        if self.detect_nonlatin:
            for m in _NONLATIN_RUN.finditer(text):
                w = m.group(0)
                if sum(c.isalpha() for c in w) >= 2:
                    spans.append((m.start(), m.end(), w, romanize(w) or None))

        if self.auto_detect:
            for m in re.finditer(r"\w+", text, re.UNICODE):
                tok = m.group(0)
                if len(tok) < self.allcaps_min_len:
                    continue
                if not tok.isupper() or not any(c.isalpha() for c in tok):
                    continue
                if tok.upper() in STOPWORDS or _is_roman(tok):
                    continue
                spans.append((m.start(), m.end(), tok, None))

        if self.detect_unknown:
            spans.extend(self._voces(text))

        if not spans:
            return text, {}

        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        chosen = []
        last_end = -1
        for s in spans:
            if s[0] >= last_end:
                chosen.append(s)
                last_end = s[1]

        mapping: dict[str, str] = {}
        out: list[str] = []
        prev = 0
        for start, end, term, rom in chosen:
            out.append(text[prev:start])
            tok = f"MWTKN{self._register(term, rom)}"
            mapping[tok] = term
            out.append(tok)
            prev = end
        out.append(text[prev:])
        return "".join(out), mapping

    @property
    def terms(self) -> list:
        """Términos intraducibles detectados, en orden de aparición."""
        return list(self._order)

    @property
    def romanizations(self) -> dict:
        """{término: romanización} solo para los que tienen (no latinos)."""
        return {t: r for t, r in self._meta.items() if r}
