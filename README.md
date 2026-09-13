# ASRock GPU RGB — ASRock Radeon RX 6800 XT Phantom Gaming 16GB OC

Reverse-engineering notes and a working CLI for the RGB controller on this card,
plus the OpenRGB patch that adds native support.

## Layout

```
E:\Claude\RGB\
  README.md                    this file
  CLAUDE.md                    context for Claude Code sessions started here
  cli\asrock_gpu_rgb.py        standalone LED control over AMD ADL I2C
  OpenRGB\                     patched OpenRGB fork, branch
                               asrock-gpu-navi21-phantom-gaming
  OpenRGBEffectsPlugin\        effects plugin source + build-plugin.bat
  patches\                     the detector patch as a standalone .patch
  research\                    probe scripts used to reverse the protocol,
                               ADL backend reference, MR !3402 diff,
                               transcript renderer
  transcript\                  the session that produced all of this
                               (.jsonl raw + conversation.md readable)
```

The built binary is installed separately at `C:\Program Files\OpenRGB-patched`
(see Build and install below).

## Hardware

| | |
|---|---|
| Card | ASRock Radeon RX 6800 XT Phantom Gaming 16GB OC (`RX6800XT PG 16GO`) |
| PCI | `1002:73BF` (Navi 21), subsystem `1849:5202` |
| VBIOS | `113-EXT48025-001` |
| RGB controller | I2C address `0x36`, GPU-internal bus, **pure I2C** (not SMBus) |
| Zones | one — channel `6` drives every visible LED |

## Access path on Windows

AMD's driver does not expose the GPU's internal I2C buses as normal I2C
adapters. They are reachable through ADL:

```
atiadlxx.dll
  ADL2_Main_Control_Create(malloc_cb, 1, &ctx)
  ADL2_Adapter_AdapterInfoX4_Get(ctx, -1, &num, &info)   # iAdapterIndex, strPNPString
  ADL2_Display_WriteAndReadI2C(ctx, iAdapterIndex, &ADLI2C)
```

`ADLI2C` fields that matter:

| field | value |
|---|---|
| `iLine` | `1` — the only line that answers; 0 returns `-3`, 2..7 return `-1` |
| `iAddress` | `addr << 1` → `0x6C` for the RGB controller |
| `iOffset` | `0` for pure I2C |
| `iAction` | `1` read, `2` write |
| `iSpeed` | `100` |

This mirrors OpenRGB's `i2c_smbus/Windows/i2c_smbus_amdadl.cpp`. No admin
rights needed.

## Bus survey

Read-only scan of `0x08..0x77` on `iLine=1`: **only `0x36` responds**
(`rc=0`); all other 111 addresses NAK with `rc=-1`. So the RGB controller is
unambiguously at `0x36` and a short read is a reliable presence probe.

## Protocol

