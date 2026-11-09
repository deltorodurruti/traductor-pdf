"""Servidor local para la interfaz web (para usar sin terminal).

Escucha SOLO en 127.0.0.1 (no se expone a la red). Sirve la GUI y ejecuta la
traducción en un hilo, reutilizando el motor de `main.py`. La GUI consulta el
progreso por polling.

Arranque:  python server.py   → abre http://localhost:8765
"""
from __future__ import annotations

import base64
import datetime
import glob
import json
import os
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ocr as ocr_mod
from config import Config, apply_type_defaults
from main import load_glossary, process_pdf
from translate import make_backend

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
OUTDIR = os.path.join(HERE, "outputs")
UPLOADDIR = os.path.join(HERE, "uploads")
os.makedirs(OUTDIR, exist_ok=True)
os.makedirs(UPLOADDIR, exist_ok=True)

PORT = 8765
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_REQUEST_BYTES = (MAX_PDF_BYTES + 2) // 3 * 4 + 1024 * 1024
MAX_JOBS = 20
MAX_ACTIVE_JOBS = 2
ALLOWED_ENGINES = {"ollama", "opus", "argos"}
ALLOWED_BOOK_TYPES = {"general", "especializado", "articulo", "libro", "preguntas"}
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")

jobs: dict = {}
jobs_lock = threading.Lock()
active_jobs = 0


def _cleanup_files(jid: str) -> None:
    for fp in (glob.glob(os.path.join(OUTDIR, f"{jid}.html"))
               + glob.glob(os.path.join(UPLOADDIR, f"{jid}_*"))):
        try:
            os.remove(fp)
        except OSError:
            pass


def _new_job() -> str:
    global active_jobs
    jid = uuid.uuid4().hex
    with jobs_lock:
        if active_jobs >= MAX_ACTIVE_JOBS:
            return ""
        active_jobs += 1
        jobs[jid] = {"lines": [], "done": False, "error": None,
                     "result": None, "stats": None}
        while len(jobs) > MAX_JOBS:
            old_id, old = next(iter(jobs.items()))
            if not old.get("done"):
                break
            jobs.pop(old_id, None)
            _cleanup_files(old_id)
    return jid


def _log(jid: str, msg) -> None:
    with jobs_lock:
        j = jobs.get(jid)
        if j is not None:
            for line in (str(msg).splitlines() or [""]):
                j["lines"].append(line)


def _cfg_from_options(opts: dict, input_pdf: str, output_html: str) -> Config:
    cfg = Config()
    cfg.input_pdf = input_pdf
    cfg.output_html = output_html
    cfg.trans_cache_path = os.path.join(HERE, ".translation_cache.db")
    cfg.backend = opts.get("engine", "ollama")
    cfg.ollama_model = opts.get("model") or cfg.ollama_model
    cfg.book_type = opts.get("book_type", "general")
    cfg.tone = opts.get("tone", "fluida")
    cfg.preservar_intraducibles = _bool(opts, "preservar_intraducibles", True)
    cfg.auto_detect_caps = _bool(opts, "auto_detect_caps", False)
    cfg.ocr_mode = opts.get("ocr", "auto")
    cfg.ocr_lang = opts.get("ocr_lang") or cfg.ocr_lang
    cfg.pronounce = _bool(opts, "pronounce", True)
    cfg.pronounce_audio = _bool(opts, "pronounce_audio", False)
    cfg._yes_cloud = _bool(opts, "yes_cloud", False)
    cfg.max_pages = opts.get("max_pages") or None
    if "review_passes" in opts:
        cfg.review_passes = opts["review_passes"]
    return cfg


def _bool(opts, key, default):
    value = opts.get(key, default)
    return value if isinstance(value, bool) else value.lower() == "true"


def _validate_options(opts: dict) -> None:
    """Valida las opciones web antes de crear una configuración de trabajo."""
    engine = opts.get("engine", "ollama")
    if not isinstance(engine, str) or engine not in ALLOWED_ENGINES:
        raise ValueError("el servidor web solo permite motores locales")
    book_type = opts.get("book_type", "general")
    if not isinstance(book_type, str) or book_type not in ALLOWED_BOOK_TYPES:
        raise ValueError("tipo de texto inválido")
    max_pages = opts.get("max_pages")
    if max_pages is not None and (isinstance(max_pages, bool) or not isinstance(max_pages, int)
                                  or max_pages < 0):
        raise ValueError("max_pages debe ser un entero mayor o igual a cero")
    if "review_passes" in opts:
        review_passes = opts["review_passes"]
        if (isinstance(review_passes, bool) or not isinstance(review_passes, int)
                or not 0 <= review_passes <= 5):
            raise ValueError("review_passes debe ser un entero entre 0 y 5")
    for field, default in (("preservar_intraducibles", True), ("auto_detect_caps", False),
                           ("pronounce", True), ("pronounce_audio", False), ("yes_cloud", False)):
        value = opts.get(field, default)
        if not isinstance(value, bool) and (not isinstance(value, str) or value.lower() not in ("true", "false")):
            raise ValueError(f"{field} debe ser true o false")


def _origin_allowed(host: str, origin: str) -> bool:
    host = (host or "").lower()
    origin = (origin or "").lower()
    return host in {f"localhost:{PORT}", f"127.0.0.1:{PORT}"} and origin in {
        f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"
    }


