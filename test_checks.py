"""Chequeos de invariantes del pipeline (no requiere red ni modelos)."""
import os
import re

from intraducibles import Masker
from translate import translate_and_review, DummyBackend, _restore, TOKEN_RE
from ocr import _split_paragraphs
import render

ok = 0
fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}")


print("== Masker: enmascarado y solapes ==")
m = Masker(glossary=["ZORKAMEL RIVOTAN", "KORVAX", "PLUMBATAX"], auto_detect=True, allcaps_min_len=3)
masked, mapping = m.mask("Say PLUMBATAX and ZORKAMEL, then ZORKAMEL RIVOTAN, not foobar.")
check("frase larga gana el solape (ZORKAMEL RIVOTAN)", "ZORKAMEL RIVOTAN" in mapping.values())
check("no aparece 'ZORKAMEL' suelto como término", "KORVAX" not in mapping.values())
check("auto-detecta ZORKAMEL", "ZORKAMEL" in mapping.values())
check("tokens MWTKN presentes", bool(TOKEN_RE.search(masked)))
check("no quedó texto original de términos en el masked", "PLUMBATAX" not in masked and "ZORKAMEL" not in masked)

print("== DummyBackend (segment): preservación garantizada ==")
trans, lost, passes = translate_and_review(masked, mapping, DummyBackend(), passes=5)
check("sin tokens perdidos", lost == [])
check("no quedan MWTKN en la salida", not TOKEN_RE.search(trans))
check("términos restaurados intactos", "PLUMBATAX" in trans and "ZORKAMEL" in trans and "ZORKAMEL RIVOTAN" in trans)
check("passes=0 en NMT/segment", passes == 0)

print("== _restore tolerante a mayúsc./minúsc. ==")
r, lost2 = _restore("hola mwtkn0 chau", {"MWTKN0": "ZORKAMEL"})
check("recupera token en minúsculas", "ZORKAMEL" in r and lost2 == [])
r2, lost3 = _restore("hola chau", {"MWTKN0": "ZORKAMEL"})
check("marca token perdido si desaparece", lost3 == [("MWTKN0", "ZORKAMEL")])

print("== OCR: split de párrafos ==")
paras = _split_paragraphs("linea uno\nsigue\n\nsegundo parrafo\n")
check("une líneas y separa por blanco", paras == ["linea uno sigue", "segundo parrafo"])

from types import SimpleNamespace as _NS
import ocr as _ocr_mod
def _caja(x0, y0, txt):
    return ([[x0, y0], [x0 + 200, y0], [x0 + 200, y0 + 20], [x0, y0 + 20]], txt)
_res = _NS(boxes=[], txts=[])
for _b, _t in [_caja(100, 100, "uno"), _caja(100, 140, "dos"), _caja(140, 180, "sangria"), _caja(100, 260, "nuevo")]:
    _res.boxes.append(_b); _res.txts.append(_t)
_txt = _ocr_mod._lineas_rapid_a_texto(_res)
check("OCR: sangría y hueco abren párrafo", _split_paragraphs(_txt) == ["uno dos", "sangria", "nuevo"])

_tk = _ocr_mod._tokens
check("doble: palabra mala del motor A la corrige B",
      _ocr_mod._fusionar(_tk(["Frater R.O. after LNperionces and", "Rufus Opus"]),
                         _tk(["Frater R.O. after Experiences and Rufus Opus"]))
      == ["Frater R.O. after Experiences and", "Rufus Opus"])
check("doble: símbolo suelto (| ~) se descarta",
      _ocr_mod._fusionar(_tk(["Frater | ~ R.O."]), _tk(["Frater R.O."])) == ["Frater R.O."])
check("doble: palabra basura no válida", not _ocr_mod._valida("paasasay"))

