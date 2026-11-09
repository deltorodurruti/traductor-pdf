"""Configuración central del traductor.

`Config` reúne todas las opciones. Los "tipos de libro" ajustan el registro
(instrucción de estilo) que se pasa al LLM para una traducción más adecuada.
"""
from __future__ import annotations

from dataclasses import dataclass


BOOK_TYPES: dict[str, str] = {
    "especializado": (
        "Texto especializado. Mantén un tono preciso y respeta la terminología "
        "especializada sin 'suavizarla'. Preserva los nombres propios y los "
        "términos técnicos en su forma original."
    ),
    "articulo": (
        "Artículo de ciencia, sociología, periodismo o divulgación. Traduce con "
        "claridad y naturalidad, registro informativo y preciso, fiel al original; "
        "respeta la terminología del campo."
    ),
    "libro": (
        "Libro general (narrativa o ensayo). Traducción fluida y fiel al sentido y al "
        "tono del autor."
    ),
    "preguntas": (
        "Formato de preguntas y respuestas / entrevista. Conserva la estructura P/R; "
        "claro y directo."
    ),
    "general": (
        "Texto general. Registro neutro y natural, fiel al sentido."
    ),
}

TIPOS_ESPECIALIZADOS = {"especializado"}


def apply_type_defaults(cfg) -> "Config":
    """Ajusta las opciones de preservación según el tipo de texto."""
    return cfg


@dataclass
class Config:
    input_pdf: str = ""
    output_html: str = ""

    source_lang: str = "en"
    reasoning_effort: str = ""
    target_lang: str = "es"

    backend: str = "ollama"
    edition: str = "simple"
    ollama_model: str = "qwen2.5:7b"
    cloud_model: str = ""
    draft_backend: str = ""
    ollama_url: str = "http://localhost:11434"
    opus_model: str = "Helsinki-NLP/opus-mt-en-es"
    temperature: float = 0.2

    book_type: str = "general"
    tone: str = "fluida"

    review_passes: int = 4
    review_early_stop: bool = True

    cache_translations: bool = True
    cache_solo_lectura: bool = False
    trans_cache_path: str = ".translation_cache.db"

    retries: int = 3
    retry_backoff: float = 2.0

    max_chunk_chars: int = 1200

    preservar_intraducibles: bool = True
    auto_detect_caps: bool = False
    detect_unknown: bool = True
    allcaps_min_len: int = 3
    glossary_path: str = "glossary.txt"
    glossary_extra: str = ""
    lexicon_path: str = "lexicons/terminos.json"
    learned_lexicon_path: str = "lexicons/aprendidas.json"

    pronounce: bool = True
    pronounce_audio: bool = False

    make_pdf: bool = True
    bilingual: bool = True

    ocr_mode: str = "auto"
    ocr_lang: str = "eng"
    ocr_dpi: int = 300
    ocr_psm: int = 3
    ocr_oem: int = 1
    ocr_preprocess: bool = True
    ocr_deskew: bool = True
    scanned_threshold: int = 4
    show_ocr_original: bool = True

    capture_vector: bool = True
    vector_dpi: int = 150
    vector_min_pt: int = 36

    max_pages: int | None = None

    @property
    def register_text(self) -> str:
        return BOOK_TYPES.get(self.book_type, BOOK_TYPES["general"])

    @property
    def es_especializado(self) -> bool:
        return self.book_type in TIPOS_ESPECIALIZADOS
