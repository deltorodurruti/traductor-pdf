"""Render bilingüe lado a lado en HTML autocontenido.

Soporta dos tipos de página:
  * texto: filas de dos columnas (original | traducción), imágenes intercaladas.
  * escaneada: se muestra el escaneo ORIGINAL intacto (imagen de la página) y
    debajo las filas OCR-original | traducción.

Las palabras intraducibles se resaltan y enlazan al apéndice de términos.
Imágenes embebidas en base64 (archivo único). Tema claro/oscuro + print-friendly.
"""
from __future__ import annotations

import base64
import html as _html
import os
import re

CSS = """
:root{
  --bg:#faf8f4; --fg:#1f1b16; --muted:#8a7d64; --rule:#d8cbb0; --accent:#9a6b2f;
  --srcfg:#5c5442; --card:#fffdf9; --link:#3b6ea5;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#17140f; --fg:#e9e2d4; --muted:#a99c81; --rule:#4a4133; --accent:#d6a15a;
         --srcfg:#c3b89f; --card:#201b14; --link:#7fb0e6; }
}
*{ box-sizing:border-box; }
body{ font-family:Georgia,'Times New Roman',serif; margin:0; padding:0 clamp(12px,4vw,40px) 96px;
      background:var(--bg); color:var(--fg); line-height:1.45; }
header{ position:sticky; top:0; background:var(--bg); border-bottom:2px solid var(--rule);
        padding:20px 0 12px; margin-bottom:24px; z-index:5; }
h1{ font-size:1.4rem; margin:0; }
.sub{ color:var(--muted); font-size:.85rem; margin-top:4px; }
.page{ margin:36px 0; }
.page-num{ text-align:center; color:var(--muted); font-size:.72rem; letter-spacing:.18em;
           text-transform:uppercase; margin-bottom:14px; }
.scan{ text-align:center; margin:0 0 18px; }
.scan img{ max-width:100%; height:auto; border:1px solid var(--rule); background:#fff; }
.badge{ display:inline-block; font-size:.62rem; letter-spacing:.1em; text-transform:uppercase;
        color:var(--muted); border:1px solid var(--rule); border-radius:10px; padding:1px 8px; margin-left:8px; }
.row{ display:grid; grid-template-columns:1fr 1fr; gap:clamp(14px,3vw,28px); margin:0 0 14px;
      align-items:start; break-inside:avoid; page-break-inside:avoid; }
.solo{ margin:0 0 12px; max-width:44rem; }   /* modo solo-traducción, ancho de lectura */
.col{ padding:2px; }
.col.src{ color:var(--srcfg); border-right:1px dashed var(--rule); padding-right:clamp(14px,3vw,28px);
          font-size:.86em; line-height:1.3; }  /* original: solo verificación, más compacto */
.lbl{ display:block; font-size:.62rem; text-transform:uppercase; letter-spacing:.14em;
      color:var(--muted); margin-bottom:4px; }
figure{ margin:22px auto; text-align:center; }
figure img{ max-width:100%; height:auto; border:1px solid var(--rule); background:#fff; }
a.term{ color:var(--accent); text-decoration:none; border-bottom:1px dotted var(--accent); font-weight:bold; }
.rom{ color:var(--muted); font-style:italic; font-size:.85em; }
.pron{ color:var(--muted); font-size:.85em; }
.pron-audio{ height:26px; vertical-align:middle; }
.warn{ color:#b5642a; font-style:italic; font-size:.85rem; }
.refs{ margin-top:72px; border-top:2px solid var(--rule); padding-top:18px; }
.refs h2{ font-size:1.1rem; }
.ref{ margin:12px 0; font-size:.92rem; }
.ref .t{ font-weight:bold; color:var(--accent); }
.ref .q{ color:var(--srcfg); font-style:italic; }
.ref a{ color:var(--link); word-break:break-all; }
.nosrc{ color:#a8452a; font-style:italic; }
@media (max-width:760px){
  .row{ grid-template-columns:1fr; }
  .col.src{ border-right:none; border-bottom:1px dashed var(--rule); padding-right:0; padding-bottom:10px; }
}
@media print{ header{ position:static; } body{ background:#fff; color:#000; } }
"""


