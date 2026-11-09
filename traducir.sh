#!/bin/bash
set -e
cd "$(dirname "$0")"

PDF="$1"
MODO="${2:-especializado}"
CALIDAD="${3:-1}"
MOTOR="${4:-web}"

[ -z "$PDF" ] && { echo "Uso: ./traducir.sh <archivo.pdf> [modo] [calidad 1-5]"; exit 1; }
[ -f "$PDF" ] || { echo "✗ No existe: $PDF"; exit 1; }

BASE="${PDF%.pdf}"
OUT="${BASE}.bilingue.html"
LOG="${BASE}.log"

echo "» Traduciendo:  $PDF"
echo "  modo=$MODO  calidad=$CALIDAD  motor=$MOTOR  salida=$OUT"
echo "  (en segundo plano; avance:  tail -f \"$LOG\")"

MODELO=""; [ "$MOTOR" = "ollama" ] && MODELO="--model qwen2.5:7b"
nohup python3 -u main.py "$PDF" --yes --engine "$MOTOR" $MODELO \
  --book-type "$MODO" --calidad "$CALIDAD" --ocr auto  \
  --out "$OUT" > "$LOG" 2>&1 &

echo "  ✓ lanzado (PID $!)"
