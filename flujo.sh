#!/usr/bin/env bash
set -uo pipefail
FUENTE="$0"
while [ -L "$FUENTE" ]; do
  DIR=$(cd "$(dirname "$FUENTE")" && pwd); FUENTE=$(readlink "$FUENTE")
  case "$FUENTE" in /*) ;; *) FUENTE="$DIR/$FUENTE";; esac
done
AQUI=$(cd "$(dirname "$FUENTE")" && pwd)
export TRAB=${TRAB:-$HOME/traductor/taller}
PY="${PYTHON:-${PY:-$(command -v python3)}}"
"$PY" -c 'import fitz, bs4' 2>/dev/null || { echo "El intérprete $PY no tiene las dependencias; define PYTHON=/ruta/python3" >&2; exit 1; }
REG=$TRAB/flujo.log
V=$'\e[32m'; A=$'\e[33m'; AZ=$'\e[36m'; GR=$'\e[90m'; N=$'\e[0m'; B=$'\e[1m'

di() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$1" | tee -a "$REG"; }
avisa() { osascript -e "display notification \"$1\" with title \"Libros\"" >/dev/null 2>&1; }
libros() { "$AQUI/estado.py" --libros; }
etapa() {
  local e; e=$("$AQUI/estado.py" --etapa "$1" 2>&1 | tail -1)
  case "$e" in [0-3]\ *) echo "$e";; *) echo "0 ✗ no puedo saber la etapa: $e";; esac
}
huella() { printf '%s @ %s\n' "$1" "$(stat -f %m "$TRAB/$2"/*_es.html 2>/dev/null | head -1)"; }
parado() { [ -f "$TRAB/$2/.parado" ] && [ "$(cat "$TRAB/$2/.parado")" = "$(huella "$1" "$2")" ]; }

case "${1:-}" in
  -h|--help) sed -n '2,/^set -/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0;;
  --log)     exec tail -n 40 -f "$REG";;
  --alta)    shift; exec "$AQUI/entregas.py" --alta "$@";;
  --reintentar)
    [ -n "${2:-}" ] || { echo "uso: $0 --reintentar LIBRO"; exit 1; }
    rm -f -- "${TRAB:?}/${2:?}/.parado"; di "↺ $2: marca de parado borrada, se reintenta"; exec "$0" "$2";;
  --parar)
    mio=$(ps -o pgid= -p $$ | tr -d ' '); n=0
    for p in $(pgrep -f "flujo.sh"); do
      [ "$p" = "$$" ] && continue
      g=$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')
      [ -z "$g" ] || [ "$g" = "$mio" ] && continue
      kill -- -"$g" 2>/dev/null && n=$((n + 1))
    done
    sleep 2
    pkill -f "pdf-translator/(rotar_libro\.sh|herramientas/libro\.sh|completar_libro\.py|entregar_libro\.py)" 2>/dev/null
    pkill -f "main\.py .*_traduccion" 2>/dev/null
    di "■ flujo parado ($n grupo(s)); lo traducido queda en la caché y se retoma al relanzar"; exit 0;;
  --ver)
    printf '\n%s%s ETAPA DE CADA LIBRO %s\n\n' "$B" "$AZ" "$N"
    for l in $(libros); do
      e=$(etapa "$l"); n=${e%% *}; resto=${e#* }
      parado "$e" "$l" && resto="$resto · ⏸ la guarda no deja entregar (--reintentar $l)"
      case "$n" in 0) c=$GR;; 1) c=$AZ;; 2) c=$A;; *) c=$V;; esac
      printf '  %s%-24s%s %s%s%s\n' "$B" "$l" "$N" "$c" "$resto" "$N"
    done
    echo; exit 0;;
esac

NOCHE=""
case " $* " in *" --noche "*) NOCHE=1;; esac
ARGS=$(echo "$*" | sed 's/--noche//')
PEDIDOS=${ARGS:-$(libros)}

if [ -n "$NOCHE" ]; then
  vuelta=0
  while :; do
    vuelta=$((vuelta + 1))
    todos=$(for l in $(libros); do
              e=$(etapa "$l"); n=${e%% *}
              [ "$n" = "0" ] && continue
              parado "$e" "$l" && continue
              echo "$l"
            done)
    pendientes=$(
      for l in $ARGS;  do echo "$todos" | grep -qx "$l" && echo "$l"; done
      for l in $todos; do echo "$ARGS" | tr " " "\n" | grep -qx "$l" || echo "$l"; done
    )
    if [ -z "$pendientes" ]; then
      parados=$(ls "$TRAB"/*/.parado 2>/dev/null | wc -l | tr -d ' ')
      di "✅ no queda nada pendiente ($parados parado(s) por la guarda); fin tras $vuelta vuelta(s)"
      avisa "Libros: nada pendiente, $parados parado(s) por la guarda"; exit 0
    fi
    di "╔═ vuelta $vuelta · pendientes: $(echo "$pendientes" | tr '\n' ' ')"
    ESPERAR=0 "$0" $pendientes
    di "╚═ vuelta $vuelta hecha; espero 30 min a que se libere cupo"
    sleep 1800
  done