import tempfile as _tf
os.environ["OCR_CACHE_DB"] = os.path.join(_tf.mkdtemp(), "ocr.db")
_k1 = _ocr_mod._cache_clave(b"png", "doble", "eng", 3, 1, True, True)
_ocr_mod._cache_guardar(_k1, ["uno dos", "tres"], "doble")
check("OCR caché: lo guardado se recupera", _ocr_mod._cache_leer(_k1) == (["uno dos", "tres"], "doble"))
check("OCR caché: otra configuración no coincide",
      _ocr_mod._cache_leer(_ocr_mod._cache_clave(b"png", "rapid", "eng", 3, 1, True, True)) is None)
check("OCR caché: otra imagen no coincide",
      _ocr_mod._cache_leer(_ocr_mod._cache_clave(b"otra", "doble", "eng", 3, 1, True, True)) is None)
os.environ["OCR_CACHE"] = "0"
check("OCR caché: OCR_CACHE=0 la desactiva", _ocr_mod._cache_leer(_k1) is None)
os.environ.pop("OCR_CACHE"); os.environ.pop("OCR_CACHE_DB")

import hojas as _hojas
import figuras as _fig
_cuerpos = ("la luna sube despacio", "nadie vio el fuego", "tres lámparas sobre la mesa", "el viento trae polvo",
            "cuando amanece todo cambia", "dos hermanos y un río", "la torre guarda silencio")
_pags = [f"UN MANUAL MODERNO DE ASTRONOMIA {c}" for c in _cuerpos]
_prosa = ("Primer párrafo de prosa, bastante largo como para que cuente de verdad como un párrafo entero.<br/>"
          "Segundo párrafo, igual de largo, con su punto final y todo lo que hace falta para distinguirlo.<br/>"
          "Tercer párrafo, otra vez largo, para que la mediana de longitud pase del umbral sin discusión.")
_verso = "El río baja despacio<br/>entre campos abiertos<br/>la mañana trae claridad<br/>y comienza otro día"
check("párrafos: la prosa con <br/> se parte en párrafos de verdad", len(_hojas._parrafos(_prosa)) == 3)
check("párrafos: los versos NO se parten (ahí el salto es del texto)", len(_hojas._parrafos(_verso)) == 1)
check("párrafos: un bloque sin saltos sigue siendo uno", len(_hojas._parrafos("Sin saltos.")) == 1)
_cortada = ("RIVOTAN, registro principal de la estación norte, según las mediciones más recientes<br/>"
            "se mantiene estable durante este periodo y conserva los valores dentro del rango esperado.<br/>"
            "ZORKAMEL, el indicador asociado al sector oeste, junto con los datos que lo describen.")
check("párrafos: un <br/> a mitad de frase NO abre párrafo (viene del salto de página)",
      len(_hojas._parrafos(_cortada)) == 2)
_entrada = ("el término RIVOTAN aparece en el índice general y en el registro de datos consultados.<br/>"
            "ZORKAMEL El indicador del sector oeste resume las mediciones principales.<br/>"
            "Esta tabla y las categorías relacionadas corresponden a la sección de resultados.")
check("párrafos: una entrada en MAYÚSCULAS abre párrafo aunque la anterior no lleve punto",
      len(_hojas._parrafos(_entrada)) == 3)
check("tipografía: las llamadas de nota pegadas se vuelan",
      _hojas._tipografia("estimación aproximada8, y resultado10 del informe").count("<sup>") == 2)
check("tipografía: una conjunción con nota también («y11»)",
      _hojas._tipografia("la variable independiente y11 resultado").count("<sup>") == 1)
check("tipografía: números, decimales, grados y horas se dejan en paz",
      _hojas._tipografia("en 1508 y el 12,5 por ciento, a 20°C y las 14:30").count("<sup>") == 0)
check("tipografía: una fórmula no es nota («H2O»)",
      "<sup>" not in _hojas._tipografia("el H2O hierve"))
check("tipografía: la tirada de guiones bajos del escaneo vuelve a ser una regla",
      _hojas._tipografia("texto ______________________ más") == "texto <hr> más")
