"""Léxico de pronunciación de términos que no se traducen (capa B: nombres fijos por obra).

Carga un corpus JSON  {"lexico": [{original, translit, es_cl, ref, notas}, ...]}
y busca por forma ORIGINAL (griego/hebreo) o por TRANSLITERACIÓN, normalizando
mayúsculas y diacríticos. Si un término está aquí, su pronunciación curada gana
sobre la automática (espeak/aproximada).

Integridad: `validate()` comprueba que no haya claves duplicadas y, si se
declaran tamaños esperados, que coincidan.
"""
from __future__ import annotations

try:
    import fcntl
except ImportError:
    fcntl = None
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter

_NUM_PREFIX = re.compile(r"^\d+\.\s*")


def _norm(s: str) -> str:
    """minúsculas sin diacríticos y sin numeración de lista, para casar
    'λόγος'/'LOGOS'/'korvax' o '68. RIVOTAN'/'RIVOTAN' entre sí."""
    s = _NUM_PREFIX.sub("", s or "")
    d = unicodedata.normalize("NFD", s)
    return "".join(c for c in d if not unicodedata.combining(c)).strip().lower()


_NON_TRANSLIT = {"rey", "duque", "principe", "marques", "presidente", "conde",
                 "carpinterolero"}


def _is_real_translit(v: str) -> bool:
    v = (v or "").strip()
    if not v or v.lower().startswith("suf."):
        return False
    return not all(w in _NON_TRANSLIT for w in v.lower().replace("/", " ").split())


class Lexicon:
    def __init__(self, entries: list | None = None):
        self.by_key: dict[str, dict] = {}
        for e in entries or []:
            keys = [e.get("original", "")]
            if _is_real_translit(e.get("translit", "")):
                keys.append(e["translit"])
            for field in keys:
                k = _norm(field)
                if k and k not in self.by_key:
                    self.by_key[k] = e

    def get(self, term: str) -> dict | None:
        """Entrada del léxico para `term` (por original o translit), o None."""
        return self.by_key.get(_norm(term))

    def __len__(self) -> int:
        return len(self.by_key)


def _read(path: str) -> list:
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("lexico", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def load(path: str) -> Lexicon:
    """Carga el corpus; devuelve un Lexicon vacío si no existe o está roto."""
    return Lexicon(_read(path))


def load_many(paths: list) -> Lexicon:
    """Varios léxicos en orden de prioridad (el primero gana): corpus curado,
    luego el aprendido."""
    entries = []
    for p in paths:
        entries += _read(p)
    return Lexicon(entries)


_META_APRENDIDO = {
    "titulo": "Léxico aprendido: términos intraducibles vistos en los libros traducidos",
    "uso": "Cada término se agrega una vez con su pronunciación automática (auto=true). "
           "Para fijar la correcta: edita es_cl (y opcionalmente ipa) y borra la clave auto. "
           "El corpus curado (terminos.json) siempre tiene prioridad.",
}


def remember(path: str, entries: list) -> int:
    """Agrega al léxico aprendido los términos que aún no conoce (por original o
    translit). Devuelve cuántos agregó. Nunca modifica entradas existentes."""
    if not path or not entries:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".lock", "a", encoding="utf-8") as lock:
        if fcntl:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        data = {"_meta": dict(_META_APRENDIDO), "lexico": []}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict) or not isinstance(data.get("lexico"), list):
                    data = {"_meta": dict(_META_APRENDIDO), "lexico": []}
            except (OSError, json.JSONDecodeError):
                pass
        known = Lexicon(data["lexico"]).by_key
        added = []
        for e in entries:
            k = _norm(e.get("original", ""))
            if k and k not in known:
                known[k] = e
                added.append(e)
        if not added:
            return 0
        data["lexico"].extend(added)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=os.path.dirname(os.path.abspath(path)),
                                             prefix=".lexicon-", suffix=".tmp", delete=False) as f:
                tmp = f.name
                json.dump(data, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
        return len(added)


EXPECTED = {}


def validate(path: str) -> tuple[dict, list]:
    """(conteo_por_tradicion, incidencias). Incidencias = tamaños declarados
que no coinciden o claves duplicadas. Ejecuta `python lexicon.py <corpus.json>`."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lex = data.get("lexico", [])
    counts = Counter(e.get("tradicion", "?") for e in lex)
    issues = [f"{name}: {counts.get(name, 0)}/{n} (esperado)"
              for name, n in EXPECTED.items() if counts.get(name, 0) != n]
    seen, dups = set(), []
    for e in lex:
        fields = [e.get("original", "")]
        if _is_real_translit(e.get("translit", "")):
            fields.append(e["translit"])
        for field in fields:
            k = _norm(field)
            if k and k in seen:
                dups.append(k)
            elif k:
                seen.add(k)
    if dups:
        issues.append(f"claves duplicadas: {len(dups)} (p.ej. {dups[:3]})")
    return dict(counts), issues


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "lexicons/terminos.json"
    counts, issues = validate(p)
    print(f"Léxico: {sum(counts.values())} entradas — {counts}")
    print("Incidencias:", "\n  - ".join([""] + issues) if issues else "ninguna ✓")
