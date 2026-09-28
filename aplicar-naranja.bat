@echo off
REM Applies the "Naranja" (orange) OpenRGB profile to the GPU RGB (ASRock RX 6800 XT Phantom Gaming).
REM Applied twice: the i2c write goes out from OpenRGB's device thread, and the
REM first pass can be lost if the process exits before it is sent.
REM Do not run together with cli\asrock_gpu_rgb.py: both use the same i2c bus.

set "OPENRGB=C:\Program Files\OpenRGB-patched\OpenRGB.exe"

if not exist "%OPENRGB%" (
    echo ERROR: "%OPENRGB%" not found
    echo The patched build is the only one that detects this card. See README.md.
    pause
    exit /b 1
)

echo Applying profile Naranja...
"%OPENRGB%" --profile "Naranja"
timeout /t 3 /nobreak >nul
"%OPENRGB%" --profile "Naranja"
echo Done.
timeout /t 2 /nobreak >nul
