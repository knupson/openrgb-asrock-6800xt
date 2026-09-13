"""
asrock_gpu_rgb - control the RGB LEDs of an ASRock Radeon GPU on Windows.

Verified on: ASRock Radeon RX 6800 XT Phantom Gaming 16GB OC
             PCI 1002:73BF, subsystem 1849:5202

How it works
------------
The RGB controller sits on the GPU's own I2C bus at address 0x36 (pure I2C,
not SMBus). Windows exposes that bus through AMD's ADL library
(atiadlxx.dll, ADL2_Display_WriteAndReadI2C, iLine = 1), the same path
OpenRGB uses in i2c_smbus/Windows/i2c_smbus_amdadl.cpp.

Packet format (from OpenRGB MR !3402, itself ported from SignalRGB's
"ASRock GPU.js"), 12 bytes:

    [cmd, 0x00, subcmd, payload...]

    cmd 0x10, subcmd = channel index:
        [0x01, R, G, B, brightness, speed, direction, 0x1A]
        0x01 in the first payload byte selects static/direct mode.

    cmd 0x14 is the channel-info query. This card's firmware does not
    implement it (it answers with a rolling transaction counter), so the
    channel layout is hardcoded below from hardware testing: only channel 6
    drives LEDs. Channels 3 and 7 are ACKed but light nothing.

Usage
-----
    python asrock_gpu_rgb.py info
    python asrock_gpu_rgb.py set 00FF00
    python asrock_gpu_rgb.py set FF8000 --brightness 128
    python asrock_gpu_rgb.py off
    python asrock_gpu_rgb.py breathe 00A0FF --seconds 60
    python asrock_gpu_rgb.py rainbow --seconds 60
    python asrock_gpu_rgb.py spin                      # hue rotation, runs forever
    python asrock_gpu_rgb.py spin --speed 4 --reverse
    python asrock_gpu_rgb.py spin --palette FF0000,00FF00,0000FF
    python asrock_gpu_rgb.py scan          # read-only I2C scan of the GPU bus

Notes
-----
* No admin rights are required; ADL I2C works as a normal user.
* Static colors persist without a running process. The effect modes are
  software-driven, so they only animate while the command runs.
* Do not run this at the same time as OpenRGB or another RGB tool that
  touches the same bus.
"""

import argparse
import colorsys
import ctypes
import sys
import time
from ctypes import (
    POINTER, Structure, byref, c_char, c_int, c_void_p, create_string_buffer,
    windll, WINFUNCTYPE,
)

ADL_OK = 0
ADL_MAX_PATH = 256
ADL_DL_I2C_ACTIONREAD = 1
ADL_DL_I2C_ACTIONWRITE = 2

AMD_VEN = 0x1002
ASROCK_SUB_VEN = 0x1849

RGB_ADDRESS = 0x36
RGB_I2C_LINE = 1
PACKET_LEN = 12
CMD_COLOR = 0x10
MODE_STATIC = 0x01
MAGIC = 0x1A

# Refresh rate for the software-driven effects.
SPIN_FPS = 20.0

# Channel 6 ("Top Side" in OpenRGB/SignalRGB naming) drives every visible LED
# on the RX 6800 XT Phantom Gaming. Override with --channel if your card
# differs.
DEFAULT_CHANNEL = 6
CHANNEL_NAMES = {3: "ARGB Header", 6: "Top Side", 7: "Fan"}


class AdapterInfoX2(Structure):
    _fields_ = [
        ("iSize", c_int),
        ("iAdapterIndex", c_int),
        ("strUDID", c_char * ADL_MAX_PATH),
        ("iBusNumber", c_int),
        ("iDeviceNumber", c_int),
        ("iFunctionNumber", c_int),
        ("iVendorID", c_int),
        ("strAdapterName", c_char * ADL_MAX_PATH),
        ("strDisplayName", c_char * ADL_MAX_PATH),
        ("iPresent", c_int),
        ("iExist", c_int),
        ("strDriverPath", c_char * ADL_MAX_PATH),
        ("strDriverPathExt", c_char * ADL_MAX_PATH),
        ("strPNPString", c_char * ADL_MAX_PATH),
        ("iOSDisplayIndex", c_int),
        ("iInfoMask", c_int),
        ("iInfoValue", c_int),
    ]


