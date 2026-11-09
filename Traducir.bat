@echo off
title  Traductor PDF
chcp 65001 >nul
color 0B
cd /d "%~dp0"
set "PY=python"
where python >nul 2>&1 || set "PY=py"
%PY% main.py --edicion simple
echo.
echo   Puedes cerrar esta ventana.
pause >nul
