"""Asistente interactivo: arma un objeto Config preguntando al persona.

Cada pregunta trae un valor por defecto (se acepta con Enter). Si no hay TTY
(entrada no interactiva), se devuelven los valores por defecto sin bloquear.
"""
from __future__ import annotations

import sys

from config import Config, BOOK_TYPES


def _interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def _input(prompt: str, default: str) -> str:
    if not _interactive():
        return default
    try:
        ans = input(prompt).strip()
    except EOFError:
        return default
    return ans if ans else default


def ask_text(label: str, default: str) -> str:
    return _input(f"{label} [{default}]: ", default)


def ask_bool(label: str, default: bool) -> bool:
    d = "S/n" if default else "s/N"
    ans = _input(f"{label} ({d}): ", "").lower()
    if not ans:
        return default
    return ans in ("s", "si", "sí", "y", "yes")


def ask_int(label: str, default: int) -> int:
    ans = _input(f"{label} [{default}]: ", str(default))
    try:
        return int(ans)
    except ValueError:
        return default


def ask_choice(label: str, options: list, default: str) -> str:
    print(f"\n{label}")
    for i, (key, desc) in enumerate(options, start=1):
        mark = " (por defecto)" if key == default else ""
        print(f"  {i}) {key}{mark} — {desc}")
    ans = _input("Elige número o nombre", default).strip()
    if ans.isdigit():
        idx = int(ans) - 1
        if 0 <= idx < len(options):
            return options[idx][0]
    for key, _ in options:
        if ans.lower() == key.lower():
            return key
    return default


def _wizard_simple(cfg: Config) -> Config:
    """Asistente mínimo (edición normal): solo el archivo y el formato."""
    print()
    print("   .-----------------------------------------------------------.")
    print("   |                                                           |")
    print("   |            T R A D U C T O R   D E   P D F                 |")
    print("   |                                                           |")
    print("   |          del ingles al espanol, con tus imagenes          |")
    print("   |                                                           |")
    print("   '-----------------------------------------------------------'")
    print()
    print("   El conocimiento no deberia depender de hablar ingles.")
    print()
    print("   " + "-" * 57)
    print()
    cfg.input_pdf = ask_text("   1) Arrastra aqui el PDF y presiona Enter", cfg.input_pdf or "")
    cfg.bilingual = ask_bool(
        "   2) Mostrar el original (pequeno) al lado para comparar?", True)
    cfg.backend = "web"
    cfg.book_type = "general"
    cfg.ocr_mode = "auto"
    cfg.preservar_intraducibles = False
    print("\n   Traduciendo, espera un momento...\n")
    return cfg


def run_wizard(preset: Config | None = None) -> Config:
    cfg = preset or Config()
    if getattr(cfg, "edition", "simple") == "simple":
        return _wizard_simple(cfg)
    print("=" * 72)
    print("  TRADUCTOR DE LIBROS  ·  asistente de configuración (edición completa)")
    print("=" * 72)

    cfg.input_pdf = ask_text("Ruta del PDF o carpeta con PDFs", cfg.input_pdf or "./libro.pdf")

    cfg.book_type = ask_choice(
        "¿Qué tipo de libro es? (ajusta el registro de la traducción)",
        [(k, v.split(".")[0]) for k, v in BOOK_TYPES.items()],
        cfg.book_type)

    cfg.tone = ask_choice(
        "¿Cómo quieres la traducción?",
        [("fluida", "natural y legible, fiel al sentido"),
         ("literal", "lo más literal posible, respeta estructura y términos")],
        cfg.tone)

    cfg.bilingual = ask_choice(
        "¿Qué quieres en el resultado?",
        [("bilingue", "traducción + original lado a lado (para comparar)"),
         ("solo", "solo la traducción")],
        "bilingue" if cfg.bilingual else "solo") == "bilingue"

    cfg.backend = ask_choice(
        "Motor de traducción",
        [("web", "Google gratis: rápido y buena calidad, necesita internet (recomendado)"),
         ("ollama", "LLM local offline, más lento en CPU pero privado"),
         ("opus", "OPUS-MT (NMT dedicado, offline)"),
         ("argos", "Argos Translate (ligero, offline)"),
         ("dummy", "prueba sin traducir (para verificar el flujo)")],
        cfg.backend)
    if cfg.backend == "ollama":
        cfg.ollama_model = ask_text("  Modelo de Ollama", cfg.ollama_model)
        cfg.ollama_url = ask_text("  URL de Ollama", cfg.ollama_url)
        cfg.review_passes = ask_int("  Pasadas de revisión por bloque", cfg.review_passes)

    cfg.ocr_mode = ask_choice(
        "¿Los PDFs son de texto copiable o escaneados (solo imagen)?",
        [("auto", "detectar automáticamente por página (recomendado)"),
         ("force", "forzar OCR en todas las páginas"),
         ("off", "nunca usar OCR (solo texto copiable)")],
        cfg.ocr_mode)
    if cfg.ocr_mode != "off":
        cfg.ocr_lang = ask_text("  Idioma del texto ORIGINAL para OCR (código Tesseract)", cfg.ocr_lang)

    cfg.preservar_intraducibles = ask_bool(
        "¿Preservar términos que no se traducen sin traducir?", cfg.preservar_intraducibles)
    if cfg.preservar_intraducibles:
        cfg.auto_detect_caps = ask_bool(
            "  ¿Auto-detectar MAYÚSCULAS como intraducibles? (puede marcar títulos por error)",
            cfg.auto_detect_caps)
        cfg.glossary_path = ask_text("  Archivo de glosario (una palabra/frase por línea)",
                                     cfg.glossary_path)

    n = ask_int("¿Cuántas páginas traducir? (0 = todas, o un número para probar)",
                cfg.max_pages or 0)
    cfg.max_pages = None if n <= 0 else n

    print("\n" + "-" * 72)
    print("Resumen:")
    print(f"  entrada={cfg.input_pdf}  tipo={cfg.book_type}  tono={cfg.tone}")
    print(f"  motor={cfg.backend}" + (f" ({cfg.ollama_model}, {cfg.review_passes} revisiones)"
                                       if cfg.backend == "ollama" else ""))
    print(f"  ocr={cfg.ocr_mode}  preservar={cfg.preservar_intraducibles}")
    print(f"  páginas={'todas' if cfg.max_pages is None else cfg.max_pages}")
    print("-" * 72)
    if not ask_bool("¿Comenzar?", True):
        print("Cancelado.")
        raise SystemExit(0)
    return cfg
