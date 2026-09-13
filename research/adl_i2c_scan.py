"""
Read-only I2C scan of the AMD GPU bus via ADL, plus line/action sweep.

Purpose: figure out whether ADL rc=0 actually means "device ACKed", by
comparing every address on the bus. No writes are performed.
"""

import sys
sys.path.insert(0, r"C:\Users\KnuPwns\AppData\Local\Temp\claude\C--Users-KnuPwns\2bf64aa1-1617-40f0-9a51-757c870d1f29\scratchpad")

from asrock_gpu_probe import Adl, parse_pnp, hexs, AMD_VEN, EXPECT_DEV, ADL_OK

ADL_DL_I2C_ACTIONREAD_REPEATEDSTART = 3


def find_target(adl):
    for a in adl.adapters():
        ids = parse_pnp(a.strPNPString.decode("ascii", "ignore"))
        if ids.get("ven") == AMD_VEN and ids.get("dev") == EXPECT_DEV:
            return a.iAdapterIndex
    return None


def main():
    adl = Adl()
    idx = find_target(adl)
    if idx is None:
        print("no AMD GPU adapter")
        return 1

    print(f"adapter {idx}: read-only scan, iLine=1, 8 bytes per address")
    hits = []
    for addr in range(0x08, 0x78):
        rc, data = adl.i2c_read(idx, addr, 8)
        interesting = rc == ADL_OK and len(set(data)) > 1
        if rc == ADL_OK:
            hits.append((addr, data))
        if interesting or addr == 0x36:
            print(f"  0x{addr:02X}: rc={rc} {hexs(data)}{'   <-- varied' if interesting else ''}")

    uniform = {}
    for addr, data in hits:
        uniform.setdefault(data, []).append(addr)
    print(f"\nrc==0 on {len(hits)}/{0x78 - 0x08} addresses")
    print("distinct payloads seen:")
    for data, addrs in uniform.items():
        rng = ", ".join(f"0x{a:02X}" for a in addrs[:12])
        more = f" (+{len(addrs) - 12} more)" if len(addrs) > 12 else ""
        print(f"  {hexs(data)}  <- {len(addrs)} addr: {rng}{more}")

    print("\n=== iLine sweep at 0x36 (read-only, 8 bytes) ===")
    for line in range(0, 8):
        pkt_rc, data = adl.i2c_read_line(idx, 0x36, 8, line)
        print(f"  iLine={line}: rc={pkt_rc} {hexs(data)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
