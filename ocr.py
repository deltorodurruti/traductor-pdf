"""OCR para PDF escaneados (solo imagen).

Motores, elegidos con la variable de entorno OCR_MOTOR:
  * doble (por defecto): corre Tesseract y RapidOCR sobre cada página y
    FUSIONA las dos lecturas palabra por palabra (ver _fusionar). Si uno de
    los dos no está instalado, usa solo el otro.
  * tesseract: solo Tesseract vía pytesseract.
  * rapid: solo RapidOCR (modelos PP-OCR sobre onnxruntime, modelo en inglés).

Si ningún motor está instalado, el pipeline sigue funcionando: las páginas
escaneadas se muestran como imagen sin traducción y se avisa al persona.

Requisitos:
  * tesseract: binario Tesseract + pip install pytesseract Pillow
    (p.ej. `brew install tesseract` o `apt install tesseract-ocr tesseract-ocr-eng`).
  * rapid: pip install rapidocr onnxruntime Pillow numpy
    (los modelos en inglés se descargan la primera vez).
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
import re
import sqlite3
import statistics
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from intraducibles import diccionario_en

MOTORES = ("doble", "tesseract", "rapid")
ultimo_motor = ""


def _motor() -> str:
    m = os.environ.get("OCR_MOTOR", "doble").strip().lower()
    return m if m in MOTORES else "doble"


def _use_bundled_tesseract() -> None:
    """Si el programa está empaquetado (.exe) y trae Tesseract adentro, usarlo.
    Así el persona no necesita instalar Tesseract por separado."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return
    tdir = os.path.join(base, "Tesseract-OCR")
    exe = os.path.join(tdir, "tesseract.exe")
    if os.path.exists(exe):
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = exe
            os.environ.setdefault("TESSDATA_PREFIX", os.path.join(tdir, "tessdata"))
        except Exception:
            pass


_use_bundled_tesseract()

_RAPID = None


def _motor_rapid():
    global _RAPID
    if _RAPID is None:
        from rapidocr import LangRec, RapidOCR
        _RAPID = RapidOCR(params={"Rec.lang_type": LangRec.EN})
    return _RAPID


@lru_cache(maxsize=8)
def _hay_tesseract(lang: str | None = None) -> tuple[bool, str]:
    import importlib.util
    if importlib.util.find_spec("pytesseract") is None:
        return False, ("✗ Falta Tesseract. Instala:  pip install pytesseract Pillow\n"
                       "  y el binario Tesseract (apt install tesseract-ocr / instalador Windows).")
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception as e:
        return False, (f"✗ pytesseract está, pero no encuentro el binario Tesseract. "
                       f"Instálalo y/o define pytesseract.pytesseract.tesseract_cmd. Detalle: {e}")
    if lang:
        try:
            langs = pytesseract.get_languages(config="")
        except Exception:
            langs = []
        if langs and lang not in langs:
            return False, (f"✗ Tesseract no tiene el idioma '{lang}' instalado. "
                           f"Disponibles: {', '.join(langs) or 'ninguno'}. "
                           f"Instala el paquete de idioma (p.ej. 'tesseract-ocr-{lang}').")
    return True, ""


@lru_cache(maxsize=1)
def _hay_rapid() -> tuple[bool, str]:
    import importlib.util
    if importlib.util.find_spec("rapidocr") is None:
        return False, "✗ Falta RapidOCR. Instala:  pip install rapidocr onnxruntime Pillow numpy"
    return True, ""


def ocr_available(lang: str | None = None) -> tuple[bool, str]:
    """(disponible, mensaje de ayuda si falta algo) para el modo elegido.

    En modo `doble` basta con que uno de los dos motores esté instalado."""
    import importlib.util
    if importlib.util.find_spec("PIL") is None:
        return False, "✗ Falta OCR. Instala:  pip install Pillow"
    m = _motor()
    if m == "tesseract":
        return _hay_tesseract(lang)
    if m == "rapid":
        return _hay_rapid()
    ok_t, msg_t = _hay_tesseract(lang)
    if ok_t:
        return True, ""
    ok_r, msg_r = _hay_rapid()
    if ok_r:
        return True, ""
    return False, msg_t + "\n" + msg_r


def _fill_for(img):
    return 255 if img.mode in ("L", "1") else (255, 255, 255)


