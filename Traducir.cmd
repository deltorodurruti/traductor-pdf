@echo off
chcp 65001 >nul
title Traductor de Libros  --  NO CIERRES ESTA VENTANA
cd /d "%~dp0"

start "Ollama" /min ollama serve

start "" /min cmd /c "timeout /t 3 >nul & start "" http://localhost:8765"

echo ============================================================
echo   Traductor de Libros iniciando...
echo   Se abrira tu navegador en unos segundos.
echo   Para DETENERLO, cierra esta ventana.
echo ============================================================
python server.py

echo.
echo El traductor se ha detenido.
pause
