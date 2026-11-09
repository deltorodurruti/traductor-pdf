#!/bin/bash
cd "$(dirname "$0")"
echo "Pega tu clave de API y presiona Enter:"
read -r KEY
case "$KEY" in
  gsk_*)    F=.groq_key ;;
  csk-*)    F=.cerebras_key ;;
  sk-or*)   F=.openrouter_key ;;
  AIza*|AQ.*) F=.gemini_key ;;
  sk-*)     F=.openai_key ;;
  *)        F=.groq_key ;;
esac
printf '%s' "$KEY" > "$HOME/$F"
chmod 600 "$HOME/$F"
echo "Guardada en ~/$F  (se queda solo en tu computador)."
