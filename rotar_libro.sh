#!/usr/bin/env bash
set -uo pipefail
AQUI=$(cd "$(dirname "$0")" && pwd)
TRAB=$1; ORIG=$2; GLOS=${3:-}
REG=$TRAB/rotacion.log
SIN_CUPO=$("$AQUI/claves.py" --sin-cupo)

apunta() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$1" | tee -a "$REG"; }
arbol() { local h; for h in $(pgrep -P "$1" 2>/dev/null); do arbol "$h"; done; echo "$1"; }
mata() { local todos; todos=$(arbol "$1"); kill $todos 2>/dev/null; sleep 2; kill -9 $todos 2>/dev/null; }
reciente() { ls -t "$TRAB"/*.log 2>/dev/null | grep -v 'rotacion.log' | head -1; }
paso() { grep -o '^== [0-9]*' "$TRAB/libro_rotado.log" 2>/dev/null | tail -1; }

CLAVES=$("$AQUI/claves.py" --env)
[ -n "$CLAVES" ] || { apunta "✗ no encuentro ninguna clave (prueba: ./claves.py)"; exit 1; }
MARCA=$TRAB/.inicio_rotacion; : > "$MARCA"
apunta "=== $(basename "$TRAB") · $(printf '%s\n' "$CLAVES" | wc -l | tr -d ' ') claves ==="
ciclo=0
while :; do
  while read -r motor k vars; do
    [ -n "$motor" ] || continue
    apunta "→ $motor $(basename "$k")"
    DESDE=$TRAB/.clave_actual; : > "$DESDE"
    env MOTOR="$motor" SOLO_TRADUCIR=1 GLOSARIO="${GLOS:-}" $vars \
      nice -n 10 "$AQUI/herramientas/libro.sh" "$ORIG" "$TRAB" </dev/null >>"$TRAB/libro_rotado.log" 2>&1 &
    pid=$!
    ult_pag=''; t_pag=$(date +%s)
    while kill -0 "$pid" 2>/dev/null; do
      sleep 45
      [ "$(paso)" = "== 1" ] || continue
      p=$(find "$TRAB" -maxdepth 1 -name '*.log' -newer "$DESDE" \
            ! -name rotacion.log ! -name libro_rotado.log -exec grep -ohE 'pág [0-9]+/' {} + 2>/dev/null \
            | grep -oE '[0-9]+' | sort -n | tail -1)
      if [ -n "$p" ] && [ "$p" != "$ult_pag" ]; then
        ult_pag=$p; t_pag=$(date +%s)
      elif [ -n "$ult_pag" ] && [ $(( $(date +%s) - t_pag )) -gt "${ESTANCADO:-1200}" ]; then
        apunta "   $motor $(basename "$k") estancado: $(( ($(date +%s) - t_pag) / 60 )) min escribiendo sin pasar de pág $ult_pag, cambio"
        mata "$pid"; break
      fi
      log=$(reciente); [ -n "$log" ] || continue
      quieto=$(( $(date +%s) - $(stat -f %m "$log") ))
      if [ "$quieto" -gt "${ATASCO:-600}" ]; then
        apunta "   $motor $(basename "$k") colgado: $((quieto / 60)) min sin escribir en $(basename "$log"), corto"
        mata "$pid"; break
      fi
      nuevas=$(find "$TRAB" -maxdepth 1 -name '*.log' -newer "$DESDE" \
                 ! -name rotacion.log ! -name libro_rotado.log -exec tail -n 40 {} + 2>/dev/null)
      if printf '%s\n' "$nuevas" | grep -qEi "$SIN_CUPO"; then
        pide=$(printf '%s\n' "$nuevas" | "$AQUI/claves.py" --espera)
        if ! printf '%s\n' "$nuevas" | grep -q "me rindo" && [ "${pide:-0}" -gt 0 ] && [ "$pide" -le 150 ]; then
          continue
        fi
        apunta "   sin cupo en $motor $(basename "$k") · iba por $(grep -ohE 'pág [0-9]+/[0-9]+' "$TRAB"/*.log 2>/dev/null | sort -t' ' -k2 -n | tail -1), cambio"
        mata "$pid"; break
      fi
    done
    wait "$pid" 2>/dev/null
    nuevo=$(ls -t "$TRAB"/*_bilingue.html 2>/dev/null | head -1)
    if [ -n "$nuevo" ] && [ "$nuevo" -nt "$MARCA" ]; then
      apunta "✅ listo: $nuevo"; exit 0
    fi
  done <<< "$CLAVES"
  ciclo=$((ciclo + 1))
  { [ "${ESPERAR:-1}" = "1" ] && [ "$ciclo" -lt "${MAX_CICLOS:-6}" ]; } || break
  apunta "⏸ ninguna clave con cupo (ciclo $ciclo); espero una hora y vuelvo a probarlas todas"
  sleep 3600
done
apunta "⏸ se acabaron las claves por hoy; vuelve a correrlo mañana y retoma donde quedó"
exit 1