def _run_job(jid: str, filename: str, pdf_bytes: bytes, opts: dict) -> None:
    global active_jobs
    def log(m):
        _log(jid, m)
    try:
        safe = "".join(c for c in os.path.basename(filename)
                       if c.isalnum() or c in "._- ").strip() or "libro.pdf"
        in_path = os.path.join(UPLOADDIR, f"{jid}_{safe}")
        with open(in_path, "wb") as f:
            f.write(pdf_bytes)
        out_path = os.path.join(OUTDIR, f"{jid}.html")
        cfg = _cfg_from_options(opts, in_path, out_path)
        apply_type_defaults(cfg)

        backend = make_backend(cfg)
        ok, msg = backend.available()
        if msg:
            log(msg)
        if not ok:
            raise RuntimeError(msg or "Motor de traducción no disponible")

        ocr_ok = True
        if cfg.ocr_mode != "off":
            ocr_ok, omsg = ocr_mod.ocr_available(cfg.ocr_lang)
            if not ocr_ok:
                log(omsg)
                log("  → Las páginas escaneadas se mostrarán como imagen, sin traducción.")

        today = datetime.date.today().isoformat()
        glossary = load_glossary(cfg.glossary_path) if cfg.preservar_intraducibles else []
        stats = process_pdf(in_path, cfg, backend, glossary, ocr_ok, today, log=log)

        with jobs_lock:
            jobs[jid]["result"] = f"{jid}.html"
            jobs[jid]["stats"] = stats
            jobs[jid]["done"] = True
        log("LISTO")
    except Exception as e:
        with jobs_lock:
            jobs[jid]["error"] = str(e)
            jobs[jid]["done"] = True
        _log(jid, f"ERROR: {e}")
    finally:
        with jobs_lock:
            active_jobs -= 1


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        charset = "; charset=utf-8" if any(x in ctype for x in ("json", "html", "javascript")) else ""
        self.send_header("Content-Type", ctype + charset)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_file(self, path: str, ctype: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._send(404, '{"error":"archivo no encontrado"}')
        return self._send(200, data, ctype)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index.html"):
            return self._serve_file(os.path.join(WEB, "index.html"), "text/html")
        if p.path == "/api/progress":
            jid = (parse_qs(p.query).get("id") or [""])[0]
            with jobs_lock:
                j = jobs.get(jid)
                data = None if not j else {
                    "lines": j["lines"], "done": j["done"],
                    "error": j["error"], "result": j["result"], "stats": j["stats"]}
            if data is None:
                return self._send(404, json.dumps({"error": "job no encontrado"}))
            return self._send(200, json.dumps(data, ensure_ascii=False))
        if p.path == "/api/result":
            jid = (parse_qs(p.query).get("id") or [""])[0]
            if not JOB_ID_RE.match(jid):
                return self._send(400, json.dumps({"error": "id inválido"}))
            fp = os.path.join(OUTDIR, f"{jid}.html")
            if not os.path.exists(fp):
                return self._send(404, json.dumps({"error": "resultado no encontrado"}))
            return self._serve_file(fp, "text/html")
        return self._send(404, json.dumps({"error": "no encontrado"}))

    def do_POST(self):
        if urlparse(self.path).path != "/api/translate":
            return self._send(404, json.dumps({"error": "no encontrado"}))
        if not _origin_allowed(self.headers.get("Host", ""), self.headers.get("Origin", "")):
            return self._send(403, json.dumps({"error": "Origen no permitido"}))
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_REQUEST_BYTES:
            return self._send(413, json.dumps({"error": "solicitud demasiado grande"}))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            pdf_bytes = base64.b64decode(payload["pdf_base64"])
            filename = payload.get("filename", "libro.pdf")
            opts = payload.get("options", {}) or {}
        except Exception as e:
            return self._send(400, json.dumps({"error": f"solicitud inválida: {e}"}))
        if not pdf_bytes:
            return self._send(400, json.dumps({"error": "PDF vacío"}))
        if len(pdf_bytes) > MAX_PDF_BYTES:
            return self._send(413, json.dumps({"error": "el PDF supera el límite de 100 MB"}))
        if not isinstance(opts, dict):
            return self._send(400, json.dumps({"error": "opciones inválidas"}))
        try:
            _validate_options(opts)
        except ValueError as e:
            return self._send(400, json.dumps({"error": str(e)}))
        jid = _new_job()
        if not jid:
            return self._send(429, json.dumps({"error": "ya hay dos traducciones activas; inténtalo más tarde"}))
        try:
            threading.Thread(target=_run_job, args=(jid, filename, pdf_bytes, opts), daemon=True).start()
        except RuntimeError as e:
            global active_jobs
            with jobs_lock:
                jobs.pop(jid, None)
                active_jobs -= 1
            return self._send(503, json.dumps({"error": f"no se pudo iniciar la traducción: {e}"}))
        return self._send(200, json.dumps({"job_id": jid}))


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("=" * 60)
    print("  Traductor de libros — servidor local")
    print(f"  Abre en tu navegador:  http://localhost:{PORT}")
    print("  (Cierra esta ventana para detenerlo)")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")


if __name__ == "__main__":
    main()
