#!/usr/bin/env bash
set -euo pipefail

[ $# -ge 2 ] || { sed -n '2,15p' "$0"; exit 1; }
ORIG=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
TRAB=$2; DEST=${3:-}
RAIZ=$(cd "$(dirname "$0")/.." && pwd)
PY="${PYTHON:-${PY:-$(command -v python3)}}"
"$PY" -c 'import fitz, bs4' 2>/dev/null || { echo "El intérprete $PY no tiene las dependencias; define PYTHON=/ruta/python3" >&2; exit 1; }
MOTOR=${MOTOR:-groq}
MODELO=${MODELO:-}
mkdir -p "$TRAB"; TRAB=$(cd "$TRAB" && pwd)
N=$(basename "${ORIG%.pdf}")
BIL=$TRAB/${N}_bilingue.html; ES=$TRAB/${N}_es.html; PDF=$TRAB/${N}_ES.pdf
cd "$RAIZ"

paso() { printf '\n== %s\n' "$1"; }

traducir() {
  local salida=$1; shift
  OCR_MOTOR=${OCR_MOTOR:-doble} "$PY" -u main.py "$ORIG" --yes --yes-cloud --engine "$MOTOR" \
    ${MODELO:+--cloud-model "$MODELO"} \
    --razonamiento "${RAZONAMIENTO:-medium}" --chunk-chars 2800 --borrador edge --review-passes 1 --book-type especializado \
     --no-pdf --no-diagramas --ocr "${OCR_MODO:-auto}" ${OCR_DPI:+--ocr-dpi "$OCR_DPI"} \
    ${GLOSARIO:+--glosario-extra "$GLOSARIO"} --out "$salida" "$@"
}

paso "1. Traducir (se repite hasta que no quede ningún bloque sin traducir; los de origen ilegible no cuentan)"
if [ ! -s "$BIL" ]; then
  for intento in 1 2 3; do
    traducir "$BIL" 2>&1 | tee "$TRAB/traducir_$intento.log" | tail -3
    n=$(grep -o "[0-9]* bloques quedaron SIN traducir" "$TRAB/traducir_$intento.log" | grep -o "^[0-9]*" || true); [ -z "$n" ] && break
    [ "$n" = "${prev:-}" ] && break
    prev=$n
  done

fi

if [ "${SOLO_TRADUCIR:-0}" = "1" ]; then
  echo "✓ traducción guardada: $BIL"
  exit 0
fi

paso "2. Verificar y sacar el solo-español"
[ -s "$ES" ] || "$PY" _verify_book.py "$BIL" "$ES" en | tail -5

paso "3. Completar lo que quedó en inglés"
"$PY" herramientas/completar_bloques.py "$ES" --motor "$MOTOR" ${GLOSARIO:+--glosario "$GLOSARIO"} --yes-cloud --aplicar | tail -2

paso "4. Pulir (encabezado corrido y pies de interfaz siempre; nombres congelados, mojibake, hebreo, índice si se piden)"
[ -n "${REEMPLAZOS:-}${PULIR:-}" ] && [ -e "$ES.pulir" ] && cp "$ES.pulir" "$ES"
"$PY" herramientas/pulir.py "$ES" --interfaz ${REEMPLAZOS:+--reemplazos "$REEMPLAZOS"} ${REEMPLAZOS:+--sin-mojibake} ${PULIR:-} --aplicar | tail -2

if [ -z "${TABLAS:-}" ] && "$PY" -c "import sys,fitz; sys.path.insert(0,'herramientas'); import paginas_con_tablas as P; sys.exit(0 if P.paginas_con_tablas(fitz.open(sys.argv[1])) else 1)" "$ORIG" 2>/dev/null; then TABLAS=auto; fi
if [ -n "${TABLAS:-}" ]; then
  paso "5. Páginas con tablas (tablas reales, hebreo recuperado)"
  "$PY" herramientas/paginas_con_tablas.py "$ORIG" "$ES" auto ${GLOSARIO:+--glosario "$GLOSARIO"} --yes-cloud --aplicar | tail -2
  [ -n "${REEMPLAZOS:-}${PULIR:-}" ] && "$PY" herramientas/pulir.py "$ES" ${REEMPLAZOS:+--reemplazos "$REEMPLAZOS"} --sin-mojibake ${PULIR:-} --aplicar | tail -1
fi

paso "6. Maquetar hoja a hoja con las figuras del original (sin bloques de texto inglés)"
"$PY" hojas.py "$ES" "$PDF" --original "$ORIG" ${SOLO_IMAGEN:+--solo-imagen "$SOLO_IMAGEN"} | tail -3

paso "7. Auditar las imágenes y pegar las que falten (las figuras no se traducen)"
"$PY" herramientas/auditar_imagenes.py "$ORIG" "$PDF" "$TRAB/auditoria" | tail -4
"$PY" herramientas/pegar_figuras.py "$ORIG" "$PDF" "$TRAB/${N}_figuras.pdf" "$TRAB/auditoria" | tail -1
[ -s "$TRAB/${N}_figuras.pdf" ] && mv "$TRAB/${N}_figuras.pdf" "$PDF"

paso "8. Revisar el PDF (inglés suelto, basura de OCR, encabezados repetidos)"
"$PY" herramientas/escanear_pdf.py "$PDF" | head -8 || true


if [ -n "$DEST" ]; then
  paso "9. Entregar"
  cp "$PDF" "$DEST" && echo "→ $DEST"
fi
