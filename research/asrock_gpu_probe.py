"""
ASRock GPU RGB probe over AMD ADL I2C (Windows).

Replicates OpenRGB's i2c_smbus_amdadl backend (iLine=1, iAddress=addr<<1,
pure I2C via ADL2_Display_WriteAndReadI2C) and the ASRock GPU protocol from
OpenRGB MR !3402 / SignalRGB's "ASRock GPU.js":

    packet = [cmd, 0x00, subcmd, data...]  padded to 12 bytes
    0x14 / 0x01 -> enabled channel bitmap (response bytes 4-5)
    0x14 / 0x02 -> LED counts (response byte 4+channel)
    0x10 / ch   -> [0x01, R, G, B, brightness, speed, direction, 0x1A]

Phase 1 (this script): read-only presence check, then the 0x14 queries.
No color writes here.
"""

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

ASROCK_ADDR = 0x36
AMD_VEN = 0x1002
EXPECT_DEV = 0x73BF
EXPECT_SUBVEN = 0x1849
EXPECT_SUBDEV = 0x5202


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
def adl_malloc(size):
    buf = create_string_buffer(size)
    _keepalive.append(buf)
    return ctypes.cast(buf, c_void_p).value


class Adl:
    def __init__(self):
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

        rc = self.dll.ADL2_Main_Control_Create(adl_malloc, 1, byref(self.ctx))
        if rc != ADL_OK:
            raise RuntimeError(f"ADL2_Main_Control_Create failed: {rc}")

    def adapters(self):
        num = c_int(0)
        arr = POINTER(AdapterInfoX2)()
        rc = self.dll.ADL2_Adapter_AdapterInfoX4_Get(self.ctx, -1, byref(num), byref(arr))
        if rc != ADL_OK:
            raise RuntimeError(f"ADL2_Adapter_AdapterInfoX4_Get failed: {rc}")
        return [arr[i] for i in range(num.value)]

    def _xfer(self, adapter_index, addr, action, data_buf, size, line=1):
        pkt = ADLI2C()
        pkt.iSize = ctypes.sizeof(ADLI2C)
        pkt.iLine = line
        pkt.iAddress = addr << 1
        pkt.iOffset = 0
        pkt.iAction = action
        pkt.iSpeed = 100
        pkt.iDataSize = size
        pkt.pcData = ctypes.cast(data_buf, POINTER(c_char))
        return self.dll.ADL2_Display_WriteAndReadI2C(self.ctx, adapter_index, byref(pkt))

    def i2c_read(self, adapter_index, addr, length, line=1, action=ADL_DL_I2C_ACTIONREAD):
        buf = create_string_buffer(length)
        rc = self._xfer(adapter_index, addr, action, buf, length, line)
        return rc, bytes(buf.raw)

    def i2c_read_line(self, adapter_index, addr, length, line):
        return self.i2c_read(adapter_index, addr, length, line=line)

    def i2c_write(self, adapter_index, addr, payload, line=1):
        buf = create_string_buffer(bytes(payload), len(payload))
        return self._xfer(adapter_index, addr, ADL_DL_I2C_ACTIONWRITE, buf, len(payload), line)


def parse_pnp(pnp):
    ids = {}
    for key, tag, off in (("dev", "DEV_", 4), ("ven", "VEN_", 4)):
        i = pnp.find(tag)
        ids[key] = int(pnp[i + off:i + off + 4], 16) if i >= 0 else None
    i = pnp.find("SUBSYS_")
    if i >= 0:
        ids["subdev"] = int(pnp[i + 7:i + 11], 16)
        ids["subven"] = int(pnp[i + 11:i + 15], 16)
    return ids


def hexs(b):
    return " ".join(f"{x:02X}" for x in b)


def asrock_packet(cmd, subcmd, data=()):
    pkt = bytearray(12)
    pkt[0] = cmd
    pkt[1] = 0x00
    pkt[2] = subcmd
    for i, v in enumerate(data[:9]):
        pkt[3 + i] = v
    return bytes(pkt)


def main():
    adl = Adl()

    target = None
    seen_buses = set()
    print("=== ADL adapters ===")
    for a in adl.adapters():
        if a.iBusNumber in seen_buses:
            continue
        seen_buses.add(a.iBusNumber)
        pnp = a.strPNPString.decode("ascii", "ignore")
        ids = parse_pnp(pnp)
        print(f"  idx={a.iAdapterIndex} bus={a.iBusNumber} "
              f"{ids.get('ven'):04X}:{ids.get('dev'):04X} "
              f"subsys {ids.get('subven'):04X}:{ids.get('subdev'):04X} "
              f"name={a.strAdapterName.decode('ascii', 'ignore')}")
        if (ids.get("ven") == AMD_VEN and ids.get("dev") == EXPECT_DEV
                and ids.get("subven") == EXPECT_SUBVEN and ids.get("subdev") == EXPECT_SUBDEV):
            target = a.iAdapterIndex

    if target is None:
        print("target GPU 1002:73BF / 1849:5202 not found on ADL")
        return 1
    print(f"target adapter index: {target}")

    print("\n=== read-only presence check @ 0x36 (no write) ===")
    rc, data = adl.i2c_read(target, ASROCK_ADDR, 12)
    print(f"  rc={rc}  data={hexs(data)}")
    if rc != ADL_OK:
        print("  no read response; aborting before any write")
        return 2

    print("\n=== query enabled channels: 0x14 / 0x01 ===")
    rc = adl.i2c_write(target, ASROCK_ADDR, asrock_packet(0x14, 0x01))
    print(f"  write rc={rc}")
    if rc != ADL_OK:
        return 3
    time.sleep(0.02)
    rc, data = adl.i2c_read(target, ASROCK_ADDR, 32)
    print(f"  read  rc={rc}  data={hexs(data)}")
    if rc != ADL_OK:
        return 4
    channel_bits = data[4] | (data[5] << 8)
    print(f"  channel bitmap = 0x{channel_bits:04X}")

    print("\n=== query LED counts: 0x14 / 0x02 ===")
    rc = adl.i2c_write(target, ASROCK_ADDR, asrock_packet(0x14, 0x02))
    print(f"  write rc={rc}")
    time.sleep(0.02)
    rc, counts = adl.i2c_read(target, ASROCK_ADDR, 32)
    print(f"  read  rc={rc}  data={hexs(counts)}")

    names = {3: "ARGB Header", 6: "Top Side", 7: "Fan"}
    print("\n=== channels ===")
    if channel_bits == 0:
        print("  none reported")
    for i in range(16):
        if channel_bits & (1 << i):
            n = counts[4 + i] if rc == ADL_OK and 4 + i < len(counts) else "?"
            print(f"  ch {i} ({names.get(i, 'Unknown')}): {n} LEDs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
