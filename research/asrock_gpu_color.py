"""
ASRock GPU RGB color control over AMD ADL I2C (address 0x36, iLine=1).

Protocol (OpenRGB MR !3402, ported from SignalRGB's "ASRock GPU.js"):
    packet = [0x10, 0x00, channel, mode, R, G, B, brightness, speed, dir, 0x1A, 0]
    mode 0x01 = static/direct

Usage:
    asrock_gpu_color.py all RRGGBB [hold_seconds]     -> blast every channel 0..15
    asrock_gpu_color.py ch N RRGGBB [hold_seconds]    -> single channel
    asrock_gpu_color.py sweep [seconds_per_channel]   -> one channel at a time, rest off
"""

import sys
import time

sys.path.insert(0, r"C:\Users\KnuPwns\AppData\Local\Temp\claude\C--Users-KnuPwns\2bf64aa1-1617-40f0-9a51-757c870d1f29\scratchpad")

from asrock_gpu_probe import Adl, parse_pnp, asrock_packet, AMD_VEN, EXPECT_DEV, ADL_OK

ADDR = 0x36
BRIGHTNESS = 0xFF
SPEED = 0xFF
DIRECTION = 0x00
MAGIC = 0x1A
CHANNEL_NAMES = {3: "ARGB Header", 6: "Top Side", 7: "Fan"}


def target(adl):
    for a in adl.adapters():
        ids = parse_pnp(a.strPNPString.decode("ascii", "ignore"))
        if ids.get("ven") == AMD_VEN and ids.get("dev") == EXPECT_DEV:
            return a.iAdapterIndex
    raise RuntimeError("AMD GPU not found on ADL")


def set_channel(adl, idx, channel, r, g, b, brightness=BRIGHTNESS):
    data = [0x01, r, g, b, brightness, SPEED, DIRECTION, MAGIC]
    return adl.i2c_write(idx, ADDR, asrock_packet(0x10, channel, data))


def parse_rgb(s):
    v = int(s, 16)
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF


def refresh_loop(adl, idx, assignments, seconds):
    """Resend every 300 ms so a controller that falls back to a hardware
    effect gets held in static mode for the whole observation window."""
    end = time.time() + seconds
    while time.time() < end:
        for ch, (r, g, b) in assignments.items():
            set_channel(adl, idx, ch, r, g, b)
        time.sleep(0.3)


def main(argv):
    adl = Adl()
    idx = target(adl)
    mode = argv[1] if len(argv) > 1 else "all"

    if mode == "all":
        r, g, b = parse_rgb(argv[2] if len(argv) > 2 else "FF0000")
        hold = float(argv[3]) if len(argv) > 3 else 20.0
        print(f"setting channels 0..15 to #{r:02X}{g:02X}{b:02X}, holding {hold}s")
        for ch in range(16):
            rc = set_channel(adl, idx, ch, r, g, b)
            print(f"  ch {ch:2d} ({CHANNEL_NAMES.get(ch, '')}) rc={rc}")
            time.sleep(0.03)
        refresh_loop(adl, idx, {ch: (r, g, b) for ch in range(16)}, hold)
        print("done")

    elif mode == "ch":
        ch = int(argv[2])
        r, g, b = parse_rgb(argv[3])
        hold = float(argv[4]) if len(argv) > 4 else 10.0
        print(f"channel {ch} -> #{r:02X}{g:02X}{b:02X} for {hold}s")
        refresh_loop(adl, idx, {ch: (r, g, b)}, hold)
        print("done")

    elif mode == "sweep":
        per = float(argv[2]) if len(argv) > 2 else 4.0
        print(f"sweeping channels 0..7, {per}s each, others forced black")
        for ch in range(8):
            print(f"  --> channel {ch} ({CHANNEL_NAMES.get(ch, 'unknown')}) RED at t={time.strftime('%H:%M:%S')}")
            assignments = {c: (0, 0, 0) for c in range(8)}
            assignments[ch] = (0xFF, 0x00, 0x00)
            refresh_loop(adl, idx, assignments, per)
        print("done")

    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
