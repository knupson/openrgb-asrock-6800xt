"""
Protocol probe for the ASRock GPU RGB controller at I2C 0x36 (AMD ADL, iLine=1).

Only queries (0x14 = channel/LED info). No color writes.
Sweeps read length, delay and read action to find the response framing.
"""

import sys
import time

sys.path.insert(0, r"C:\Users\KnuPwns\AppData\Local\Temp\claude\C--Users-KnuPwns\2bf64aa1-1617-40f0-9a51-757c870d1f29\scratchpad")

from asrock_gpu_probe import Adl, parse_pnp, hexs, asrock_packet, AMD_VEN, EXPECT_DEV, ADL_OK

ADDR = 0x36
ACTION_READ = 1
ACTION_READ_REPSTART = 3


def target(adl):
    for a in adl.adapters():
        ids = parse_pnp(a.strPNPString.decode("ascii", "ignore"))
        if ids.get("ven") == AMD_VEN and ids.get("dev") == EXPECT_DEV:
            return a.iAdapterIndex
    return None


def main():
    adl = Adl()
    idx = target(adl)

    print("=== idle reads (no preceding write), 5x 12 bytes ===")
    for i in range(5):
        rc, d = adl.i2c_read(idx, ADDR, 12)
        print(f"  {i}: rc={rc} {hexs(d)}")
        time.sleep(0.05)

    print("\n=== read length sweep, no write ===")
    for ln in (1, 2, 4, 8, 12, 16, 20, 32):
        rc, d = adl.i2c_read(idx, ADDR, ln)
        print(f"  len={ln:2d}: rc={rc} {hexs(d)}")

    print("\n=== 0x14/0x01 (enabled channels) : delay x readlen sweep ===")
    for delay in (0.0, 0.005, 0.02, 0.05):
        for ln in (8, 12, 16):
            wrc = adl.i2c_write(idx, ADDR, asrock_packet(0x14, 0x01))
            if delay:
                time.sleep(delay)
            rc, d = adl.i2c_read(idx, ADDR, ln)
            print(f"  delay={delay*1000:5.1f}ms len={ln:2d}: wrc={wrc} rrc={rc} {hexs(d)}")
            time.sleep(0.05)

    print("\n=== 0x14/0x01 with repeated-start read ===")
    for ln in (8, 12, 16):
        wrc = adl.i2c_write(idx, ADDR, asrock_packet(0x14, 0x01))
        time.sleep(0.02)
        rc, d = adl.i2c_read(idx, ADDR, ln, action=ACTION_READ_REPSTART)
        print(f"  len={ln:2d}: wrc={wrc} rrc={rc} {hexs(d)}")
        time.sleep(0.05)

    print("\n=== 0x14/0x02 (LED counts), 12-byte reads ===")
    for i in range(3):
        wrc = adl.i2c_write(idx, ADDR, asrock_packet(0x14, 0x02))
        time.sleep(0.02)
        rc, d = adl.i2c_read(idx, ADDR, 12)
        print(f"  {i}: wrc={wrc} rrc={rc} {hexs(d)}")
        time.sleep(0.05)

    print("\n=== subcommand sweep 0x14/0x00..0x08, 12-byte reads ===")
    for sub in range(0, 9):
        wrc = adl.i2c_write(idx, ADDR, asrock_packet(0x14, sub))
        time.sleep(0.02)
        rc, d = adl.i2c_read(idx, ADDR, 12)
        print(f"  sub=0x{sub:02X}: wrc={wrc} rrc={rc} {hexs(d)}")
        time.sleep(0.05)

    # Deliberately no sweep over unknown command bytes (0x11..0x16): unknown
    # commands on an unknown firmware could touch flash/bootloader state.
    # Stay within the documented 0x14 (query) family until 0x10 (color) is proven.

    return 0


if __name__ == "__main__":
    sys.exit(main())
