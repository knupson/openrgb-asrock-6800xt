# Proyecto: RGB de la placa de video (ASRock RX 6800 XT Phantom Gaming)

Carpeta de trabajo para todo lo relacionado al control de LEDs de la GPU y al
build propio de OpenRGB. Detalle técnico completo en `README.md` — leerlo antes
de tocar el protocolo i2c o el patch.

## Lo esencial

- GPU: **ASRock Radeon RX 6800 XT Phantom Gaming 16GB OC**, `1002:73BF`,
  subsystem `1849:5202`, Navi 21.
- Controlador RGB: i2c **`0x36`** en el bus interno de la GPU, **pure i2c** (no
  SMBus), accesible por `atiadlxx.dll` / `ADL2_Display_WriteAndReadI2C` con
  `iLine=1`. No requiere admin.
- **Una sola zona: canal 6.** Los canales 3 y 7 ACKean pero no prenden nada.
- Comando de color: `0x10`. El query de canales `0x14` **no está implementado**
  en este firmware (devuelve contadores rodantes), por eso el layout de canales
  va hardcodeado.
- Estado: funcionando end-to-end. OpenRGB patcheado en
  `C:\Program Files\OpenRGB-patched` (accesos directos apuntan ahí), la GPU es
  **device 0**. El OpenRGB oficial quedó intacto en `C:\Program Files\OpenRGB`.

## Reglas de este proyecto

- **No correr el CLI de `cli\asrock_gpu_rgb.py` y OpenRGB a la vez** — pelean
  por el mismo bus i2c.
- **No barrer command bytes desconocidos** contra `0x36`. El protocolo conocido
  es `0x10` (color) y `0x14` (query). Comandos desconocidos en firmware
  desconocido pueden tocar estado de flash/bootloader.
- Los scans i2c de sólo lectura son seguros; las escrituras a addresses no
  identificados no.
- El patch **no está upstream**. Los releases oficiales de OpenRGB no detectan
  esta placa: hay que rebuildear (`OpenRGB\scripts\build-windows.bat 6.8.3 2022 64`)
  y copiar el output a `C:\Program Files\OpenRGB-patched`.

## Toolchain instalado (no reinstalar)

- VS 2022 Build Tools (workload VCTools) en
  `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools`
- Qt 6.8.3 msvc2022_64 + módulo qt5compat en `E:\Claude\RGB\Qt`
- jom en `E:\Claude\RGB\Qt\jom`
- Los scripts de build resuelven Qt vía `QT_ROOT` (default `E:\Claude\RGB\Qt`).
  `C:\Qt` ya no existe: el install se movió tal cual, es relocatable por `qt.conf`.

## Gotchas de build en esta máquina

- En un `cmd /c` de una línea, `set PATH=...;%PATH%` **después** de
  `call vcvarsall.bat` no sirve: `%PATH%` se expande antes y borra lo que
  agregó vcvarsall. Extender `PATH` dentro de un `.bat` antes del `call`.
- Esta shell tiene `NoDefaultCurrentDirectoryInExePath`, así que `cmd` no
  encuentra un `.bat` por nombre pelado en el cwd. Usar `.\script.bat`.
- OpenRGB en Windows es binario GUI-subsystem: su stdout no se captura si se
  lanza sin consola. Mirar `%APPDATA%\OpenRGB\logs\` en vez de stdout.
- La CLI de OpenRGB: pasar un nombre de device con espacios desde PowerShell lo
  parte en varios argv y aborta el parseo de opciones. Usar el índice
  (`--device 0`).
