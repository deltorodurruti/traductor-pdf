#!/bin/bash
cd "$(dirname "$0")"
echo "==============================================="
echo "  Preparando el traductor (macOS)"
echo "==============================================="

if ! command -v brew >/dev/null 2>&1; then
  echo "Falta Homebrew. Instalalo con una linea desde https://brew.sh"
  echo "y vuelve a ejecutar este instalador."
  exit 1
fi

echo "[1/2] Instalando Python y Tesseract con Homebrew..."
brew bundle --file="$(dirname "$0")/Brewfile"

echo "[2/2] Instalando los componentes del programa..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo
echo "Listo. Abre 'Traducir.command' (simple) o 'Avanzado.command' (completo)."