class ADLI2C(Structure):
    _fields_ = [
        ("iSize", c_int),
        ("iLine", c_int),
        ("iAddress", c_int),
        ("iOffset", c_int),
        ("iAction", c_int),
        ("iSpeed", c_int),
        ("iDataSize", c_int),
        ("pcData", POINTER(c_char)),
    ]


MALLOC_CB = WINFUNCTYPE(c_void_p, c_int)
_keepalive = []


@MALLOC_CB
def _adl_malloc(size):
    buf = create_string_buffer(size)
    _keepalive.append(buf)
    return ctypes.cast(buf, c_void_p).value


def _parse_pnp(pnp):
    ids = {}
    for key, tag in (("ven", "VEN_"), ("dev", "DEV_")):
        i = pnp.find(tag)
        ids[key] = int(pnp[i + 4:i + 8], 16) if i >= 0 else None
    i = pnp.find("SUBSYS_")
    ids["subdev"] = int(pnp[i + 7:i + 11], 16) if i >= 0 else None
    ids["subven"] = int(pnp[i + 11:i + 15], 16) if i >= 0 else None
    return ids


class AsrockGpu:
    def __init__(self, channel=DEFAULT_CHANNEL):
        self.channel = channel
        self.dll = windll.LoadLibrary("atiadlxx.dll")
        self.ctx = c_void_p()

        self.dll.ADL2_Main_Control_Create.argtypes = [MALLOC_CB, c_int, POINTER(c_void_p)]
        self.dll.ADL2_Main_Control_Create.restype = c_int
        self.dll.ADL2_Adapter_AdapterInfoX4_Get.argtypes = [
            c_void_p, c_int, POINTER(c_int), POINTER(POINTER(AdapterInfoX2))
        ]
        self.dll.ADL2_Adapter_AdapterInfoX4_Get.restype = c_int
        self.dll.ADL2_Display_WriteAndReadI2C.argtypes = [c_void_p, c_int, POINTER(ADLI2C)]
        self.dll.ADL2_Display_WriteAndReadI2C.restype = c_int

        rc = self.dll.ADL2_Main_Control_Create(_adl_malloc, 1, byref(self.ctx))
        if rc != ADL_OK:
            raise RuntimeError(f"ADL2_Main_Control_Create failed: {rc}")

        self.adapter_index, self.ids, self.adapter_name = self._find_gpu()

    def _adapters(self):
        num = c_int(0)
        arr = POINTER(AdapterInfoX2)()
        rc = self.dll.ADL2_Adapter_AdapterInfoX4_Get(self.ctx, -1, byref(num), byref(arr))
        if rc != ADL_OK:
            raise RuntimeError(f"ADL2_Adapter_AdapterInfoX4_Get failed: {rc}")
        seen = set()
        out = []
        for i in range(num.value):
            a = arr[i]
            if a.iBusNumber in seen:
                continue
            seen.add(a.iBusNumber)
            out.append(a)
        return out

    def _find_gpu(self):
        for a in self._adapters():
            ids = _parse_pnp(a.strPNPString.decode("ascii", "ignore"))
            if ids.get("ven") == AMD_VEN and ids.get("subven") == ASROCK_SUB_VEN:
                return a.iAdapterIndex, ids, a.strAdapterName.decode("ascii", "ignore")
        raise RuntimeError("no ASRock AMD GPU found on ADL (subsystem vendor 1849)")

    def _xfer(self, action, buf, size, addr=RGB_ADDRESS):
        pkt = ADLI2C()
        pkt.iSize = ctypes.sizeof(ADLI2C)
        pkt.iLine = RGB_I2C_LINE
        pkt.iAddress = addr << 1
        pkt.iOffset = 0
        pkt.iAction = action
        pkt.iSpeed = 100
        pkt.iDataSize = size
        pkt.pcData = ctypes.cast(buf, POINTER(c_char))
        return self.dll.ADL2_Display_WriteAndReadI2C(self.ctx, self.adapter_index, byref(pkt))

    def read(self, length, addr=RGB_ADDRESS):
        buf = create_string_buffer(length)
        rc = self._xfer(ADL_DL_I2C_ACTIONREAD, buf, length, addr)
        return rc, bytes(buf.raw)

    def write(self, payload, addr=RGB_ADDRESS):
        buf = create_string_buffer(bytes(payload), len(payload))
        return self._xfer(ADL_DL_I2C_ACTIONWRITE, buf, len(payload), addr)

    def set_color(self, r, g, b, brightness=0xFF, channel=None, speed=0xFF, direction=0x00):
        packet = bytearray(PACKET_LEN)
        packet[0] = CMD_COLOR
        packet[1] = 0x00
        packet[2] = self.channel if channel is None else channel
        packet[3:11] = bytes([MODE_STATIC, r, g, b, brightness, speed, direction, MAGIC])
        rc = self.write(packet)
        if rc != ADL_OK:
            raise RuntimeError(f"color write failed: ADL rc={rc}")