_colilla = _hojas._tipografia("texto<br/>_______________________<br/>__<br/>TÍTULO")
check("tipografía: no queda ni la colilla de la regla partida",
      "_" not in _colilla and "<hr>" in _colilla)
import types as _types, time as _time
import translate as _tr
class _Resp429:
    status_code, headers = 429, {}
    text = '{"error":{"message":"Rate limit reached: try again in 5m0s"}}'
_b = _tr.CloudBackend.__new__(_tr.CloudBackend)
for _k, _v in dict(provider="pruebas", base="http://x", model="m", timeout=5, temperature=0.0,
                   MAX_ESPERA_TOTAL=60, _max_out=0, reasoning_effort="", src_name="inglés",
                   tgt_name="español", register="", tone="fluida").items():
    setattr(_b, _k, _v)
_b._session = _types.SimpleNamespace(post=lambda *a, **k: _Resp429())
_b._load_key = lambda: "k"
_red, _t = _tr.con_red, _tr.time
_tr.con_red = lambda f, *a, **k: f()
_tr.time = _types.SimpleNamespace(sleep=lambda s: None, time=_time.time)
try:
    _b._chat("sys", "hola")
    _corto = False
except RuntimeError as _e:
    _corto = "me rindo" in str(_e)
except Exception:
    _corto = False
_tr.con_red, _tr.time = _red, _t
check("espera: un 429 eterno no cuelga el libro, se rinde y deja probar otra clave", _corto)

check("tipografía: un guion entre palabras no se toca",
      _hojas._tipografia("guion-medio compuesto") == "guion-medio compuesto")

_dos_secciones = ([f"LIBRO UNO {n} {c}" for n, c in enumerate(_cuerpos)]
                  + [f"LIBRO UNO {n} otra frase distinta {n}" for n in range(8, 14)]
                  + [f"LIBRO DOS {n} {c}" for n, c in enumerate(_cuerpos)]
                  + [f"LIBRO DOS {n} y una más por aquí {n}" for n in range(8, 14)])
_hall = _hojas.detectar_encabezados(_dos_secciones)
check("encabezados: detecta los DOS que tiene el libro, no solo el más repetido",
      len(_hall) == 2 and {" ".join(r[:2]).upper() for r in _hall} == {"LIBRO UNO", "LIBRO DOS"})
check("encabezados: quita el de la sección que toque, sea cual sea",
      all(_hojas.quitar_encabezado(_hojas.quitar_encabezado("LIBRO DOS 9 el viento trae polvo", _hall[0]),
                                   _hall[1]).startswith("el viento") for _ in [0]))

_ref = _hojas.detectar_encabezado(_pags)
check("hojas: detecta el encabezado corrido", _ref is not None and _ref[:3] == ["UN", "MANUAL", "MODERNO"])
check("hojas: lo quita aunque el OCR lo escriba distinto",
      _hojas.quitar_encabezado("UN MANUEL MODERNO DE ASTRONOMIA cuando amanece todo cambia", _ref) == "cuando amanece todo cambia")
check("hojas: sin encabezado repetido no inventa uno",
      _hojas.detectar_encabezado(["amanece sobre la sierra nevada", "los barcos regresan al puerto", "nadie recuerda aquel verano",
                                  "una carta llegó sin remitente", "el molino dejó de girar", "bajo el puente corre el agua",
                                  "siempre hubo un camino más corto", "la lluvia borró las huellas"]) is None)
check("hojas: quita el folio -5-", _hojas.quitar_folio("termina la frase. -5-") == "termina la frase.")
check("hojas: quita el folio 36-", _hojas.quitar_folio("termina la frase, 36-") == "termina la frase,")
check("hojas: no toca un número dentro del texto", _hojas.quitar_folio("capítulo 12 del libro") == "capítulo 12 del libro")
check("figuras: la figura va en su posición relativa",
      [t for t, _ in _fig.colocar(["aaaa", "bbbb", "cccc", "dddd"], [(0.5, "F")])] == ["p", "p", "f", "p", "p"])
