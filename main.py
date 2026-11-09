"""Traductor de libros PDF: bilingüe lado a lado, offline, con OCR, preservación
de términos intraducibles y revisión multi-pasada.

Uso interactivo (recomendado):
    python main.py

Uso directo (sin asistente):
    python main.py libro.pdf --yes --engine ollama
    python main.py ./carpeta_libros --yes --engine dummy --ocr auto
"""
from __future__ import annotations

import argparse
import datetime
import glob
import os
import re
import sys
import tempfile
import time
import requests

import extract
import lexicon
import ocr as ocr_mod
import pronounce as pron_mod
import render
import remoto
import transcache
from intraducibles import Masker
from config import Config, apply_type_defaults
from interactive import run_wizard
from translate import CloudBackend, lang_name, make_backend, translate_and_review

REMOTE_BACKENDS = set(CloudBackend.PROVIDERS) | {"web", "google", "edge"}
ENGINE_CHOICES = ["ollama", *sorted(CloudBackend.PROVIDERS), "web", "edge", "argos", "opus", "dummy"]


def _remote_backends(backend: str, draft_backend: str = "") -> list[str]:
    return list(dict.fromkeys(m for m in (backend, draft_backend) if m in REMOTE_BACKENDS))


def _fix_ssl_certs() -> None:
    """En el .exe empaquetado, apuntar requests/SSL a los certificados incluidos
    (evita el fallo de HTTPS que cerraba la ventana al traducir)."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import certifi
        ca = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
    except Exception:
        pass


def _learned_path(cfg: Config) -> str:
    """Léxico aprendido: junto al programa (o donde diga la config si es absoluta)."""
    p = cfg.learned_lexicon_path
    if os.path.isabs(p):
        return p
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    return os.path.join(base, p)


def _resource(path: str) -> str:
    """Ruta a un archivo de datos que funciona suelto Y empaquetado (PyInstaller).
    Si no existe tal cual (cwd), lo busca junto al ejecutable/script o en _MEIPASS."""
    if os.path.exists(path):
        return path
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    cand = os.path.join(base, path)
    return cand if os.path.exists(cand) else path


def load_glossary(path: str) -> list:
    if not path or not os.path.exists(path):
        return []
    terms = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line)
    return terms


def resolve_inputs(path: str) -> list:
    path = (path or "").strip().strip('"').strip("'").strip()
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "*.pdf")))
    return [path] if path else []


def _default_out(pdf_path: str, cfg: Config) -> str:
    """Ruta de salida por defecto. En la edición simple, al Escritorio como
    '<nombre> traducido.html' (fácil de encontrar)."""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    if getattr(cfg, "edition", "") == "simple":
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop):
            return os.path.join(desktop, f"{stem} traducido.html")
    return os.path.splitext(pdf_path)[0] + ".bilingue.html"


def make_masker(cfg: Config, glossary: list) -> Masker:
    especializado = cfg.es_especializado
    lexicos = [_resource(cfg.lexicon_path), _resource("lexicons/voces_verificadas.json"), _learned_path(cfg)]
    return Masker(
        glossary=glossary if (cfg.preservar_intraducibles and especializado) else [],
        auto_detect=cfg.preservar_intraducibles and cfg.auto_detect_caps and especializado,
        allcaps_min_len=cfg.allcaps_min_len,
        detect_nonlatin=cfg.preservar_intraducibles,
        detect_unknown=cfg.preservar_intraducibles and cfg.detect_unknown and especializado,
        lexicon_paths=lexicos if (cfg.preservar_intraducibles and especializado) else [],
    )


def _group_texts(texts: list, max_chars: int) -> list:
    """Agrupa textos consecutivos en chunks de hasta max_chars (0 = sin agrupar).
    Mejora la coherencia y reduce el nº de llamadas al modelo."""
    if not max_chars or max_chars <= 0:
        return [t for t in texts if t]
    chunks, buf, size = [], [], 0
    for t in texts:
        if not t:
            continue
        if buf and size + len(t) > max_chars:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(t)
        size += len(t) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


_EN_FUNC = re.compile(r"\b(the|and|of|to|with|which|from|this|that|for|is|are|was|"
                      r"were|be|by|as|it|his|her|not|but|had)\b", re.I)
_FR_FUNC = re.compile(r"\b(et|il|ils|elle|ne|pas|au|du|des|est|dans|avec|vous|nous|cette|sont|leur|"
                      r"mais|pour|qui|aux|était|être|ont|cela)\b", re.I)
_SRC_FUNC = {"en": (_EN_FUNC, "áéíóúñ¿¡"), "fr": (_FR_FUNC, "áíóúñ¿¡")}


def bad_translation(src: str, out: str, cfg: Config) -> bool:
    """¿La 'traducción' es en realidad un fallo? Detecta tres modos que antes
    pasaban en silencio: salida vacía, texto truncado (el modelo cortó un bloque
    largo) y texto que quedó en el idioma ORIGEN (en->es). Conservador: no marca
    traducciones buenas."""
    s, o = (src or "").strip(), (out or "").strip()
    if not s:
        return False
    if not o:
        return True
    sw, ow = len(s.split()), len(o.split())
    if sw >= 20 and ow < 0.5 * sw:
        return True
    if cfg.source_lang in _SRC_FUNC and cfg.target_lang == "es" and len(o) >= 40:
        rx, es_marks = _SRC_FUNC[cfg.source_lang]
        if len(rx.findall(o)) >= 4 and not any(c in o for c in es_marks):
            return True
    if cfg.target_lang == "es" and cfg.source_lang not in _SRC_FUNC and len(o) >= 40 and s == o:
        return True
    return False


_EN_RESIDUE = re.compile(r"^[a-z]{3,}(less|ing|ough|ness|ould|ght|tion|ship|ward)$")


def residue_count(text: str) -> int:
    """Palabras sueltas que parecen inglés (sufijos que en español casi no existen:
    -less/-ing/-tion/-ship…). Gatilla la corrección de residuo (p. ej. 'colorless',
    'worship', o capitulares partidas como 'onversation')."""
    return sum(1 for w in re.findall(r"[a-z]{4,}", text) if _EN_RESIDUE.match(w))


_REFUSAL = re.compile(r"lo siento|no puedo (cumplir|ayudar|hacer|proporcionar|generar)|"
                      r"as an ai|i cannot|i'?m sorry|¿hay algo más|no es posible", re.I)


def _is_refusal(text: str) -> bool:
    """El modelo chico a veces responde con una negativa en vez de corregir."""
    return bool(_REFUSAL.search(text[:200]))


def html_to_pdf(html_path: str, log=print) -> str:
    """HTML -> PDF. Solo-traducción: una hoja por página del original (hojas.py).
    Bilingüe: Chrome headless (fiel al CSS); fallback a cupsfilter (macOS)."""
    import shutil
    import subprocess
    pdf_path = os.path.splitext(html_path)[0] + ".pdf"
    try:
        import hojas
        if hojas.es_solo(html_path):
            return hojas.maquetar(html_path, pdf_path, log=log)
    except Exception as e:
        log(f"  ⚠ maquetado hoja a hoja falló ({e}); uso el PDF simple")
    chrome = render.find_chrome()
    pdf_dir = os.path.dirname(os.path.abspath(pdf_path)) or "."
    fd, tmp_pdf = tempfile.mkstemp(prefix=".pdf-translator-", suffix=".pdf", dir=pdf_dir)
    os.close(fd)
    try:
        if chrome:
            subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                            f"--print-to-pdf={tmp_pdf}", "file://" + os.path.abspath(html_path)],
                           check=True, capture_output=True, timeout=300)
        elif shutil.which("cupsfilter"):
            with open(tmp_pdf, "wb") as f:
                subprocess.run(["cupsfilter", html_path], check=True, stdout=f, timeout=300)
        else:
            log("  ⚠ sin motor de PDF (instala Chrome); queda solo el HTML")
            return ""
        with open(tmp_pdf, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise RuntimeError("el generador no produjo un PDF válido")
        os.replace(tmp_pdf, pdf_path)
        return pdf_path
    except Exception as e:
        log(f"  ⚠ no se pudo generar el PDF ({e}); queda el HTML")
        return ""
    finally:
        try:
            os.remove(tmp_pdf)
        except OSError:
            pass


def process_pdf(pdf_path: str, cfg: Config, backend, glossary: list,
                ocr_ok: bool, today: str, log=print, draft=None) -> dict:
    log(f"\n» Procesando: {pdf_path}")
    pages = extract.extract_document(
        pdf_path, max_pages=cfg.max_pages, ocr_mode=cfg.ocr_mode,
        scanned_threshold=cfg.scanned_threshold, ocr_dpi=cfg.ocr_dpi,
        capture_vector=cfg.capture_vector, vector_dpi=cfg.vector_dpi,
        vector_min_pt=cfg.vector_min_pt)
    log(f"  {len(pages)} páginas extraídas")

    masker = make_masker(cfg, glossary)
    cache = transcache.TranslationCache(cfg.trans_cache_path, cfg.cache_translations,
                                        escribir=not cfg.cache_solo_lectura)
    sig = transcache.signature(cfg, glossary if cfg.es_especializado else [])
    sig_fallbacks = transcache.fallback_signatures(cfg, glossary if cfg.es_especializado else [])
    rendered = []
    counters = {"blocks": 0, "passes": 0, "lost": 0, "errors": 0, "cached": 0,
                "untranslated": 0, "scanned_total": 0, "scanned_empty": 0}

    def translate_block(text: str) -> str:
        """Traduce un bloque con caché (reanudar) y degradación con gracia.
        Verifica la salida: si quedó en inglés o truncada, reintenta; y si aun así
        falla, la CUENTA y NO la cachea (para que un re-run la repare). Ignora
        además entradas de caché 'envenenadas' de corridas viejas (inglés cacheado)."""
        masked, mapping = masker.mask(text)
        def cache_hit(value):
            return value if value is not None and transcache.conserva_mapeo(value, mapping) else None

        hit = cache_hit(cache.get(sig, text))
        for s in sig_fallbacks:
            if hit is not None:
                break
            hit = cache_hit(cache.get(s, text))
        if hit is not None and not bad_translation(text, hit, cfg):
            counters["cached"] += 1
            return hit
        last_e, best = None, text
        for intento in range(max(1, cfg.retries)):
            try:
                trans, lost, passes = translate_and_review(
                    masked, mapping, backend, cfg.review_passes, cfg.review_early_stop,
                    draft_backend=draft)
                if not lost and not bad_translation(text, trans, cfg):
                    r0 = residue_count(trans)
                    if r0:
                        try:
                            fixed = backend.fix_residue(trans)
                            if (fixed and all(v in fixed for v in mapping.values())
                                    and not bad_translation(text, fixed, cfg)
                                    and residue_count(fixed) < r0
                                    and 0.7 * len(trans) <= len(fixed) <= 1.4 * len(trans)
                                    and not _is_refusal(fixed)):
                                trans = fixed
                        except Exception:
                            pass
                        if getattr(backend, "diferido", False):
                            counters["blocks"] += 1
                            return trans
                    counters["blocks"] += 1
                    counters["passes"] += passes
                    counters["lost"] += len(lost)
                    cache.set(sig, text, trans)
                    return trans
                best, last_e = trans, "salida en idioma origen, truncada o con voces perdidas"
            except Exception as e:
                if isinstance(e, requests.HTTPError) and getattr(e.response, "status_code", 0) in (400, 401, 402, 403, 404, 422):
                    raise
                last_e = e
            if intento + 1 < max(1, cfg.retries):
                time.sleep(cfg.retry_backoff * (intento + 1))
        counters["errors"] += 1
        counters["untranslated"] += 1
        log(f"    ⚠ bloque no traducido correctamente tras {cfg.retries} intentos "
            f"({last_e}); se conserva y NO se cachea — re-ejecuta para repararlo")
        return text

    total = len(pages)
    def bar(i):
        f = i / total if total else 1
        return f"[pág {i}/{total} {'█'*int(f*14)}{'░'*(14-int(f*14))} {int(f*100):>3}%]"

    try:
        for i, pg in enumerate(pages, 1):
            if pg.mode == "scanned":
                page_dict = {"number": pg.number, "mode": "scanned",
                             "page_image": pg.page_image,
                             "page_image_ext": pg.page_image_ext, "rows": []}
                paras = []
                if ocr_ok:
                    try:
                        paras = ocr_mod.ocr_paragraphs(
                            pg.page_image, cfg.ocr_lang, psm=cfg.ocr_psm,
                            oem=cfg.ocr_oem, preprocess=cfg.ocr_preprocess,
                            deskew=cfg.ocr_deskew)
                    except Exception as e:
                        counters["errors"] += 1
                        log(f"    ⚠ OCR falló en la página {pg.number} ({e}); "
                            f"se muestra solo la imagen")
                for chunk in _group_texts(paras, cfg.max_chunk_chars):
                    page_dict["rows"].append(
                        ("text", chunk if cfg.show_ocr_original else "", translate_block(chunk)))
                counters["scanned_total"] += 1
                if not page_dict["rows"]:
                    counters["scanned_empty"] += 1
                rendered.append(page_dict)
                log(f"  {bar(i)} pág {pg.number} [escaneada] {len(page_dict['rows'])} bloques OCR")
            else:
                rows, nb, run = [], 0, []
                for it in pg.items:
                    if it.type == "text":
                        run.append(it.text)
                    else:
                        for chunk in _group_texts(run, cfg.max_chunk_chars):
                            rows.append(("text", chunk, translate_block(chunk)))
                            nb += 1
                        run = []
                        rows.append(("image", it.data, it.ext))
                for chunk in _group_texts(run, cfg.max_chunk_chars):
                    rows.append(("text", chunk, translate_block(chunk)))
                    nb += 1
                rendered.append({"number": pg.number, "mode": "text", "rows": rows})
                log(f"  {bar(i)} pág {pg.number} [texto] {nb} bloques")
    finally:
        cache.close()

    terms = masker.terms
    pronunciations = {}
    roms = masker.romanizations
    if cfg.pronounce and terms:
        learned = _learned_path(cfg)
        lex = lexicon.load_many([_resource(cfg.lexicon_path), learned])
        for term in terms:
            pronunciations[term] = pron_mod.pronounce(
                term, roms.get(term), want_audio=cfg.pronounce_audio,
                curated=lex.get(term))
        nuevos = [{"original": t, "translit": roms.get(t) or "", "es_cl": pr.get("guia") or pr["say"],
                   "ipa": pr.get("ipa") or "", "auto": True, "fuente": os.path.basename(pdf_path),
                   "notas": "pronunciación automática; corrige es_cl y borra 'auto' para fijarla"}
                  for t, pr in pronunciations.items() if pr["kind"] in ("aprox", "IPA")]
        n = lexicon.remember(learned, nuevos)
        if n:
            log(f"  léxico aprendido: {n} términos nuevos → {learned}")

    out = cfg.output_html or _default_out(pdf_path, cfg)
    render.render_html(rendered, terms, out,
                       title=os.path.basename(pdf_path),
                       src_name=lang_name(cfg.source_lang),
                       tgt_name=lang_name(cfg.target_lang),
                       romanizations=roms, pronunciations=pronunciations,
                       bilingual=cfg.bilingual)
    log(f"  ✔ Generado: {out}")
    u = getattr(backend, "usage", None)
    if u and u.get("calls"):
        log(f"  tokens de nube: {u['prompt'] + u['completion']:,} ({u['calls']} llamadas; "
            f"{u['prompt']:,} entrada + {u['completion']:,} salida)".replace(",", "."))
    if cfg.make_pdf:
        pdf_out = html_to_pdf(out, log)
        if pdf_out:
            log(f"  ✔ PDF: {pdf_out}")
    return {"out": out, "blocks": counters["blocks"], "passes": counters["passes"],
            "lost": counters["lost"], "errors": counters["errors"],
            "cached": counters["cached"], "terms": len(terms),
            "untranslated": counters["untranslated"],
            "scanned_total": counters["scanned_total"],
            "scanned_empty": counters["scanned_empty"]}


def build_config_from_args(args) -> Config:
    cfg = Config()
    if args.input:
        cfg.input_pdf = args.input
    if args.engine:
        cfg.backend = args.engine
    if args.origen:
        cfg.source_lang = args.origen
    if args.razonamiento:
        cfg.reasoning_effort = args.razonamiento
    if args.model:
        cfg.ollama_model = args.model
    if args.cloud_model:
        cfg.cloud_model = args.cloud_model
    if args.glosario_extra:
        cfg.glossary_extra = args.glosario_extra
    if args.borrador:
        cfg.draft_backend = args.borrador
        if args.review_passes is None:
            cfg.review_passes = 1
    if args.calidad:
        cfg.review_passes = args.calidad
    if args.review_passes is not None:
        cfg.review_passes = max(0, args.review_passes)
    if args.book_type:
        cfg.book_type = args.book_type
    if args.tone:
        cfg.tone = args.tone
    if args.ocr:
        cfg.ocr_mode = args.ocr
    if args.out:
        cfg.output_html = args.out
    if args.max_pages is not None:
        cfg.max_pages = args.max_pages if args.max_pages > 0 else None
    if args.ocr_dpi:
        cfg.ocr_dpi = args.ocr_dpi
    if args.no_diagramas:
        cfg.capture_vector = False
    if args.no_deskew:
        cfg.ocr_deskew = False
    if args.chunk_chars is not None:
        cfg.max_chunk_chars = args.chunk_chars
    if args.no_cache:
        cfg.cache_translations = False
    if args.detect_caps:
        cfg.auto_detect_caps = True
    if args.no_preserve:
        cfg.preservar_intraducibles = False
    if args.no_pdf:
        cfg.make_pdf = False
    if args.solo:
        cfg.bilingual = False
    if args.edicion:
        cfg.edition = args.edicion
    return cfg


def _menu_completo() -> str:
    """Menú de la edición completa."""
    print("  1) Traducir un PDF")
    return "traducir"


def _ocr_hint():
    from ocr import ocr_available
    ok, _ = ocr_available()
    return ("Tesseract está instalado: lo más probable es que sean hojas en blanco" if ok
            else "OCR no disponible; instala Tesseract (ver README)")

def main(argv=None):
    _fix_ssl_certs()
    ap = argparse.ArgumentParser(
        description="Traductor de libros PDF a español, bilingüe lado a lado y offline "
                    "(con OCR y preservación de términos).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ejemplos:\n"
               "  python main.py                                 asistente interactivo\n"
               "  python main.py libro.pdf --yes                 valores por defecto (Ollama)\n"
               "  python main.py libro.pdf --yes --book-type articulo\n"
               "  python main.py ./carpeta --yes --ocr auto      todos los PDF de la carpeta\n"
               "  python main.py libro.pdf --yes --engine dummy    prueba sin Ollama\n")
    ap.add_argument("input", nargs="?", help="PDF o carpeta con PDFs")
    ap.add_argument("--yes", action="store_true", help="omitir el asistente interactivo")
    ap.add_argument("--engine",
                    choices=ENGINE_CHOICES,
                    help="motor: ollama (local, privado) · groq/cerebras/openrouter/gemini/mistral/cloudflare "
                         "(NUBE, rápido, el texto sale del equipo) · web/edge (traductor en línea gratis, "
                         "sin clave) · dummy (prueba)")
    ap.add_argument("--origen", choices=["en", "fr", "la", "de", "it", "pt"], default=None,
                    help="idioma del texto original (def: en)")
    ap.add_argument("--razonamiento", choices=["low", "medium", "high"], default=None,
                    help="nube: esfuerzo de razonamiento (gpt-oss); low gasta mucho menos cuota")
    ap.add_argument("--yes-cloud", action="store_true",
                    help="confirmar de antemano el uso de la nube (para libros públicos; omite la pregunta)")
    ap.add_argument("--cloud-model", help="modelo para el motor de nube (def: el del proveedor)")
    ap.add_argument("--glosario-extra", metavar="ARCHIVO",
                    help="glosario adicional (una palabra o frase por línea) que se SUMA al base solo "
                         "en esta corrida: términos intraducibles propios del libro")
    ap.add_argument("--borrador", "--draft", choices=["edge", "web", "argos", "opus"], default=None,
                    help="modo combinado: este motor gratuito hace el borrador y el --engine (LLM) "
                         "solo lo revisa contra el original (una pasada salvo --review-passes): "
                         "la mitad de tokens de cuota")
    ap.add_argument("--model", help="modelo de Ollama (def: qwen2.5:32b)")
    ap.add_argument("--calidad", "--nivel", type=int, choices=[1, 2, 3, 4, 5], default=None,
                    help="nivel de calidad 1-5 (1 rápido · 2 mejor · 3 equilibrado · 4 bueno · "
                         "5 máximo). A más nivel, más pasadas de revisión: mejor traducción, más lento")
    ap.add_argument("--review-passes", type=int, default=None,
                    help="control fino: pasadas de revisión por bloque (0 = sin revisión: ~2,5x "
                         "menos tokens; solo recomendable con modelos grandes de nube). "
                         "Si se indica, anula a --calidad")
    ap.add_argument("--edicion", choices=["simple", "completa"], default=None,
                    help="edición simple o completa del flujo de salida")
    ap.add_argument("--book-type", "--tipo",
                    choices=["especializado", "articulo", "libro", "preguntas", "general"],
                    help="tipo de texto (def: general; especializado preserva nombres propios y términos técnicos)")
    ap.add_argument("--tone", choices=["fluida", "literal"],
                    help="naturalidad vs. literalidad (def: fluida)")
    ap.add_argument("--ocr", choices=["auto", "force", "off"],
                    help="manejo de páginas escaneadas (def: auto)")
    ap.add_argument("--max-pages", type=int, default=None,
                    help="traducir solo N páginas (para probar); omitido = todas")
    ap.add_argument("--ocr-dpi", type=int, help="resolución de rasterizado para OCR (>=300)")
    ap.add_argument("--no-diagramas", action="store_true",
                    help="no capturar diagramas vectoriales")
    ap.add_argument("--no-deskew", action="store_true",
                    help="no enderezar escaneos torcidos antes del OCR")
    ap.add_argument("--chunk-chars", type=int, help="tamaño de agrupación de bloques (0 = sin agrupar)")
    ap.add_argument("--no-cache", action="store_true", help="no usar el caché de traducciones")
    ap.add_argument("--detect-caps", action="store_true",
                    help="detectar MAYÚSCULAS como intraducibles (solo modo especializado; ruidoso)")
    ap.add_argument("--no-preserve", action="store_true",
                    help="no preservar palabras intraducibles (ni no-latinas)")
    ap.add_argument("--out", help="ruta de salida .html (solo con un PDF)")
    ap.add_argument("--no-pdf", action="store_true",
                    help="generar solo el HTML, sin el .pdf")
    ap.add_argument("--solo", action="store_true",
                    help="mostrar solo la traducción (sin la columna original)")
    args = ap.parse_args(argv)

    cfg = build_config_from_args(args)

    if not args.yes and cfg.edition == "completa":
        if _menu_completo() != "traducir":
            return 0

    if not args.yes:
        cfg = run_wizard(preset=cfg)
    apply_type_defaults(cfg)
    cfg._yes_cloud = args.yes_cloud

    inputs = resolve_inputs(cfg.input_pdf)
    if not inputs:
        print(f"✗ No encontré PDFs en: {cfg.input_pdf!r}")
        return 2

    if len(inputs) > 1 and cfg.output_html:
        print("⚠ --out solo aplica a un PDF; con varios se usará un nombre por libro.")
        cfg.output_html = ""

    backend = make_backend(cfg)
    ok, msg = backend.available()
    if msg:
        print(msg)
    if not ok:
        print("✗ El motor de traducción no está disponible. Aborto.")
        return 3
    draft = None
    if cfg.draft_backend:
        if not backend.supports_review:
            print(f"⚠ --borrador necesita un motor LLM que revise (ollama o nube); "
                  f"'{cfg.backend}' no revisa: se ignora el borrador.")
            cfg.draft_backend = ""
        else:
            draft = make_backend(cfg, cfg.draft_backend)
            ok, msg = draft.available()
            if msg:
                print(msg)
            if not ok:
                print("✗ El motor del borrador no está disponible. Aborto.")
                return 3

    remotos = _remote_backends(cfg.backend, cfg.draft_backend)
    if remotos:
        try:
            remoto.exigir_consentimiento_nube(
                f"Motor remoto ({', '.join(dict.fromkeys(remotos))})", aceptado=args.yes_cloud)
        except remoto.SinConsentimiento as e:
            print(e)
            return 0 if sys.stdin.isatty() else 1

    ocr_ok = True
    if cfg.ocr_mode != "off":
        ocr_ok, omsg = ocr_mod.ocr_available(cfg.ocr_lang)
        if not ocr_ok:
            print(omsg)
            print("  → Las páginas escaneadas se mostrarán como imagen, sin traducción.")

    today = datetime.date.today().isoformat()
    print(f"\nMotor: {cfg.backend}" + (f" (revisa el borrador de {cfg.draft_backend})" if draft else "")
          + f" | OCR: {cfg.ocr_mode} | Revisión: {cfg.review_passes if backend.supports_review else 0} pasadas")

    glossary = load_glossary(_resource(cfg.glossary_path)) if cfg.preservar_intraducibles else []
    if cfg.glossary_extra and cfg.preservar_intraducibles:
        glossary += [t for t in load_glossary(cfg.glossary_extra) if t not in glossary]
    if glossary:
        print(f"Glosario: {len(glossary)} términos")

    results = []
    failed = 0
    for pdf in inputs:
        try:
            results.append(process_pdf(pdf, cfg, backend, glossary, ocr_ok, today, log=print, draft=draft))
        except Exception as e:
            if isinstance(e, requests.HTTPError) and getattr(e.response, "status_code", 0) in (400, 401, 402, 403, 404, 422):
                raise
            failed += 1
            print(f"  ✗ Error procesando {pdf}: {e}")

    if cfg.edition == "simple" and results:
        for r in results:
            pdf_out = os.path.splitext(r["out"])[0] + ".pdf"
            final = pdf_out if os.path.exists(pdf_out) else r["out"]
            print("\n" + "=" * 60)
            print("  LISTO! Tu traduccion esta aqui:")
            print(f"     {final}")
            if r.get("untranslated") or r.get("scanned_empty"):
                print("  ⚠ OJO, revisa:")
                if r.get("untranslated"):
                    print(f"     · {r['untranslated']} bloques quedaron SIN traducir "
                          f"(vuelve a ejecutar el mismo comando: se reparan solos).")
                if r.get("scanned_empty"):
                    print(f"     · {r['scanned_empty']}/{r['scanned_total']} páginas escaneadas "
                          f"sin texto ({_ocr_hint()}).")
            print("=" * 60)
        return 1 if failed or len(results) != len(inputs) or any(r.get("untranslated") or r.get("scanned_empty") for r in results) else 0

    print("\n" + "=" * 72)
    print("RESUMEN")
    problemas = 0
    for r in results:
        cad = f"  ♻ {r['cached']} desde caché" if r.get("cached") else ""
        print(f"  {r['out']}  ({r['blocks']} bloques, {r['terms']} términos){cad}")
        if r.get("untranslated"):
            problemas += 1
            print(f"     ⚠ {r['untranslated']} bloques NO se tradujeron (quedaron en inglés/truncados). "
                  f"Vuelve a ejecutar el MISMO comando: se repararán solos (no están cacheados).")
        if r.get("scanned_empty"):
            problemas += 1
            print(f"     ⚠ {r['scanned_empty']} de {r['scanned_total']} páginas escaneadas quedaron SIN texto "
                  f"({_ocr_hint()}). Revisa esas páginas.")
        if r.get("lost"):
            print(f"     · {r['lost']} tokens de voces perdidos; esos bloques se reintentaron y no se guardaron en caché")
    if not problemas:
        print("  ✓ Auditoría: sin bloques sin traducir ni páginas perdidas.")
    if failed:
        print(f"  ✗ {failed} PDF(s) fallaron.")
    print("=" * 72)
    return 1 if failed or problemas else 0


def _hold_window():
    """Al ejecutar el .exe con doble clic, mantener la ventana abierta."""
    if getattr(sys, "frozen", False):
        try:
            input("\nListo. Presiona Enter para cerrar esta ventana...")
        except EOFError:
            pass


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except SystemExit as e:
        code = e.code
    except BaseException:
        import traceback
        print("\n--- Ocurrio un error ---")
        traceback.print_exc()
        print("\nGuarda una captura de este mensaje para reportar el error.")
        code = 1
    finally:
        _hold_window()
    sys.exit(code)
