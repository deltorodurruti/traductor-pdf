#!/usr/bin/env bash
set -uo pipefail

LOG="/tmp/remaqueta.log"
COLOR_OK='\033[32m'; COLOR_ERR='\033[31m'; COLOR_WRN='\033[33m'; COLOR_RST='\033[0m'

[ -f "$LOG" ] || { echo "$(date '+%H:%M:%S') inicio" > "$LOG"; }

echo ""
echo "╭────────────────────────────────────────────────╮"
echo "│  REMAQUETACIÓN DE LIBROS                       │"
echo "╰────────────────────────────────────────────────╯"
echo ""

ACTIVE=$(pgrep -f "entregar_libro.py --corrido --forzar" 2>/dev/null | wc -l)
if [ "$ACTIVE" -gt 0 ]; then
  LIB=$(pgrep -af "entregar_libro.py --corrido --forzar" | sed -n 's/.*--forzar //p' | head -1)
  [ -z "$LIB" ] && LIB="(procesando...)"
  echo -e "🔄 ${COLOR_WRN}EN PROCESO${COLOR_RST}: $LIB"
else
  echo -e "✓ ${COLOR_OK}SIN PROCESOS ACTIVOS${COLOR_RST}"
fi

echo ""

OKED=$(grep -c '✅ entregado' "$LOG" 2>/dev/null) || OKED=0
ERRORED=$(grep -c '✗' "$LOG" 2>/dev/null) || ERRORED=0
TOTAL=$((OKED + ERRORED))

echo "Resultados:"
echo -e "  ✅ ${COLOR_OK}Entregados: $OKED${COLOR_RST}"
echo -e "  ✗ ${COLOR_ERR}Errores: $ERRORED${COLOR_RST} (no en entregas.tsv — ignorar)"
echo -e "  → ${COLOR_WRN}Total procesados: $TOTAL / 24${COLOR_RST}"
echo ""

echo "Últimas acciones:"
tail -5 "$LOG" | sed 's/^/  /'

echo ""
echo "────────────────────────────────────────────────"
echo "Log completo: tail -f $LOG"
echo ""
