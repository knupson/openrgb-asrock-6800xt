@echo off
REM Aplica el perfil "Naranja" al RGB de la GPU (ASRock RX 6800 XT Phantom Gaming).
REM Se aplica dos veces: el write i2c sale desde el device thread de OpenRGB y la
REM primera pasada puede perderse si el proceso se cierra antes de que salga.
REM No ejecutar junto con cli\asrock_gpu_rgb.py: pelean por el mismo bus i2c.

set "OPENRGB=C:\Program Files\OpenRGB-patched\OpenRGB.exe"

if not exist "%OPENRGB%" (
    echo ERROR: no se encuentra "%OPENRGB%"
    echo El build patcheado es el unico que detecta esta placa. Ver README.md.
    pause
    exit /b 1
)

echo Aplicando perfil Naranja...
"%OPENRGB%" --profile "Naranja"
timeout /t 3 /nobreak >nul
"%OPENRGB%" --profile "Naranja"
echo Listo.
timeout /t 2 /nobreak >nul