CHROME_CANDIDATES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Chromium.app/Contents/MacOS/Chromium",
                     "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                     r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                     r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                     r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                     r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                     "msedge", "google-chrome", "chrome", "chromium", "chromium-browser",
                     "brave-browser", "brave")


def find_chrome() -> str | None:
    """Ejecutable de Chrome/Edge/Chromium para imprimir HTML a PDF (None si no hay)."""
    import shutil
    override = os.environ.get("TRADUCTOR_CHROME")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    return next((c for c in CHROME_CANDIDATES if os.path.exists(c) or shutil.which(c)), None)


def imprimir_pdf(html_path: str, pdf_path: str, *, chrome: str | None = None,
                 timeout: int = 900) -> str:
    """Imprime un HTML local a PDF con Chrome/Brave/Edge headless. Devuelve pdf_path.

    Punto único de impresión: todos los maquetadores pasan por aquí para no repetir
    los flags ni divergir en el navegador. `chrome` se autodetecta si no se pasa.
    """
    import subprocess
    chrome = chrome or find_chrome()
    if not chrome:
        raise RuntimeError("No encuentro Chrome/Brave/Edge para imprimir el PDF. "
                           "Instala uno o define TRADUCTOR_CHROME=/ruta/al/navegador.")
    url = html_path if "://" in html_path else "file://" + os.path.abspath(html_path)
    tmp = pdf_path + ".tmp.pdf"
    try:
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={tmp}", url],
                       check=True, capture_output=True, timeout=timeout)
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            raise RuntimeError(f"Chrome no produjo un PDF completo: {pdf_path}")
        os.replace(tmp, pdf_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return pdf_path


def _esc(s: str) -> str:
    return _html.escape(s or "", quote=False)


def _attr(s: str) -> str:
    """Escapa un valor para usarlo DENTRO de un atributo HTML (escapa comillas)."""
    return _html.escape(s or "", quote=True)


def escribir_atomico(path: str, texto: str) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _highlight(escaped_text: str, patterns: list, roman_by_n=None, seen=None) -> str:
    """Resalta términos preservados (ya escapados) enlazándolos al apéndice.

    Una sola pasada con resolución de solapes: se recogen todas las coincidencias,
    se prefieren las más largas y sin solaparse, y se envuelve conservando el texto
    tal cual aparece (respeta mayúsc./minúsc. de cada columna). Evita anclas anidadas.
    Para términos no latinos con romanización, la añade entre paréntesis la PRIMERA
    vez que aparecen en esa columna (`seen` lleva la cuenta).
    """
    roman_by_n = roman_by_n or {}
    spans = []
    for pat, n, _term in patterns:
        for m in pat.finditer(escaped_text):
            spans.append((m.start(), m.end(), n))
    if not spans:
        return escaped_text
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    chosen = []
    last_end = -1
    for s in spans:
        if s[0] >= last_end:
            chosen.append(s)
            last_end = s[1]
    out = []
    prev = 0
    for start, end, n in chosen:
        out.append(escaped_text[prev:start])
        anchor = f'<a class="term" href="#t{n}">{escaped_text[start:end]}</a>'
        rom = roman_by_n.get(n)
        if rom and seen is not None and n not in seen:
            anchor += f' <span class="rom">({_esc(rom)})</span>'
            seen.add(n)
        out.append(anchor)
        prev = end
    out.append(escaped_text[prev:])
    return "".join(out)


def _b64_img(data: bytes, ext: str) -> str:
    mime = "png" if ext.lower() in ("png", "") else ext.lower()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


def render_html(pages, term_map, out_path, *,
                title="Traducción bilingüe", src_name="inglés", tgt_name="español",
                romanizations=None, pronunciations=None,
                bilingual=True):
    romanizations = romanizations or {}
    pronunciations = pronunciations or {}
    numbering = {term: i for i, term in enumerate(term_map, start=1)}
    roman_by_n = {numbering[t]: r for t, r in romanizations.items() if t in numbering}
    seen_src, seen_tgt = set(), set()
    patterns = []
    for term, n in numbering.items():
        esc = re.escape(_esc(term))
        pat = re.compile(rf"(?<![\wÀ-ÿ]){esc}(?![\wÀ-ÿ])")
        patterns.append((pat, n, term))

    P = []
    P.append("<!doctype html><html lang='es'><head><meta charset='utf-8'>")
    P.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    P.append(f"<title>{_esc(title)}</title><style>{CSS}</style></head><body>")
    P.append(f"<header><h1>{_esc(title)}</h1>"
             f"<div class='sub'>Traducción bilingüe · {_esc(src_name)} → {_esc(tgt_name)} "
             f"· generado automáticamente</div></header>")

    for pg in pages:
        P.append(f"<section class='page'><div class='page-num'>Página {pg['number']}"
                 + ("<span class='badge'>escaneada · OCR</span>" if pg.get("mode") == "scanned" else "")
                 + "</div>")

        if pg.get("mode") == "scanned" and pg.get("page_image"):
            src = _b64_img(pg["page_image"], pg.get("page_image_ext", "png"))
            P.append(f"<div class='scan'><img src='{src}' alt='escaneo de la página "
                     f"{pg['number']}'></div>")
            if not pg.get("rows"):
                P.append("<p class='warn'>No se pudo extraer texto por OCR de esta página "
                         "(¿Tesseract no instalado o página sin texto?).</p>")

        for row in pg.get("rows", []):
            if row[0] == "text":
                _, orig, trad = row
                t = re.sub(r"\n\s*\n+", "\n",
                           _highlight(_esc(trad), patterns, roman_by_n, seen_tgt)).replace("\n", "<br>")
                if not bilingual:
                    P.append(f"<div class='solo'>{t}</div>")
                    continue
                o = re.sub(r"\n\s*\n+", "\n",
                           _highlight(_esc(orig), patterns, roman_by_n, seen_src)).replace("\n", "<br>")
                P.append("<div class='row'>")
                P.append(f"<div class='col src'><span class='lbl'>Original</span>{o}</div>")
                P.append(f"<div class='col tgt'><span class='lbl'>{_esc(tgt_name).capitalize()}</span>{t}</div>")
                P.append("</div>")
            elif row[0] == "image":
                _, data, ext = row
                P.append(f"<figure><img src='{_b64_img(data, ext)}' alt='ilustración'></figure>")
        P.append("</section>")

    if term_map:
        P.append("<section class='refs'><h2>Términos que no se traducen</h2>")
        for term, n in numbering.items():
            rom = romanizations.get(term)
            rom_html = f" <span class='rom'>({_esc(rom)})</span>" if rom else ""
            pron_html = ""
            pr = pronunciations.get(term)
            if pr and pr.get("say"):
                kind = pr.get("kind")
                label = {"IPA": "pronunciación", "curada": "pronunciación (léxico)",
                         "aprendida": "pronunciación (léxico aprendido)"}.get(
                    kind, "pronunciación aprox.")
                say = f"/{pr['say']}/" if kind == "IPA" else pr["say"]
                ref = f" <span class='sub'>[{_esc(pr['ref'])}]</span>" if pr.get("ref") else ""
                extra = ""
                if pr.get("ipa") and kind != "IPA":
                    extra += f" · IPA: /{_esc(pr['ipa'])}/"
                if pr.get("guia") and kind == "IPA":
                    extra += f" · aprox.: {_esc(pr['guia'])}"
                pron_html = f" · <span class='pron'>{label}: {_esc(say)}{extra}</span>{ref}"
                if pr.get("audio_b64"):
                    pron_html += (f" <audio class='pron-audio' controls preload='none' "
                                  f"src='data:audio/wav;base64,{pr['audio_b64']}'></audio>")
            P.append(f"<div class='ref' id='t{n}'><span class='t'>[{n}] {_esc(term)}</span>"
                     f"{rom_html}{pron_html}</div>")
        P.append("</section>")

    P.append("</body></html>")
    escribir_atomico(out_path, "".join(P))
    return out_path
