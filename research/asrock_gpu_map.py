"""
Map ASRock GPU RGB channels to physical zones by giving each candidate
channel a distinct color at the same time.

ch3 (ARGB Header) = red, ch6 (Top Side) = green, ch7 (Fan) = blue,
every other channel 0..15 = black.
"""

import sys
import time

sys.path.insert(0, r"C:\Users\KnuPwns\AppData\Local\Temp\claude\C--Users-KnuPwns\2bf64aa1-1617-40f0-9a51-757c870d1f29\scratchpad")

from asrock_gpu_color import set_channel, target, refresh_loop
from asrock_gpu_probe import Adl

PLAN = {3: (0xFF, 0x00, 0x00), 6: (0x00, 0xFF, 0x00), 7: (0x00, 0x00, 0xFF)}


def main():
    adl = Adl()
    idx = target(adl)

    hold = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0

    assignments = {ch: (0, 0, 0) for ch in range(16)}
    assignments.update(PLAN)

    for ch, (r, g, b) in assignments.items():
        rc = set_channel(adl, idx, ch, r, g, b)
        if ch in PLAN:
            print(f"  ch {ch} -> #{r:02X}{g:02X}{b:02X} rc={rc}")
        time.sleep(0.03)

    print(f"holding {hold}s with refresh")
    refresh_loop(adl, idx, assignments, hold)
    print("done - final state left as set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
