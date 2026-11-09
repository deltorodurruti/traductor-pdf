#!/usr/bin/env bash
set -uo pipefail
AQUI=$(cd "$(dirname "$0")" && pwd)
ENTREGA=${ENTREGA:-$HOME/traductor/libros_esp}
PY="${PYTHON:-${PY:-$(command -v python3)}}"
"$PY" -c 'import fitz, bs4' 2>/dev/null || { echo "El intérprete $PY no tiene las dependencias; define PYTHON=/ruta/python3" >&2; exit 1; }
VERBOSO=""; [ "${1:-}" = "-v" ] && { VERBOSO=1; shift; }
FILTRO=${1:-}

V=$'\e[32m'; A=$'\e[33m'; R=$'\e[31m'; GR=$'\e[90m'; N=$'\e[0m'; B=$'\e[1m'
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT

printf '%sRevisando los libros de %s%s\n\n' "$B" "$ENTREGA" "$N"
for f in "$ENTREGA"/*.pdf; do
  [ -e "$f" ] || continue
  if [ -n "$FILTRO" ]; then
    case "$(basename "$f" | tr '[:upper:]' '[:lower:]')" in
      *$(echo "$FILTRO" | tr '[:upper:]' '[:lower:]')*) ;;
      *) continue ;;
    esac
  fi
  salida=$($PY "$AQUI/herramientas/escanear_pdf.py" "$f" 2>/dev/null)
  linea=$(printf '%s' "$salida" | head -1)
  pags=$(printf '%s' "$linea"  | sed -n 's/.*págs \([0-9]*\).*/\1/p')
  ingles=$(printf '%s' "$linea"| sed -n 's/.*en inglés \([0-9]*\).*/\1/p')
  basura=$(printf '%s' "$linea"| sed -n 's/.*basura \([0-9]*\).*/\1/p')
  printf '%s\t%s\t%s\t%s\n' "$(( ${ingles:-0} + ${basura:-0} ))" "$(basename "$f")" \
    "${pags:-?}" "${ingles:-0}/${basura:-0}" >> "$TMP"
  [ -n "$VERBOSO" ] && printf '%s' "$salida" | tail -n +2 | sed 's/^/      /'
done

printf '%s%-52s %6s %8s %9s%s\n' "$B" "LIBRO" "PÁGS" "INGLÉS" "BASURA" "$N"
sort -rn "$TMP" | while IFS=$'\t' read -r suma nom pags par; do
  ing=${par%%/*}; bas=${par##*/}
  if   [ "$suma" -eq 0 ];  then c=$V
  elif [ "$suma" -lt 20 ]; then c=$A
  else c=$R; fi
  printf '%s%-52s %6s %8s %9s%s\n' "$c" "${nom:0:52}" "$pags" "$ing" "$bas" "$N"
done
printf '\n%singlés = bloques que quedaron sin traducir (las bibliografías cuentan y son correctas)\n' "$GR"
printf 'basura = texto roto del OCR del original, tablas o fechas; mirar con -v antes de alarmarse%s\n' "$N"
