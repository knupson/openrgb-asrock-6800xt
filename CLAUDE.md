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
- Desde 2026-09-27 lo productivo es **upstream master `5b2d5ce` + el patch
  rebaseado de T4toh** (issue #1, `patches\0002-*.patch`), y el Effects Plugin
  en master (1.0+). Backups del estado anterior en
  `E:\Repositorios\Personal\_datos\_backups\OpenRGB-patched-2026-09-27` y
  `...\openrgb-appdata-2026-09-27`.

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
- `C:\Program Files` y `%APPDATA%` están fuera del área que permite el hook
  `write-guard`, y Program Files pide admin: el deploy lo corre el user con `!`.

## Toolchain

Fuentes y Qt viven en `E:\Repositorios\Personal\_datos\openrgb-asrock-6800xt\`
(`E:\Claude\RGB` ya no existe):

- `OpenRGB\` — branch vieja `asrock-gpu-navi21-phantom-gaming` (base `790e148`).
- `OpenRGB-master\` — worktree, branch `asrock-6800xt-master`, lo productivo.
- `OpenRGBEffectsPlugin\` y worktree `OpenRGBEffectsPlugin-master\`.
- `Qt\6.8.3\msvc2022_64` + qt5compat, y `Qt\jom`. Upstream CI sigue en Qt 6.8.3
  + VS 2022, no hace falta cambiarlo.
- Los scripts de build tienen default `QT_ROOT=E:\Claude\RGB\Qt` (viejo): setear
  `QT_ROOT` antes de llamarlos.
- VS 2022 Build Tools (VCTools, MSVC 14.44) en
  `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools`. Desapareció
  sin registro en algún momento antes del 2026-09-27 y se reinstaló por winget
  (`Microsoft.VisualStudio.2022.BuildTools`). Si falta, verificar con una
  búsqueda de `vcvarsall.bat` antes de asumir nada.

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
- `--config <dir>` no aísla del todo: el build 1.0+ escribe
  `%APPDATA%\OpenRGB\OpenRGB.json` (agrega claves default) y un log ahí antes
  de cambiar de directorio. Para probar builds sin tocar lo productivo, hacer
  backup de `%APPDATA%\OpenRGB` antes.
- Para chequear si OpenRGB corre usar `tasklist /FI "IMAGENAME eq OpenRGB*"`;
  un `Get-Process OpenRGB` encadenado con otros comandos dio falso negativo.
