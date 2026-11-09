"""Caché de traducciones en SQLite: reanudar y no re-traducir.

Guarda cada bloque ya traducido (clave = firma de config + texto origen). Al
re-correr un libro, o si se interrumpió a mitad, los bloques ya hechos se
devuelven al instante y la traducción continúa donde quedó.

Es incremental (commit por escritura, durable ante cortes) y usa un lock +
`check_same_thread=False` para el servidor (varios trabajos a la vez).
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading


class TranslationCache:
    def __init__(self, path: str, enabled: bool = True, escribir: bool = True):
        self.enabled = bool(enabled and path)
        self.escribe = escribir
        self.lock = threading.Lock()
        self.conn = None
        if self.enabled:
            self.conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
            self.conn.execute("CREATE TABLE IF NOT EXISTS tr (k TEXT PRIMARY KEY, v TEXT)")
            self.conn.commit()

    @staticmethod
    def _key(sig: str, source: str) -> str:
        return hashlib.sha1(f"{sig}\x00{source}".encode("utf-8")).hexdigest()

    def get(self, sig: str, source: str):
        if not self.enabled:
            return None
        with self.lock:
            cur = self.conn.execute("SELECT v FROM tr WHERE k=?", (self._key(sig, source),))
            row = cur.fetchone()
        return row[0] if row else None

    def set(self, sig: str, source: str, value: str) -> None:
        if not self.enabled or not self.escribe:
            return
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO tr(k, v) VALUES(?, ?)",
                              (self._key(sig, source), value))
            self.conn.commit()

    def close(self) -> None:
        if self.conn is not None:
            with self.lock:
                self.conn.close()
                self.conn = None


def conserva_mapeo(value: str, mapping: dict) -> bool:
    """Acepta un acierto solo si conserva los términos que hoy se enmascararon."""
    return all(marker in value or term in value for marker, term in mapping.items())


def signature(cfg, glossary: list) -> str:
    """Firma que invalida el caché si cambia algo que afecte la traducción."""
    gl = hashlib.sha1("\n".join(glossary).encode("utf-8")).hexdigest()[:12] if glossary else "-"
    defaults = {"groq": "openai/gpt-oss-120b", "cerebras": "gpt-oss-120b",
                "sambanova": "gpt-oss-120b", "cloudflare": "@cf/openai/gpt-oss-120b"}
    model = cfg.ollama_model if cfg.backend == "ollama" else (
        cfg.opus_model if cfg.backend == "opus" else
        (getattr(cfg, "cloud_model", "") or defaults.get(cfg.backend, cfg.backend)))
    model = model.removeprefix("@cf/").removeprefix("openai/")
    if model == "gpt-oss-120b" and cfg.backend in defaults:
        model = "gpt-oss-120b"
    elif cfg.backend not in defaults:
        model = cfg.backend + ":" + model
    proveedor = "groq" if cfg.backend in defaults else cfg.backend
    voces = "1" if getattr(cfg, "preservar_intraducibles", False) else "0"
    sig = "|" + "|".join([proveedor, model, cfg.book_type, cfg.tone, voces,
                    str(cfg.review_passes), cfg.source_lang, cfg.target_lang, gl])
    draft = getattr(cfg, "draft_backend", "")
    return f"{sig}+{draft}" if draft else sig


def plain_signature(cfg, glossary: list) -> str:
    """Firma del mismo libro sin modo combinado: sus bloques (traducidos
    íntegramente por el LLM) sirven también para el modo combinado."""
    d = getattr(cfg, "draft_backend", "")
    try:
        cfg.draft_backend = ""
        return signature(cfg, glossary)
    finally:
        cfg.draft_backend = d


def _fallback_mismo_motor(cfg, glossary: list) -> list:
    """Firmas cuyos bloques valen para el modo combinado: el mismo libro
    traducido íntegramente por el LLM con cualquier nº de pasadas de revisión
    (todas son al menos tan buenas como borrador + una revisión)."""
    if not getattr(cfg, "draft_backend", ""):
        return []
    p = cfg.review_passes
    try:
        out = []
        for n in (p, 3, 4, 5, 2, 1, 0):
            cfg.review_passes = n
            s = plain_signature(cfg, glossary)
            if s not in out:
                out.append(s)
        return out
    finally:
        cfg.review_passes = p


def fallback_signatures(cfg, glossary: list) -> list:
    out = _fallback_mismo_motor(cfg, glossary)
    return out
