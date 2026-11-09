"""Pronunciación de términos que no se traducen.

Dos niveles:
  * Si está instalado **espeak-ng** (o espeak): pronunciación real → IPA
    (alfabeto fonético) y, opcionalmente, un **audio** WAV que se puede escuchar.
    Detecta el alfabeto para elegir la voz (griego, hebreo, ruso/cirílico, o inglés
    para la romanización latina).
  * Si no está espeak: una guía silábica **aproximada** y offline
    (p.ej. "ZORKAMEL" → "heh-KAH-teh"), para que siempre haya algo.

espeak-ng es libre y multiplataforma:
  Linux:   sudo apt install espeak-ng
  macOS:   brew install espeak-ng
  Windows: instalador de https://github.com/espeak-ng/espeak-ng/releases
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile

from romanize import romanize

_DIGRAPHS = (("ph", "f"), ("th", "t"), ("kh", "j"), ("ch", "j"), ("gh", "g"), ("tz", "ts"))
_ONSETS = {"br", "cr", "dr", "fr", "gr", "pr", "tr", "bl", "cl", "fl", "gl", "pl",
           "ll", "rr", "qu", "gu"}


def _bin() -> str | None:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def have_espeak() -> bool:
    return _bin() is not None


def _voice_for(term: str) -> str:
    for ch in term:
        o = ord(ch)
        if 0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF:
            return "el"
        if 0x0590 <= o <= 0x05FF:
            return "he"
        if 0x0400 <= o <= 0x04FF:
            return "ru"
    return "la"


def ipa(term: str) -> str | None:
    """IPA vía espeak-ng, o None si no está disponible/falla."""
    b = _bin()
    if not b:
        return None
    try:
        r = subprocess.run([b, "-q", "--ipa", "-v", _voice_for(term), "--", term],
                           capture_output=True, text=True, timeout=10)
        s = (r.stdout or "").strip()
        if " " in s and " " not in term.strip():
            return None
        return s or None
    except Exception:
        return None


def audio_wav(term: str) -> bytes | None:
    """Audio WAV de la pronunciación (bytes), o None."""
    b = _bin()
    if not b:
        return None
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        subprocess.run([b, "-v", _voice_for(term), "-w", tmp, "--", term],
                       capture_output=True, timeout=15)
        with open(tmp, "rb") as fh:
            data = fh.read()
        return data or None
    except Exception:
        return None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def respell(word: str) -> str:
    """Guía silábica aproximada para lectores de español (offline).

    'ZORKAMEL' -> 'he-KA-te'.  Vocales españolas puras + dígrafos (θ→t, φ→f, χ→j).
    Acento (MAYÚSCULAS) en la penúltima sílaba. Aproximación legible, no IPA.
    """
    w = "".join(c for c in word.lower() if c.isalpha())
    if not w:
        return ""
    for a, b in _DIGRAPHS:
        w = w.replace(a, b)
    w = w.replace("y", "i")
    w = re.sub(r"q(?!u)", "k", w)
    parts, onset = [], ""
    for tok in re.findall(r"[aeiou]+|[^aeiou]+", w):
        if tok[0] in "aeiou":
            parts.append(onset + tok); onset = ""
        elif not parts or len(tok) == 1:
            onset = tok
        elif tok[-2:] in _ONSETS:
            parts[-1] += tok[:-2]; onset = tok[-2:]
        else:
            parts[-1] += tok[:-1]; onset = tok[-1]
    if onset:
        if parts:
            parts[-1] += onset
        else:
            parts = [onset]
    stress = len(parts) - 2 if len(parts) >= 2 else 0
    parts[stress] = parts[stress].upper()
    return "-".join(parts)


def pronounce(term: str, romanization: str | None = None, want_audio: bool = False,
              curated: dict | None = None) -> dict:
    """Devuelve {kind, say, guia, ipa, audio_b64, ref}.
    kind ∈ {'curada' (corpus), 'aprendida' (léxico automático, editable),
            'IPA' (alfabeto no latino, voz de su idioma), 'aprox' (guía silábica)}.

    Prioridad: corpus curado > léxico aprendido > automática. En la automática,
    un término en alfabeto latino muestra la guía silábica para lector de
    español ("te-LE-ma") con el IPA de la voz latina como apoyo; uno en griego,
    hebreo o cirílico muestra el IPA de su voz y la guía de su romanización."""
    result = {"kind": None, "say": None, "guia": None, "ipa": None, "audio_b64": None, "ref": None}
    if curated and curated.get("es_cl"):
        result.update(kind="aprendida" if curated.get("auto") else "curada",
                      say=curated["es_cl"], ipa=curated.get("ipa") or None,
                      ref=curated.get("ref") or None)
        return result
    base = romanization or romanize(term) or term
    guia = respell(base)
    ip = ipa(term)
    if _voice_for(term) == "la":
        result.update(kind="aprox", say=guia, guia=guia, ipa=ip)
    elif ip:
        result.update(kind="IPA", say=ip, guia=guia, ipa=ip)
    else:
        result.update(kind="aprox", say=guia, guia=guia)
    if want_audio and ip:
        wav = audio_wav(term)
        if wav:
            result["audio_b64"] = base64.b64encode(wav).decode("ascii")
    return result