check("figuras: quita rótulos con símbolos al final",
      _fig.quitar_cola("Texto del libro. ABC△ rótulo uno dos tres") == "Texto del libro.")
check("figuras: no toca un final de frase normal",
      _fig.quitar_cola("Texto del libro. Y sigue el párrafo con más palabras") == "Texto del libro. Y sigue el párrafo con más palabras")
check("figuras: quita rótulos al inicio, no texto del libro",
      _fig.quitar_cabeza("0+ 5 Norte~ Water [Delta] Como puedes ver el texto sigue") == "Como puedes ver el texto sigue"
      and _fig.quitar_cabeza("Haz un pequeño corte en el borde superior y lo llevas puesto") == "Haz un pequeño corte en el borde superior y lo llevas puesto")

print("== Render: resaltado sin anclas anidadas ==")
html = render._highlight(
    render._esc("ZORKAMEL RIVOTAN y ZORKAMEL y ZORKAMEL"),
    [(re.compile(re.escape("ZORKAMEL RIVOTAN"), re.I), 1, "ZORKAMEL RIVOTAN"),
     (re.compile(re.escape("ZORKAMEL"), re.I), 2, "ZORKAMEL"),
     (re.compile(re.escape("ZORKAMEL"), re.I), 3, "ZORKAMEL")])
check("no hay anclas anidadas", "<a" in html and "<a class=\"term\" href=\"#t1\">ZORKAMEL RIVOTAN</a>" in html)
check("cuenta de anclas correcta (3)", html.count("<a class=\"term\"") == 3)

print("== Fix: falsos positivos de MAYÚSCULAS ==")
m2 = Masker(glossary=[], auto_detect=True, allcaps_min_len=3)
_, mp = m2.mask("THE BOOK OF THE LAW")
check("no enmascara encabezado en versalitas", mp == {})
_, mp = m2.mask("See Chapter III and Section IV")
check("no enmascara números romanos", mp == {})
_, mp = m2.mask("Available as PDF in the USA")
check("no enmascara siglas comunes (PDF/USA)", mp == {})
_, mp = m2.mask("Write ZORKAMEL now")
check("sí enmascara ZORKAMEL", "ZORKAMEL" in mp.values())
_, mp = m2.mask("El nombre ΛΟΓΟΣ aparece en el documento")
check("enmascara mayúsculas griegas (unicode)", any("ΛΟΓΟΣ" in v for v in mp.values()))

print("== Fix: restauración tolerante a separadores ==")
r, lost = _restore("el MWTKN 0 y mwtkn-1 aqui", {"MWTKN0": "ZORKAMEL", "MWTKN1": "AUM"})
check("restaura 'MWTKN 0' con espacio", "ZORKAMEL" in r)
check("restaura 'mwtkn-1' con guion", "AUM" in r)
check("sin tokens crudos MWTKN visibles", not TOKEN_RE.search(r) and "MWTKN" not in r)
check("nada perdido", lost == [])
r2, _ = _restore("MWTKN1 y MWTKN10", {"MWTKN1": "A", "MWTKN10": "B"})
check("no confunde MWTKN1 con MWTKN10", r2 == "A y B")

print("== Romanización determinística ==")
from romanize import romanize
check("griego λόγος -> logos", romanize("λόγος").lower() == "logos")
check("griego λόγος romaniza con 'th'", romanize("λόγος").lower().startswith("logos"))
check("hebreo שלום romaniza no vacío", bool(romanize("שלום")))
check("latín no cambia", romanize("Hello") == "Hello")

