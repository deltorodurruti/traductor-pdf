@echo off
title  Guardar clave de API
chcp 65001 >nul
color 0B
echo Pega tu clave de API y presiona Enter.
set /p KEY=Clave: 
set "F=.groq_key"
echo %KEY%| findstr /b "gsk_"  >nul && set "F=.groq_key"
echo %KEY%| findstr /b "csk-"  >nul && set "F=.cerebras_key"
echo %KEY%| findstr /b "sk-or" >nul && set "F=.openrouter_key"
echo %KEY%| findstr /b "AIza"  >nul && set "F=.gemini_key"
echo %KEY%| findstr /b "AQ."   >nul && set "F=.gemini_key"
> "%USERPROFILE%\%F%" echo|set /p="%KEY%"
echo.
echo Guardada en %USERPROFILE%\%F%  (solo en tu PC).
pause