12-byte packets, `[cmd, 0x00, subcmd, payload…]`, from OpenRGB MR
[!3402](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3402)
(itself ported from SignalRGB's `ASRock GPU.js`).

### Set colour — confirmed working

```
cmd    = 0x10
subcmd = channel index
payload= [0x01, R, G, B, brightness, speed, direction, 0x1A]
         0x01 = static/direct mode
```

### Channel query — NOT implemented on this firmware

```
cmd 0x14, subcmd 0x01  -> documented: channel bitmap in response bytes 4-5
cmd 0x14, subcmd 0x02  -> documented: LED counts at response byte 4+channel
```

On this card the reply is not channel data. Bytes 0 and 2 of the response are
rolling counters that increment once per I2C transaction:

```
idle reads:  02 00 06 …   02 00 07 …   02 00 08 …   02 00 09 …
```

so the bitmap reads back as `0x0000`. The channel layout has to be hardcoded
per card instead. Determined empirically by driving channels 3 / 6 / 7 with
red / green / blue simultaneously and looking at the card: everything lit
green ⇒ channel 6 owns all the LEDs, channels 3 and 7 ACK but light nothing.
The channel byte is honoured (the last write of each refresh cycle was
channel 15 = black and the LEDs stayed green).

Unknown command bytes were deliberately not swept — unknown commands on
unknown firmware can touch flash/bootloader state.

## CLI

```
python asrock_gpu_rgb.py info            # adapter, PCI IDs, controller status
python asrock_gpu_rgb.py set 00FF00      # static colour
python asrock_gpu_rgb.py set FF8000 --brightness 128
python asrock_gpu_rgb.py off
python asrock_gpu_rgb.py breathe 00A0FF --seconds 60
python asrock_gpu_rgb.py rainbow --seconds 60
python asrock_gpu_rgb.py spin                      # colour rotation, runs forever
python asrock_gpu_rgb.py scan            # read-only bus scan
python asrock_gpu_rgb.py --channel 3 set FF0000    # try another channel
```

Static colours persist with no process running. `breathe` / `rainbow` / `spin`
are software-driven and only animate while the command runs. Do not run this at
the same time as OpenRGB or another tool that drives the same bus.

### `spin`

The rotating effect. There is only one zone, so nothing can rotate *across* the
card — the rotation is in time: the whole card walks the colour wheel at a
constant rate. Runs at 20 Hz, pacing each frame against a monotonic clock so
the lap time does not drift with however long the I2C write took.

| flag | meaning |
|---|---|
| `--speed SECONDS` | seconds per full lap (default `12`) |
| `--reverse` | rotate the other way round |
| `--palette RRGGBB,RRGGBB,…` | crossfade between fixed colours instead of the continuous rainbow; wraps from the last back to the first |
| `--saturation 0..1` | rainbow saturation, lower is pastel (default `1.0`); ignored with `--palette` |
| `--brightness 0..255` | applied by scaling RGB in software, so it works whether or not the firmware honours the brightness byte |
| `--seconds N` | stop after N seconds (default: run until ctrl-c) |

```
python asrock_gpu_rgb.py spin --speed 4 --reverse
python asrock_gpu_rgb.py spin --saturation 0.45 --brightness 160
python asrock_gpu_rgb.py spin --palette FF0000,00FF00,0000FF --speed 6
```

## Whole-machine rotation — `cli\spin_all.py`

`asrock_gpu_rgb.py` only reaches the graphics card. Case fans, keyboard and
motherboard zones live on other controllers, which OpenRGB already drives, so
`spin_all.py` runs the same rotation through OpenRGB's SDK instead of touching
any bus itself. Only OpenRGB writes to hardware, so there is no bus contention
with it — this is the one script here that is *meant* to run alongside OpenRGB.

```
"C:\Program Files\OpenRGB-patched\OpenRGB.exe" --server --startminimized
python spin_all.py --list
python spin_all.py --speed 8
python spin_all.py --speed 6 --spread 1 --only B760M,ASRock
python spin_all.py --off
```

Same effect flags as `spin`, plus:

| flag | meaning |
|---|---|
| `--list` | print the devices, zones and modes OpenRGB sees, then exit |
| `--only NAME[,NAME…]` | only drive devices whose name contains one of these |
| `--spread 0..1` | `0` (default) paints every LED the same colour, so the whole machine rotates in phase; `1` wraps a full rainbow around each addressable chain, so on a strip the colours physically travel |
| `--comet [TAIL]` | rotate a bright arc over a dark strip. Looks sharp on a bare strip, but see below — on these fans it reads as blinking |
| `--floor 0..1` | minimum brightness in `--comet` mode (default `0.3`) |
| `--fps N` | frame rate (default `20`). **The setting that matters most here** |
| `--off` | blank every selected device and exit |

### What actually works on this machine

Settled by trial on the real hardware, after a lot of things that looked right
in the data and wrong on the case:

```
python spin_all.py --only ASRock,B760M --spread 1 --speed 1.5 --fps 15
```

Four findings, each of which individually broke the effect:

* **The motherboard's SMBus controller cannot take 20 fps.** Frames get eaten
  and all that survives is the overall brightness moving, which reads as a
  pulse rather than as rotation. ~15 fps is fine, and a single-LED chase step
  at 1.7 fps is definitely fine. This alone made a correct travelling rainbow
  look static.
* **Rotate per zone, not across the device.** The B760M's 26 LEDs are
  `D_LED(24)` + `LED_C1(1)` + `PCI-E Accent(1)`. Sweeping a comet across all 26
  sends the head into the last two, which are nowhere near the fans, so the
  fans go black for two steps every lap. `strips()` in `spin_all.py` splits the
  rotation per zone for this reason.
* **`--comet` is the wrong effect for these fans.** A comet is mostly darkness
  by construction, and the fans hang off a hub that mirrors the chain, so each
  fan spends most of the lap unlit — it blinks. `--spread 1` holds every LED at
  full brightness and rotates the hue instead, which is the effect that reads
  as spinning and never goes dark.
* **The EVision keyboard misbehaves under this update rate**, so it is left out
  with `--only`.

The GPU is one LED and can only ever ride the phase as a flat colour change.

### What this machine has

| id | device | LEDs | zones |
|---|---|---|---|
| 0 | ASRock Radeon RX 6800 XT Phantom Gaming | 1 | `Top Side` |
| 1 | EVision Keyboard 0C45:5204 | 126 | `Keyboard` |
| 2 | B760M D3HP | 26 | `D_LED(24)`, `LED_C1(1)`, `PCI-E Accent(1)` |

The case fans hang off the motherboard's `D_LED` header as 24 addressable LEDs,
so `--spread 1` gives a genuine travelling rainbow there. The GPU is a single
LED and can only ever change colour as one block.

### SDK notes

The client in `spin_all.py` is hand-written against protocol version 6. Two
things worth knowing before touching it:

* **`openrgb-python` (0.3.6) does not work with this server.** It only
  implements up to protocol 4 and dies parsing protocol 6 device blocks with
  `ValueError: 256 is not a valid ZoneType`.
* **`Documentation/OpenRGBSDK.md` is out of date for protocol 6.** It omits two
  `display_name` strings that `RGBController.cpp` really does serialise: one at
  the end of each Zone Data block (after the zone modes), and one in Device
  Data between `flags` and `configuration`. Trust
  `RGBController::GetDeviceDescriptionData` over the markdown.
* **The server pushes unsolicited packets** — an ack (`10`) after every
  request, its own name (`51`) after protocol negotiation, and
  device-list-changed (`100`). A client that treats the next packet as its
  reply desyncs immediately, then reads a garbage length and tries to buffer
  it; that is worth a hard cap on payload size, not just a retry
  (`MAX_PAYLOAD`).
* **An effect loop must drain those acks or it deadlocks.** Nothing in the
  effect path wants a reply, so it is tempting to never read the socket. Do
  that and the acks fill the receive buffer, the server blocks writing to us,
  it stops reading our requests, our send buffer fills, and `sendall()` blocks
  forever. The symptom is nasty: the animation runs fine for a minute or two,
  then freezes with no error, no exit, and zero CPU. At 20 fps over three
  devices that is 60 acks a second against a ~64 kB buffer, so it takes about a
  minute to hit. `OpenRGBSDK.drain()` is called once per frame for this.

## OpenRGB patch

Branch `asrock-gpu-navi21-phantom-gaming` in `C:\Users\KnuPwns\src\OpenRGB`,
exported as
`C:\Users\KnuPwns\src\0001-Add-ASRock-RX-6800-XT-Phantom-Gaming-GPU-RGB-support.patch`.

Upstream already has the ASRock GPU controller (merged 2026-07-31, for the
RX 9070 XT Steel Legend), but it does not work here for two reasons:

1. **Wrong PCI IDs.** The detector is registered for
   `1002:7550 / 1849:5403` only. Added a registration for
   `1002:73BF / 1849:5202`.

2. **The Windows probe can never succeed.** The detector gates on
   `i2c_smbus_write_quick()`, and `i2c_smbus_amdadl::i2c_smbus_xfer()`
   returns `-1` unconditionally for `I2C_SMBUS_QUICK`. That makes the ASRock
   GPU detector unreachable on Windows for *any* card, including the 9070 XT
   it was written for. Replaced with a short pure-I2C read.

Plus a fallback channel layout, keyed on PCI subsystem device, used when the
`0x14` query returns nothing.

## Build and install

Toolchain (already installed on this machine):

* VS 2022 Build Tools with the VCTools workload —
  `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools`
* Qt 6.8.3 msvc2022_64 in `E:\Claude\RGB\Qt` (via `pip install aqtinstall`,
  `aqt install-qt windows desktop 6.8.3 win64_msvc2022_64 -m qt5compat -O E:\Claude\RGB\Qt`).
  El install es relocatable (aqtinstall deja un `qt.conf`), así que se movió desde
  `C:\Qt` sin reinstalar.
* jom in `E:\Claude\RGB\Qt\jom`

Los scripts de build toman la raíz de Qt de la variable `QT_ROOT`, con default
`E:\Claude\RGB\Qt`. Para apuntar a otro install, exportarla antes de invocarlos.

Rebuild:

```
cd E:\Claude\RGB\OpenRGB
scripts\build-windows.bat 6.8.3 2022 64
```

Output lands in `OpenRGB Windows 64-bit\`. The script ends with
`move release "OpenRGB Windows 64-bit"`, so if that folder already exists from
a previous build the new output is nested inside it as `…\release\` instead of
replacing it — delete the old output folder before rebuilding, or flatten the
nested one afterwards.

The running install is a copy of it
at `C:\Program Files\OpenRGB-patched`, and the desktop and Start Menu
shortcuts point there. The stock OpenRGB 1.0rc3 install is untouched in
`C:\Program Files\OpenRGB` as a fallback.

After pulling upstream changes, rebase the branch and rebuild — the patch is
not upstream, so official releases will not detect this card.

Verify detection and drive the card without the GUI:

```
cd "C:\Program Files\OpenRGB-patched"
OpenRGB.exe --loglevel 4 --noautoconnect --device 0 --mode Direct --color 00C8FF
```

### Effects plugin

The card's firmware has no effect modes — the controller exposes only `Direct`,
so animated effects have to be driven in software. The OpenRGB Effects Plugin
is built and installed for that:

* source + build script: `E:\Claude\RGB\OpenRGBEffectsPlugin\build-plugin.bat`
* installed to `%APPDATA%\OpenRGB\plugins\OpenRGBEffectsPlugin.dll`
* loads clean against this build (`58 effects registered`); its submodule pins
  OpenRGB at plugin API version 5, which matches

Two gotchas hit while building it:

* `cmd /c "call vcvarsall.bat … && set PATH=…;%PATH% && qmake"` fails with
  `Cannot run compiler 'cl'` — `%PATH%` expands before vcvarsall runs and wipes
  what it added. Extend `PATH` inside a `.bat` *before* the `call`.
* This shell has `NoDefaultCurrentDirectoryInExePath` set, so `cmd` will not
  find a bare `build-plugin.bat` in the current directory. Use `.\`.

Effects start from the GUI (Effects tab → add effect → tick the `Top Side`
zone → Start), or from an OpenRGB profile whose
`plugins["OpenRGB Effects Plugin"]` section marks the effect `AutoStart`.
There is no plain settings file that auto-starts one at launch.

The zone is a single LED, so spatial effects (wave, spiral, zigzag) render as
a flat colour change; rainbow, breathing and audio-reactive ones look right.

For an effect without OpenRGB at all, the CLI here has `rainbow` and `breathe`.

### Notes

The GPU registers as device 0. Note that OpenRGB on Windows is a GUI-subsystem
binary, so its stdout is not capturable when launched without a console —
check `%APPDATA%\OpenRGB\logs\` instead. Passing a multi-word device name from
PowerShell splits into separate argv entries and aborts option parsing; use
the device index.