fi

di "═══ flujo sobre $(echo "$PEDIDOS" | wc -w | tr -d ' ') libro(s) ═══"
for libro in $PEDIDOS; do
  d=$TRAB/$libro
  [ -d "$d" ] || { di "✗ $libro: no existe esa carpeta"; continue; }
  di "── $libro · empieza en etapa $(etapa "$libro")"
  glos=$(ls "$d"/glosario*.txt 2>/dev/null | head -1)
  anterior=""
  while :; do
    e=$(etapa "$libro"); n=${e%% *}
    [ "$n" = "0" ] && break
    if parado "$e" "$libro"; then
      di "   ⏸ la guarda no dejó entregar y nada cambió desde entonces (./flujo.sh --reintentar $libro)"; break
    fi
    rm -f -- "${d:?}/.parado"
    [ "$e" = "$anterior" ] && { di "   ⏸ no avanza desde «$e»; lo dejo aquí"; break; }
    anterior=$e
    case "$n" in
      1)  orig=$(ls "$d"/*.pdf 2>/dev/null | grep -vE "_ES|_nuevo|_v[0-9]|antes|limpio|trabajo" | head -1)
          di "   1/3 traducir · $(basename "$orig")"
          "$AQUI/rotar_libro.sh" "$d" "$orig" ${glos:+"$glos"} >>"$REG" 2>&1
          ;;
      2)  html=$(ls "$d"/*_es.html 2>/dev/null | head -1)
          if [ -z "$html" ]; then
            bilingue=$(ls "$d"/*_bilingue.html 2>/dev/null | head -1)
            [ -n "$bilingue" ] || { di "✗ no encuentro HTML bilingüe para verificar"; break; }
            html="${bilingue%_bilingue.html}_es.html"
            di "   verificar · $(basename "$bilingue")"
            "$PY" "$AQUI/_verify_book.py" "$bilingue" "$html" en >>"$REG" 2>&1 || break
          fi
          di "   2/3 completar lo que quedó en inglés"
          "$PY" -u "$AQUI/completar_libro.py" "$html" ${glos:+"$glos"} --yes-cloud >>"$REG" 2>&1
          ;;
      3)  di "   3/3 maquetar y entregar"
          salida=$("$PY" "$AQUI/entregar_libro.py" --corrido --forzar "$libro" 2>&1 | tee -a "$REG" | grep -E "✅|✗")
          printf '%s\n' "$salida" | sed 's/^/   /'
          case "$salida" in
            *✅*) avisa "$libro entregado";;
            *"✗ empeora"*) huella "$(etapa "$libro")" "$libro" > "$d/.parado"; avisa "$libro: la guarda no deja entregar";;
          esac
          ;;
      *)  break;;
    esac
  done
  di "   → queda en: $(etapa "$libro")"
done
di "═══ fin ═══"