def parse_rgb(s):
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError("color must be RRGGBB hex")
    v = int(s, 16)
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF


def parse_palette(s):
    colors = [parse_rgb(part) for part in s.split(",") if part.strip()]
    if len(colors) < 2:
        raise argparse.ArgumentTypeError("palette needs at least two RRGGBB colors")
    return colors


def cmd_info(gpu, args):
    print(f"adapter        : {gpu.adapter_name} (ADL index {gpu.adapter_index})")
    print(f"pci            : {gpu.ids['ven']:04X}:{gpu.ids['dev']:04X} "
          f"subsystem {gpu.ids['subven']:04X}:{gpu.ids['subdev']:04X}")
    print(f"rgb controller : I2C 0x{RGB_ADDRESS:02X}, iLine {RGB_I2C_LINE}")
    rc, data = gpu.read(4)
    status = "responding" if rc == ADL_OK else f"no response (rc={rc})"
    print(f"status         : {status}  raw={' '.join(f'{x:02X}' for x in data)}")
    print(f"channel in use : {gpu.channel} ({CHANNEL_NAMES.get(gpu.channel, 'unknown')})")


def cmd_set(gpu, args):
    r, g, b = args.color
    gpu.set_color(r, g, b, brightness=args.brightness)
    print(f"channel {gpu.channel} -> #{r:02X}{g:02X}{b:02X} brightness {args.brightness}")


def cmd_off(gpu, args):
    gpu.set_color(0, 0, 0, brightness=0)
    print(f"channel {gpu.channel} -> off")


def cmd_breathe(gpu, args):
    r, g, b = args.color
    end = time.time() + args.seconds
    print(f"breathing #{r:02X}{g:02X}{b:02X} for {args.seconds}s (ctrl-c to stop)")
    t = 0.0
    while time.time() < end:
        # 0 -> 1 -> 0 over 4 seconds
        phase = (1 - abs(((t % 4.0) / 2.0) - 1))
        scale = 0.05 + 0.95 * phase
        gpu.set_color(int(r * scale), int(g * scale), int(b * scale))
        time.sleep(0.05)
        t += 0.05


def cmd_rainbow(gpu, args):
    end = time.time() + args.seconds
    print(f"rainbow for {args.seconds}s (ctrl-c to stop)")
    hue = 0.0
    while time.time() < end:
        r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
        gpu.set_color(r, g, b)
        hue = (hue + 0.004) % 1.0
        time.sleep(0.05)


def _palette_color(colors, pos):
    """Colour at fractional position `pos` (0..1 = one lap of the palette),
    linearly crossfaded between neighbouring entries and wrapping around."""
    n = len(colors)
    p = (pos % 1.0) * n
    i = int(p)
    frac = p - i
    c0 = colors[i % n]
    c1 = colors[(i + 1) % n]
    return tuple(int(round(a + (b - a) * frac)) for a, b in zip(c0, c1))


