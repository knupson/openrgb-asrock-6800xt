# Project: RGB on the graphics card (ASRock RX 6800 XT Phantom Gaming)

Working folder for everything related to the GPU's LED control and the custom
OpenRGB build. Full technical detail is in `README.md` — read it before
touching the i2c protocol or the patch.

## Essentials

- GPU: **ASRock Radeon RX 6800 XT Phantom Gaming 16GB OC**, `1002:73BF`,
  subsystem `1849:5202`, Navi 21.
- RGB controller: i2c **`0x36`** on the GPU's internal bus, **pure i2c** (not
  SMBus), reachable through `atiadlxx.dll` / `ADL2_Display_WriteAndReadI2C` with
  `iLine=1`. Does not need admin.
- **A single zone: channel 6.** Channels 3 and 7 ACK but light nothing.
- Color command: `0x10`. The `0x14` channel query **is not implemented** in
  this firmware (it returns rolling counters), so the channel layout is
  hardcoded.
- Status: working end to end. Patched OpenRGB in
  `C:\Program Files\OpenRGB-patched` (shortcuts point there), the GPU is
  **device 0**. The official OpenRGB is untouched in `C:\Program Files\OpenRGB`.
- Since 2026-09-27 production is **upstream master `5b2d5ce` + T4toh's rebased
  patch** (issue #1, `patches\0002-*.patch`), and the Effects Plugin on master
  (1.0+). Backups of the previous state in
  `E:\Repositorios\Personal\_datos\_backups\OpenRGB-patched-2026-09-27` and
  `...\openrgb-appdata-2026-09-27`.

## Project rules

- **Do not run the `cli\asrock_gpu_rgb.py` CLI and OpenRGB at the same time** —
  they fight over the same i2c bus.
- **Do not sweep unknown command bytes** against `0x36`. The known protocol is
  `0x10` (color) and `0x14` (query). Unknown commands on unknown firmware can
  touch flash/bootloader state.
- Read-only i2c scans are safe; writes to unidentified addresses are not.
- The patch **is not upstream**. Official OpenRGB releases do not detect this
  card: rebuild (`OpenRGB\scripts\build-windows.bat 6.8.3 2022 64`) and copy
  the output to `C:\Program Files\OpenRGB-patched`.
- `C:\Program Files` and `%APPDATA%` are outside the area the `write-guard`
  hook allows, and Program Files needs admin: the user runs the deploy with `!`.

## Toolchain

Sources and Qt live in `E:\Repositorios\Personal\_datos\openrgb-asrock-6800xt\`
(`E:\Claude\RGB` no longer exists):

- `OpenRGB\` — old branch `asrock-gpu-navi21-phantom-gaming` (base `790e148`).
- `OpenRGB-master\` — worktree, branch `asrock-6800xt-master`, production.
- `OpenRGBEffectsPlugin\` and worktree `OpenRGBEffectsPlugin-master\`.
- `Qt\6.8.3\msvc2022_64` + qt5compat, and `Qt\jom`. Upstream CI is still on
  Qt 6.8.3 + VS 2022, no need to change it.
- The build scripts default to `QT_ROOT=E:\Claude\RGB\Qt` (stale): set
  `QT_ROOT` before calling them.
- VS 2022 Build Tools (VCTools, MSVC 14.44) in
  `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools`. It vanished
  without a trace at some point before 2026-09-27 and was reinstalled via winget
  (`Microsoft.VisualStudio.2022.BuildTools`). If it is missing, search for
  `vcvarsall.bat` before assuming anything.

## Build gotchas on this machine

- In a one-line `cmd /c`, `set PATH=...;%PATH%` **after**
  `call vcvarsall.bat` does not work: `%PATH%` expands first and wipes what
  vcvarsall added. Extend `PATH` inside a `.bat` before the `call`.
- This shell has `NoDefaultCurrentDirectoryInExePath`, so `cmd` does not find a
  `.bat` by bare name in the cwd. Use `.\script.bat`.
- OpenRGB on Windows is a GUI-subsystem binary: its stdout is not captured when
  launched without a console. Read `%APPDATA%\OpenRGB\logs\` instead.
- OpenRGB CLI: passing a device name with spaces from PowerShell splits it into
  several argv entries and aborts option parsing. Use the index
  (`--device 0`).
- `--config <dir>` does not fully isolate: the 1.0+ build writes
  `%APPDATA%\OpenRGB\OpenRGB.json` (adds default keys) and a log there before
  switching directories. To test builds without touching production, back up
  `%APPDATA%\OpenRGB` first.
- To check whether OpenRGB is running use `tasklist /FI "IMAGENAME eq OpenRGB*"`;
  a `Get-Process OpenRGB` chained with other commands gave a false negative.