print("== Máscara de alfabetos no latinos + romanización ==")
mnl = Masker(glossary=[], auto_detect=False, detect_nonlatin=True)
masked_g, map_g = mnl.mask("el artículo incluye la palabra λόγος en el ejemplo")
check("enmascara la palabra griega", any("λόγος" == v for v in map_g.values()))
check("expone romanización del término", mnl.romanizations.get("λόγος", "").lower() == "logos")
tr, lost_g, _ = translate_and_review(masked_g, map_g, DummyBackend(), passes=0)
check("griego preservado tras traducir (segment)", "λόγος" in tr and lost_g == [])
_, map_r = Masker(glossary=[], auto_detect=True, detect_nonlatin=True).mask("Chapter XVII of IV")
check("romanos no se enmascaran aun con no-latino activo", map_r == {})

print("== Render: romanización inline (primera aparición) + apéndice ==")
mnl2 = Masker(glossary=[], auto_detect=False, detect_nonlatin=True)
mnl2.mask("λόγος y otra vez λόγος")
outp = "___rom_test.html"
render.render_html(
    [{"number": 1, "mode": "text", "rows": [("text", "λόγος y λόγος", "λόγος y λόγος")]}],
    mnl2.terms, outp, title="t", romanizations=mnl2.romanizations)
hc = open(outp, encoding="utf-8").read()
os.remove(outp)
check("muestra romanización (logos) inline", "(logos)" in hc.lower())
check("romanización 1x por columna + apéndice (=3)", hc.lower().count("(logos)") == 3)

print("== Pronunciación ==")
import pronounce as pron
check("respell 'logos' -> LO-gos", pron.respell("logos") == "LO-gos")
check("respell 'PLUMBATAX' con acento", pron.respell("PLUMBATAX") == "plum-BA-tax")
check("voz griega para término griego", pron._voice_for("λόγος") == "el")
check("voz hebrea para término hebreo", pron._voice_for("שלום") == "he")
check("voz latina para alfabeto latino", pron._voice_for("PLUMBATAX") == "la")
pr = pron.pronounce("λόγος", "logos")
check("griego: IPA de la voz griega si hay espeak, si no guía; la guía siempre",
      pr["guia"] == "LO-gos" and (pr["kind"] == "IPA" if pron.have_espeak() else pr["kind"] == "aprox"))
check("latino: guía silábica primero, IPA latino de apoyo",
      pron.pronounce("ZORKAMEL")["say"] == pron.respell("ZORKAMEL"))
check("silabeo: zor-KA-mel, ri-VO-tan, plum-BA-tax",
      (pron.respell("ZORKAMEL"), pron.respell("RIVOTAN"), pron.respell("PLUMBATAX"))
      == ("zor-KA-mel", "ri-VO-tan", "plum-BA-tax"))
check("sin audio si no se pide/no hay espeak", pr["audio_b64"] is None)

print("== Render: pronunciación en apéndice ==")
mnl3 = Masker(glossary=[], auto_detect=False, detect_nonlatin=True)
mnl3.mask("λόγος")
outp2 = "___pron_test.html"
render.render_html(
    [{"number": 1, "mode": "text", "rows": [("text", "λόγος", "λόγος")]}],
    mnl3.terms, outp2, title="t",
    romanizations=mnl3.romanizations,
    pronunciations={t: pron.pronounce(t, mnl3.romanizations.get(t)) for t in mnl3.terms})
hp = open(outp2, encoding="utf-8").read()
os.remove(outp2)
check("apéndice muestra la guía de pronunciación", "LO-gos" in hp and "pronunciación" in hp)

print("== Limpieza de texto (traducción correcta) ==")
import textclean
check("une guion de línea 'funda- mentals'", textclean.clean("funda- mentals") == "fundamentals")
check("quita guion suave 'an\\xadcient'", textclean.clean("an­cient") == "ancient")
check("espacio duro -> normal", textclean.clean("a b c") == "a b c")
check("no une raya espaciada", textclean.clean("el building - un lugar") == "el building - un lugar")
check("no une si hay mayúscula 'Anti- Christ'", textclean.clean("Anti- Christ") == "Anti- Christ")
check("junk: ruta file://", textclean.is_junk("file:///C|/home/example/file.txt[22-9-2009 19:53:00]"))
check("junk: URL suelta", textclean.is_junk("https://example.com/a"))
check("no-junk: texto normal", not textclean.is_junk("RIVOTAN is a rare term"))

