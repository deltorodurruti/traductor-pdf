@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo   Preparando el traductor. No cierres esta ventana.
echo ============================================================
echo.

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY ( where py >nul 2>&1 && set "PY=py" )
if defined PY goto :haspy

echo No encuentro Python. Voy a intentar instalarlo...
where winget >nul 2>&1 || goto :manualpy
winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto :manualpy
echo.
echo   ==========================================================
echo    Python quedo instalado. IMPORTANTE:
echo    CIERRA esta ventana y vuelve a abrir install.bat.
echo   ==========================================================
pause
exit /b

:manualpy
echo.
echo ============================================================
echo   No se pudo instalar Python solo. Hazlo a mano (facil):
echo   1^) Entra a:  python.org/downloads
echo   2^) Clic en el boton amarillo  "Download Python".
echo   3^) Abre el archivo descargado (el instalador).
echo   4^) MUY IMPORTANTE: abajo MARCA la casilla
echo         "Add python.exe to PATH"
echo   5^) Clic en  "Install Now"  y espera a que termine.
echo   6^) Cierra, y vuelve a abrir install.bat.
echo ============================================================
pause
exit /b

:haspy

echo [1/4] Instalando componentes del programa...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt

echo [2/4] Instalando el lector de PDFs escaneados (Tesseract)...
where winget >nul 2>&1 && winget install -e --id UB-Mannheim.TesseractOCR --accept-source-agreements --accept-package-agreements

echo [3/4] Copiando el programa a una carpeta permanente...
set "DEST=%LOCALAPPDATA%\TraductorPDF"
if not exist "%DEST%" mkdir "%DEST%"
xcopy /E /I /Y "%~dp0*" "%DEST%\" >nul

if not exist "%DEST%\main.py" (
  echo.
  echo   ATENCION: no se pudo copiar el programa.
  echo   Seguramente abriste el zip por dentro sin extraerlo.
  echo   1^) Cierra esto.  2^) Clic derecho al zip - Extraer todo.
  echo   3^) Entra a la carpeta y abre install.bat desde ahi.
  echo.
  pause
  exit /b
)

echo [4/4] Creando el acceso "Traductor PDF" en tu Escritorio...
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
> "%DESKTOP%\Traductor PDF.bat" echo @echo off
>>"%DESKTOP%\Traductor PDF.bat" echo cd /d "%DEST%"
>>"%DESKTOP%\Traductor PDF.bat" echo call "%DEST%\Traducir.bat"

echo.
echo ============================================================
echo   Listo!  En el Escritorio tienes "Traductor PDF".
echo   Haz doble clic ahi para traducir. Funciona siempre,
echo   aunque borres o muevas la carpeta de descargas.
echo ============================================================
pause