def _binarize(img):
    """Denoise + binarización (Otsu) con OpenCV para escaneos antiguos.

    Quita motas del papel viejo y separa tinta de fondo, que es la mejora de
    OCR más grande en tipografías dañadas. Si OpenCV no está, devuelve la imagen
    igual (degradación con gracia)."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return img
    try:
        from PIL import Image
        arr = np.asarray(img.convert("L"))
        arr = cv2.medianBlur(arr, 3)
        arr = cv2.fastNlMeansDenoising(arr, h=10)
        _, bw = cv2.threshold(arr, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bw = cv2.copyMakeBorder(bw, 10, 10, 10, 10,
                                cv2.BORDER_CONSTANT, value=255)
        return Image.fromarray(bw)
    except Exception:
        return img


def _orient(img):
    """Corrige orientación 90/180/270 con OSD de Tesseract (best-effort)."""
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(img)
        deg = int(re.search(r"Rotate:\s*(\d+)", osd).group(1))
    except Exception:
        return img
    if deg in (90, 180, 270):
        try:
            return img.rotate(-deg, expand=True, fillcolor=_fill_for(img))
        except Exception:
            return img
    return img


def _deskew(img):
    """Endereza un escaneo torcido buscando el ángulo (-5°..+5°) que hace más
    'nítidas' las filas de texto (máxima varianza de la proyección horizontal).
    Requiere numpy; si no está, devuelve la imagen igual."""
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return img
    g = img.convert("L")
    scale = 800.0 / max(g.size)
    small = g.resize((max(1, int(g.width * scale)), max(1, int(g.height * scale)))) \
        if scale < 1 else g
    angles = [0.0]
    for k in range(1, 11):
        angles += [k * 0.5, -k * 0.5]
    best_a, best_s = 0.0, -1.0
    for a in angles:
        rot = small.rotate(a, resample=Image.BILINEAR, fillcolor=255)
        arr = 255.0 - np.asarray(rot, dtype=np.float32)
        proj = arr.sum(axis=1)
        s = float(((proj[1:] - proj[:-1]) ** 2).sum())
        if s > best_s:
            best_s, best_a = s, a
    if abs(best_a) < 0.3:
        return img
    return img.rotate(best_a, resample=Image.BICUBIC, fillcolor=_fill_for(img), expand=True)


def _lineas_rapid_a_texto(res) -> str:
    """Une las líneas de RapidOCR en texto con saltos de párrafo.

    Nueva línea = salto simple. Párrafo nuevo (línea en blanco) si la línea
    empieza más a la derecha del margen (sangría) o si hay un hueco vertical
    mayor que 1,3 veces el paso normal entre líneas."""
    if res.boxes is None or not len(res.txts):
        return ""
    lin = []
    for pts, txt in zip(res.boxes, res.txts):
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        lin.append((min(ys), min(xs), max(xs), txt))
    lin.sort(key=lambda l: l[0])
    saltos = [b[0] - a[0] for a, b in zip(lin, lin[1:]) if b[0] - a[0] > 0]
    paso = statistics.median(saltos) if saltos else 0
    margen = statistics.median(l[1] for l in lin)
    ancho = max(l[2] for l in lin)
    out = [lin[0][3]]
    for prev, cur in zip(lin, lin[1:]):
        nuevo = (cur[0] - prev[0] > 1.3 * paso) or (cur[1] - margen > 0.03 * ancho)
        out.append(("\n\n" if nuevo else "\n") + cur[3])
    return "".join(out)


def _norm(w: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", w).lower()


_SUFIJOS = (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("d", ""), ("ing", ""), ("ly", ""))


def _valida(w: str) -> bool:
    """Palabra plausible: inglés conocido (con plural o flexión), una sola letra
    o un número. Símbolos sueltos («|», «~») y basura («paasasay») no."""
    n = _norm(w)
    if not n:
        return False
    if n.isdigit() or len(n) == 1:
        return True
    dic = diccionario_en()
    if not dic:
        return bool(re.search(r"[aeiouy]", n))
    cands = [n] + [n[:-len(s)] + r for s, r in _SUFIJOS if n.endswith(s) and len(n) > len(s) + 2]
    return any(c in dic for c in cands)


def _raros(bloque) -> int:
    """Cuántos símbolos raros (fuera de letras, números y puntuación común) trae un bloque."""
    return sum(len(re.findall(r"[^\w\s.,;:!?'\"()\-–—’“”&%$@/]", w)) for w, _ in bloque)


def _aceptable_suelta(w: str) -> bool:
    """Palabra que solo leyó un motor: se acepta si es válida o si parece nombre
    propio (mayúscula inicial, p. ej. «Rufus»). Basura y símbolos se descartan."""
    return _valida(w) or (w[:1].isupper() and bool(_norm(w)))


def _tokens(paras: list[str]) -> list[tuple[str, bool]]:
    """Palabras con la marca de «inicia párrafo» (la primera de cada párrafo)."""
    out = []
    for p in paras:
        for i, w in enumerate(p.split()):
            out.append((w, i == 0))
    return out


def _fusionar(a: list[tuple[str, bool]], b: list[tuple[str, bool]]) -> list[str]:
    """Fusiona dos lecturas OCR de la misma página en párrafos.

    Alinea las palabras (difflib, sin distinguir mayúsculas ni signos):
      * iguales en ambas lecturas → se toma la palabra y se suman los saltos de párrafo;
      * distintas → gana el bloque con más palabras válidas (inglés conocido);
      * solo en una lectura → se conserva si es válida y se descarta si es símbolo suelto.
    Así un error de un motor («LNperionces») lo corrige el otro («Experiences»),
    y los saltos de párrafo de cualquiera de los dos cuentan."""
    na = [_norm(w) for w, _ in a]
    nb = [_norm(w) for w, _ in b]
    sm = difflib.SequenceMatcher(None, na, nb, autojunk=False)
    res: list[tuple[str, bool]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                wa, pa = a[i1 + k]
                _, pb = b[j1 + k]
                res.append((wa, pa or pb))
        elif op == "replace":
            ka = (sum(_valida(w) for w, _ in a[i1:i2]), -_raros(a[i1:i2]))
            kb = (sum(_valida(w) for w, _ in b[j1:j2]), -_raros(b[j1:j2]))
            gana_a = ka >= kb
            lado = a[i1:i2] if gana_a else b[j1:j2]
            otro = b[j1:j2] if gana_a else a[i1:i2]
            ini = bool(otro) and otro[0][1]
            trozo = [(w, p or (ini and k == 0)) for k, (w, p) in enumerate(lado)]
            res.extend(trozo)
        elif op == "delete":
            res.extend((w, p) for w, p in a[i1:i2] if re.search(r"[\wÀ-ÿ]", w))
        elif op == "insert":
            res.extend((w, p) for w, p in b[j1:j2] if re.search(r"[\wÀ-ÿ]", w))
    return _reagrupar(res)


def _preparar(img, preprocess: bool, deskew: bool, orientar: bool):
    from PIL import ImageOps
    if orientar and deskew:
        img = _orient(img)
    if preprocess:
        try:
            img = ImageOps.autocontrast(ImageOps.grayscale(img))
        except Exception:
            pass
    if deskew:
        try:
            img = _deskew(img)
        except Exception:
            pass
    if preprocess:
        img = _binarize(img)
    return img


def _leer_tesseract(img, lang: str, psm: int, oem: int) -> list[str]:
    import pytesseract
    raw = pytesseract.image_to_string(img, lang=lang, config=f"--oem {oem} --psm {psm}")
    return _split_paragraphs(raw)


def _leer_rapid(img) -> list[str]:
    import numpy as np
    return _split_paragraphs(_lineas_rapid_a_texto(_motor_rapid()(np.array(img.convert("RGB")))))


def _leer_motor(nombre: str, img, lang: str, psm: int, oem: int, preprocess: bool, deskew: bool):
    """Prepara la imagen para ese motor y devuelve sus palabras con marca de párrafo."""
    if nombre == "tesseract":
        base = _preparar(img, preprocess, deskew, orientar=True)
        return _tokens(_leer_tesseract(base, lang, psm, oem))
    base = _preparar(img, preprocess, deskew, orientar=False)
    return _tokens(_leer_rapid(base))


CACHE_VERSION = "v2"
_cache_lock = threading.Lock()
_cache_con = None
_cache_ruta = None


def _cache_conexion():
    """Caché de OCR por página en SQLite (OCR_CACHE=0 la desactiva, OCR_CACHE_DB cambia la ruta)."""
    global _cache_con, _cache_ruta
    if os.environ.get("OCR_CACHE", "1") == "0":
        return None
    ruta = os.environ.get("OCR_CACHE_DB") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ocr_cache.db")
    with _cache_lock:
        if _cache_con is None or _cache_ruta != ruta:
            try:
                con = sqlite3.connect(ruta, timeout=30, check_same_thread=False)
                con.execute("CREATE TABLE IF NOT EXISTS ocr (k TEXT PRIMARY KEY, v TEXT)")
                con.commit()
                _cache_con, _cache_ruta = con, ruta
            except sqlite3.Error:
                _cache_con = None
    return _cache_con


def _cache_clave(png_bytes: bytes, motor: str, lang: str, psm: int, oem: int, preprocess: bool, deskew: bool) -> str:
    cfg = f"|{motor}|{lang}|{psm}|{oem}|{int(preprocess)}|{int(deskew)}|{CACHE_VERSION}"
    return hashlib.sha1(png_bytes + cfg.encode()).hexdigest()


def _cache_leer(clave: str):
    con = _cache_conexion()
    if con is None:
        return None
    with _cache_lock:
        fila = con.execute("SELECT v FROM ocr WHERE k=?", (clave,)).fetchone()
    if not fila:
        return None
    d = json.loads(fila[0])
    return d["paras"], d["motor"]


def _cache_guardar(clave: str, paras: list, motor: str) -> None:
    con = _cache_conexion()
    if con is None:
        return
    with _cache_lock:
        con.execute("INSERT OR REPLACE INTO ocr(k, v) VALUES(?, ?)",
                    (clave, json.dumps({"paras": paras, "motor": motor}, ensure_ascii=False)))
        con.commit()


def ocr_paragraphs(png_bytes: bytes, lang: str = "eng", psm: int = 3, oem: int = 1,
                   preprocess: bool = True, deskew: bool = True) -> list[str]:
    """Devuelve el texto OCR de una imagen PNG, dividido en párrafos.

    Modo `doble`: Tesseract y RapidOCR leen la misma página y _fusionar combina
    las dos lecturas. `lang`, `psm` y `oem` son de Tesseract (RapidOCR usa su
    modelo en inglés).
    """
    global ultimo_motor
    from PIL import Image

    import textclean
    motor = _motor()
    clave = _cache_clave(png_bytes, motor, lang, psm, oem, preprocess, deskew)
    hit = _cache_leer(clave)
    if hit is not None:
        paras, ultimo_motor = hit
    else:
        img = Image.open(io.BytesIO(png_bytes))
        img.load()
        nombres = [n for n, ok in (("tesseract", motor in ("doble", "tesseract") and _hay_tesseract(lang)[0]),
                                   ("rapid", motor in ("doble", "rapid") and _hay_rapid()[0])) if ok]
        if not nombres:
            raise RuntimeError("ningún motor OCR disponible")
        with ThreadPoolExecutor(max_workers=len(nombres)) as ex:
            futs = [(n, ex.submit(_leer_motor, n, img, lang, psm, oem, preprocess, deskew)) for n in nombres]
        lecturas = []
        for n, f in futs:
            try:
                lecturas.append((n, f.result()))
            except Exception:
                pass
        if not lecturas:
            raise RuntimeError("ningún motor OCR disponible")
        if len(lecturas) == 2:
            paras = _fusionar(lecturas[0][1], lecturas[1][1])
            ultimo_motor = "doble"
        else:
            paras = _reagrupar(lecturas[0][1])
            ultimo_motor = lecturas[0][0]
        if len(lecturas) == len(nombres):
            _cache_guardar(clave, paras, ultimo_motor)
    out = []
    for p in paras:
        c = textclean.clean(p)
        if c and not textclean.is_junk(c):
            out.append(c)
    return out


def _reagrupar(toks: list[tuple[str, bool]]) -> list[str]:
    """Un solo motor: reconstruye los párrafos desde sus marcas."""
    paras, cur = [], []
    for w, p in toks:
        if p and cur:
            paras.append(" ".join(cur))
            cur = []
        cur.append(w)
    if cur:
        paras.append(" ".join(cur))
    return paras


def _split_paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text)
    paras = []
    for b in blocks:
        joined = " ".join(ln.strip() for ln in b.splitlines() if ln.strip())
        joined = joined.strip()
        if joined:
            paras.append(joined)
    return paras