def cmd_spin(gpu, args):
    """Rotate through colours over time.

    The card has a single zone, so there is nothing to rotate *across* — the
    rotation is in time: the whole card walks the colour wheel (or the given
    palette) at a constant rate.

    Brightness is applied by scaling RGB in software rather than through the
    brightness byte, so it behaves the same whether or not the firmware
    honours that byte.
    """
    scale = max(0, min(255, args.brightness)) / 255.0
    period = max(0.05, args.speed)
    interval = 1.0 / SPIN_FPS

    if args.palette:
        what = f"palette of {len(args.palette)} colors"
    else:
        what = f"rainbow (saturation {args.saturation:.2f})"
    span = "forever" if args.seconds is None else f"{args.seconds:g}s"
    print(f"spinning {what}, {period:g}s per lap"
          f"{', reversed' if args.reverse else ''}, {span} (ctrl-c to stop)")

    start = time.monotonic()
    frame = 0
    while True:
        now = time.monotonic()
        elapsed = now - start
        if args.seconds is not None and elapsed >= args.seconds:
            break

        pos = (elapsed / period) % 1.0
        if args.reverse:
            pos = 1.0 - pos

        if args.palette:
            r, g, b = _palette_color(args.palette, pos)
        else:
            r, g, b = (int(round(c * 255))
                       for c in colorsys.hsv_to_rgb(pos, args.saturation, 1.0))

        gpu.set_color(int(r * scale), int(g * scale), int(b * scale))

        # Sleep to the next frame boundary so the lap time does not drift with
        # however long the I2C write took.
        frame += 1
        time.sleep(max(0.0, start + frame * interval - time.monotonic()))


def cmd_scan(gpu, args):
    print("read-only I2C scan of the GPU bus (no writes), 8 bytes per address")
    for addr in range(0x08, 0x78):
        rc, data = gpu.read(8, addr=addr)
        if rc == ADL_OK:
            print(f"  0x{addr:02X}: {' '.join(f'{x:02X}' for x in data)}")
    print("done")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Control ASRock Radeon GPU RGB LEDs via AMD ADL I2C")
    ap.add_argument("--channel", type=int, default=DEFAULT_CHANNEL,
                    help=f"RGB channel index (default {DEFAULT_CHANNEL} = Top Side)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show adapter and controller status").set_defaults(func=cmd_info)

    p = sub.add_parser("set", help="set a static color")
    p.add_argument("color", type=parse_rgb)
    p.add_argument("--brightness", type=int, default=0xFF)
    p.set_defaults(func=cmd_set)

    sub.add_parser("off", help="turn the LEDs off").set_defaults(func=cmd_off)

    p = sub.add_parser("breathe", help="software breathing effect")
    p.add_argument("color", type=parse_rgb)
    p.add_argument("--seconds", type=float, default=60.0)
    p.set_defaults(func=cmd_breathe)

    p = sub.add_parser("rainbow", help="software rainbow effect")
    p.add_argument("--seconds", type=float, default=60.0)
    p.set_defaults(func=cmd_rainbow)

    p = sub.add_parser("spin", help="rotate through colours over time")
    p.add_argument("--speed", type=float, default=12.0, metavar="SECONDS",
                   help="seconds per full lap of the colour wheel (default 12)")
    p.add_argument("--reverse", action="store_true",
                   help="rotate the other way round")
    p.add_argument("--palette", type=parse_palette, metavar="RRGGBB,RRGGBB,...",
                   help="crossfade between these colours instead of the "
                        "continuous rainbow")
    p.add_argument("--saturation", type=float, default=1.0, metavar="0..1",
                   help="rainbow saturation; lower is pastel (default 1.0), "
                        "ignored with --palette")
    p.add_argument("--brightness", type=int, default=0xFF, metavar="0..255",
                   help="applied by scaling RGB in software (default 255)")
    p.add_argument("--seconds", type=float, default=None,
                   help="stop after this many seconds (default: run forever)")
    p.set_defaults(func=cmd_spin)

    sub.add_parser("scan", help="read-only I2C scan of the GPU bus").set_defaults(func=cmd_scan)

    args = ap.parse_args(argv)

    try:
        gpu = AsrockGpu(channel=args.channel)
    except (OSError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        args.func(gpu, args)
    except KeyboardInterrupt:
        print("\ninterrupted")
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