print("== Tipo de texto: especializado activa lo especial, el resto no ==")
from config import Config, apply_type_defaults
import main as _main
gl = ["ZORKAMEL", "PLUMBATAX"]
mkm = _main.make_masker((lambda c: (setattr(c, "book_type", "especializado"), c)[1])(Config()), gl)
_, mm = mkm.mask("El texto incluye ZORKAMEL y PLUMBATAX")
check("especializado: enmascara glosario", "ZORKAMEL" in mm.values() and "PLUMBATAX" in mm.values())
cfga = Config(); cfga.book_type = "articulo"
_, ma = _main.make_masker(cfga, gl).mask("El grupo PLUMBATAX y el nombre ZORKAMEL")
check("articulo: NO enmascara glosario (evita falso positivo 'PLUMBATAX')", ma == {})
_, mnl_a = _main.make_masker(cfga, gl).mask("La palabra λόγος aquí")
check("articulo: sí preserva no-latino", any(v == "λόγος" for v in mnl_a.values()))

print("== Origen francés: detecta bloque que quedó en francés ==")
cfr = Config(); cfr.source_lang = "fr"
_fr = "Ensuite vous observerez le paysage et noterez les changements au fil des saisons"
_es = "Luego observarás el paisaje y anotarás los cambios a lo largo de las estaciones"
check("fr: salida en francés = mala", _main.bad_translation(_fr, _fr, cfr))
check("fr: salida en español = buena", not _main.bad_translation(_fr, _es, cfr))
check("en: el francés no dispara el chequeo inglés", not _main.bad_translation(_fr, _fr, Config()))

print("== Fixes de auditoría (revisión de nuevo) ==")
from romanize import romanize as _rom
check("Ῥώμη -> Rhome (rho con 'rh')", _rom("Ῥώμη") == "Rhome")
check("ῥήτωρ -> rhetor", _rom("ῥήτωρ").lower().startswith("rhetor"))
check("solo puntuación -> ''", _rom("·") == "")
check("pronounce no-latino -> guía latina", bool(pron.pronounce("λόγος")["guia"]))
check("is_junk file://host", textclean.is_junk("file://host/x"))
import lexicon as _lex
_lx = _lex.Lexicon([{"original": "λόγος", "translit": "logos", "es_cl": "i-a-Ó", "ref": "fuente"},
                    {"original": "68. ZORKAMEL", "translit": "Rey", "es_cl": "", "ref": "antología"}])
check("léxico casa por original griego", _lx.get("λόγος") is not None)
check("léxico casa por translit normalizada", _lx.get("logos") is not None)
check("léxico casa nombre con numeración", _lx.get("ZORKAMEL") is not None)
check("léxico ignora rango como clave", _lx.get("Rey") is None)
check("curada gana: usa es_cl del léxico",
      pron.pronounce("λόγος", curated=_lx.get("λόγος"))["kind"] == "curada")
check("sin es_cl -> respaldo aprox (nunca vacío)",
      bool(pron.pronounce("ZORKAMEL", curated=_lx.get("ZORKAMEL"))["say"]))
check("clean normaliza espacios raros", textclean.clean("a b c　d") == "a b c d")

_c = "___cit_off.html"
render.render_html([{"number": 1, "mode": "text", "rows": [("text", "ZORKAMEL", "ZORKAMEL")]}],
                   ["ZORKAMEL"], _c, title="t")
_h = open(_c, encoding="utf-8").read(); os.remove(_c)

render.render_html([{"number": 1, "mode": "text", "rows": [("text", "el sol brilla", "el sol brilla")]}],
                   ["SOL"], _c, title="t")
_h = open(_c, encoding="utf-8").read(); os.remove(_c)
check("resaltado case-sensitive: 'sol' no se marca como 'SOL'", 'class="term"' not in _h)

