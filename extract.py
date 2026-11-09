"""Extracción de PDF: texto + imágenes, con detección de páginas escaneadas.

Por cada página decide el modo:
  * "text": tiene capa de texto copiable -> se extraen párrafos e imágenes.
  * "scanned": sin texto útil -> se rasteriza la página completa (imagen) para
    aplicarle OCR después; el escaneo original se conserva intacto.

El OCR NO se hace aquí (lo hace ocr.py desde main), para que este módulo se
pueda usar y probar sin depender de Tesseract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import fitz

import textclean


@dataclass
class TextItem:
    text: str
    bbox: tuple
    type: str = "text"


@dataclass
class ImageItem:
    data: bytes
    ext: str
    width: int
    height: int
    bbox: tuple
    type: str = "image"


@dataclass
class Page:
    number: int
    mode: str = "text"
    items: list = field(default_factory=list)
    page_image: bytes | None = None
    page_image_ext: str = "png"


def _clean(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    return " ".join(l for l in lines if l).strip()


def _extract_text_items(data) -> list:
    items = []
    for b in data.get("blocks", []):
        if b.get("type", 0) != 0:
            continue
        parts = []
        for line in b.get("lines", []):
            parts.append("".join(sp.get("text", "") for sp in line.get("spans", [])))
        text = textclean.clean(_clean("\n".join(parts)))
        if text and not textclean.is_junk(text):
            items.append(TextItem(text=text, bbox=tuple(b["bbox"])))
    return items


def _extract_images(doc, page) -> list:
    items = []
    seen = set()
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref", 0)
        if not xref or xref in seen:
            continue
        seen.add(xref)
        try:
            img = doc.extract_image(xref)
        except Exception:
            continue
        items.append(ImageItem(
            data=img["image"], ext=img.get("ext", "png"),
            width=img.get("width", 0), height=img.get("height", 0),
            bbox=tuple(info.get("bbox", (0, 0, 0, 0)))))
    return items


def _rasterize(page, dpi: int) -> bytes:
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png")


def _overlap_area(a, b) -> float:
    inter = a & b
    return inter.width * inter.height if (inter.width > 0 and inter.height > 0) else 0.0


def _extract_vector_figures(page, min_pt: int, dpi: int,
                            raster_bboxes: list, text_bboxes: list) -> list:
    """Captura diagramas hechos con VECTORES (line-art) rasterizándolos.

    `get_image_info` no ve los dibujos vectoriales; `cluster_drawings` agrupa el
    line-art y rasterizamos cada cluster. Se descartan: filetes muy pequeños,
    marcos de página completa, lo ya cubierto por una imagen ráster, y los
    clusters que en su mayoría son texto (para no duplicar párrafos como figura).
    """
    items = []
    try:
        clusters = page.cluster_drawings()
    except Exception:
        return items
    pw, ph = page.rect.width, page.rect.height
    for rect in clusters:
        w, h = rect.width, rect.height
        area = max(0.0, w) * max(0.0, h)
        if max(w, h) < min_pt or area < float(min_pt) * min_pt:
            continue
        if w > pw * 0.85 and h > ph * 0.85:
            continue
        if any(_overlap_area(rect, rb) > area * 0.6 for rb in raster_bboxes):
            continue
        if sum(_overlap_area(rect, tb) for tb in text_bboxes) > area * 0.5:
            continue
        try:
            pix = page.get_pixmap(clip=rect, dpi=dpi)
        except Exception:
            continue
        items.append(ImageItem(data=pix.tobytes("png"), ext="png",
                               width=pix.width, height=pix.height, bbox=tuple(rect)))
    return items


def _order_items(items: list, page_rect) -> list:
    """Orden de lectura. Detecta 2 columnas (papers) y devuelve la columna
    izquierda completa antes que la derecha, separando por bloques a ancho total
    (títulos, encabezados, figuras que cruzan la medianera)."""
    by_y = sorted(items, key=lambda it: (round(it.bbox[1], 1), round(it.bbox[0], 1)))
    if not items:
        return by_y
    gutter = page_rect.x0 + page_rect.width / 2.0
    m = page_rect.width * 0.06

    texts = [it for it in items if it.type == "text"]
    left = [it for it in texts
            if (it.bbox[0] + it.bbox[2]) / 2 < gutter and it.bbox[2] < gutter + m]
    right = [it for it in texts
             if (it.bbox[0] + it.bbox[2]) / 2 >= gutter and it.bbox[0] > gutter - m]

    body_top = page_rect.y0 + page_rect.height * 0.15
    crossers = sum(1 for it in texts
                   if it.bbox[0] < gutter - m and it.bbox[2] > gutter + m and it.bbox[1] > body_top)

    def _vspan(side):
        ys = [it.bbox[1] for it in side]
        return (max(ys) - min(ys)) if len(ys) >= 2 else 0

    two_col = (len(left) >= 2 and len(right) >= 2 and crossers <= 1
               and _vspan(left) > page_rect.height * 0.35
               and _vspan(right) > page_rect.height * 0.35)
    if not two_col:
        return by_y

    def kind(it):
        x0, _, x1, _ = it.bbox
        if x0 < gutter - m and x1 > gutter + m:
            return "full"
        return "left" if (x0 + x1) / 2 < gutter else "right"

    ordered, buf_l, buf_r = [], [], []

    def flush():
        ordered.extend(sorted(buf_l, key=lambda it: it.bbox[1]))
        ordered.extend(sorted(buf_r, key=lambda it: it.bbox[1]))
        buf_l.clear()
        buf_r.clear()

    for it in by_y:
        k = kind(it)
        if k == "full":
            flush()
            ordered.append(it)
        elif k == "left":
            buf_l.append(it)
        else:
            buf_r.append(it)
    flush()
    return ordered


def extract_document(pdf_path: str, max_pages: int | None = None,
                     ocr_mode: str = "auto", scanned_threshold: int = 20,
                     ocr_dpi: int = 300, capture_vector: bool = True,
                     vector_dpi: int = 150, vector_min_pt: int = 36) -> list[Page]:
    doc = fitz.open(pdf_path)
    pages: list[Page] = []
    try:
        for pno in range(len(doc)):
            if max_pages is not None and pno >= max_pages:
                break
            page = doc[pno]
            data = page.get_text("dict")
            text_items = _extract_text_items(data)
            text_len = sum(len(it.text) for it in text_items)

            if ocr_mode == "force":
                scanned = True
            elif ocr_mode == "off":
                scanned = False
            else:
                scanned = text_len < scanned_threshold

            if scanned:
                pages.append(Page(number=pno + 1, mode="scanned",
                                  page_image=_rasterize(page, ocr_dpi),
                                  page_image_ext="png"))
            else:
                raster = _extract_images(doc, page)
                items = text_items + raster
                if capture_vector:
                    raster_bboxes = [fitz.Rect(it.bbox) for it in raster]
                    text_bboxes = [fitz.Rect(it.bbox) for it in text_items]
                    items += _extract_vector_figures(page, vector_min_pt, vector_dpi,
                                                     raster_bboxes, text_bboxes)
                items = _order_items(items, page.rect)
                pages.append(Page(number=pno + 1, mode="text", items=items))
    finally:
        doc.close()
    return pages
