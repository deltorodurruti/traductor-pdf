@echo off
chcp 65001 >nul
title Instalar Traductor de Libros
cd /d "%~dp0"
echo ============================================================
echo   INSTALACION DEL TRADUCTOR DE LIBROS  (una sola vez)
echo ============================================================
echo.

echo [1/4] Comprobando Python...
where python >nul 2>nul
if errorlevel 1 (
  echo   [X] No encuentro Python. Voy a abrir la pagina de descarga.
  echo       Instala Python 3 y MARCA la casilla "Add python.exe to PATH".
  start "" https://www.python.org/downloads/
  echo   Cuando termines, vuelve a ejecutar este mismo archivo.
  pause
  exit /b 1
)
python --version
echo.

echo [2/4] Instalando librerias de Python...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo   [X] Hubo un error instalando las librerias.
  pause
  exit /b 1
)
echo   [OK] Librerias instaladas.
echo.

echo [3/4] Comprobando Ollama (motor de traduccion)...
where ollama >nul 2>nul
if errorlevel 1 (
  echo   [X] No encuentro Ollama. Voy a abrir la pagina de descarga.
  start "" https://ollama.com/download
  echo   Instala Ollama y vuelve a ejecutar este instalador.
  pause
  exit /b 1
)
echo   Descargando el modelo de traduccion (es grande, puede tardar)...
ollama pull qwen2.5:32b
echo   [OK] Modelo listo.
echo.

echo [4/5] OPCIONAL: OCR para libros ESCANEADOS
echo   Si vas a traducir PDF escaneados (solo imagen), instala Tesseract:
echo   https://github.com/UB-Mannheim/tesseract/wiki
echo   (elige el idioma English durante la instalacion)
echo.

echo [5/5] OPCIONAL: pronunciacion REAL (IPA + audio)
echo   Para oir como se pronuncian las términos que no se traducen, instala espeak-ng:
echo   https://github.com/espeak-ng/espeak-ng/releases
echo   (sin esto, se muestra una pronunciacion aproximada por escrito)
echo.

echo ============================================================
echo   LISTO.  Ahora haz doble clic en  "Traducir.cmd"
echo ============================================================
pause