print("== Caché de traducciones (reanudar) ==")
import transcache
_db = "___tc_test.db"
if os.path.exists(_db):
    os.remove(_db)
_tc = transcache.TranslationCache(_db, True)
_tc.set("SIG", "hola", "HOLA")
check("cache set/get", _tc.get("SIG", "hola") == "HOLA")
check("cache miss con otra firma", _tc.get("OTRA", "hola") is None)
_tc.close()
_tc2 = transcache.TranslationCache(_db, True)
check("cache persiste (reanudar)", _tc2.get("SIG", "hola") == "HOLA")
_tc2.close()
os.remove(_db)
_off = transcache.TranslationCache("", False)
_off.set("s", "a", "b")
check("cache deshabilitado no guarda", _off.get("s", "a") is None)

print("== Agrupar bloques en chunks ==")
check("junta pequeños en un chunk", _main._group_texts(["aa", "bb", "cc"], 100) == ["aa\n\nbb\n\ncc"])
check("separa al exceder el tope", len(_main._group_texts(["a" * 60, "b" * 60], 100)) == 2)
check("0 = no agrupa", _main._group_texts(["a", "b"], 0) == ["a", "b"])
check("filtra textos vacíos", _main._group_texts(["a", "", ""], 0) == ["a"])

print("== Orden de lectura (columnas) ==")
import extract as _ex
from types import SimpleNamespace as _NS
def _it(x0, y0, x1=None):
    return _NS(type="text", bbox=(x0, y0, (x1 if x1 is not None else x0 + 60), y0 + 10))
_rect = _NS(x0=0, y0=0, width=600, height=800)
_two = _ex._order_items([_it(320, 100), _it(40, 500), _it(320, 600), _it(40, 120)], _rect)
check("2 columnas: izquierda antes que derecha", [it.bbox[0] for it in _two] == [40, 40, 320, 320])
_one = _ex._order_items([_it(40, 60), _it(40, 40)], _rect)
check("1 columna: orden natural por y", [it.bbox[1] for it in _one] == [40, 60])
_title = _it(40, 110, 560)
_wt = _ex._order_items([_it(320, 200), _it(40, 600), _title, _it(40, 220), _it(320, 650)], _rect)
check("título a ancho total separa bandas", _wt[0] is _title and [it.bbox[0] for it in _wt[1:]] == [40, 40, 320, 320])
_c3 = [_it(40, 150), _it(40, 600), _it(250, 160, 350), _it(250, 610, 350), _it(430, 170), _it(430, 620)]
_o3 = _ex._order_items(_c3, _rect)
check("3 columnas (central cruza el centro): cae a orden natural",
      _o3 == sorted(_c3, key=lambda it: (round(it.bbox[1], 1), round(it.bbox[0], 1))))

print("== Deskew (enderezar escaneos) ==")
try:
    import numpy as _np
    from PIL import Image as _Img, ImageDraw as _Dr
    import ocr as _ocr
    _im = _Img.new("L", (400, 300), 255); _d = _Dr.Draw(_im)
    for _y in range(30, 270, 24):
        _d.rectangle([30, _y, 370, _y + 8], fill=0)
    _tilt = _im.rotate(-3, resample=_Img.BILINEAR, fillcolor=255, expand=True)
    _fix = _ocr._deskew(_tilt)
    def _score(_i):
        _a = 255.0 - _np.asarray(_i.convert("L"), dtype=_np.float32)
        _p = _a.sum(axis=1)
        return float(((_p[1:] - _p[:-1]) ** 2).sum())
    check("deskew endereza (nitidez de filas sube)", _score(_fix) > _score(_tilt) * 5)
except Exception as _e:
    print(f"  (omitido: numpy/PIL no disponibles — {_e})")

print(f"\nRESULTADO: {ok} OK, {fail} FALLOS")
raise SystemExit(1 if fail else 0)
