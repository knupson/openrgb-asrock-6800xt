"""
spin_all - drive the `spin` colour rotation across every device OpenRGB sees.

Why this exists
---------------
`asrock_gpu_rgb.py` talks straight to the GPU's I2C controller, so it can only
light the graphics card. Case fans, RAM and motherboard zones hang off other
controllers entirely. OpenRGB already has drivers for all of them, so this
script drives OpenRGB instead of the hardware: OpenRGB is the only process
touching any bus, and this one talks to it over the SDK's TCP socket. That
also sidesteps the "never run the CLI and OpenRGB at the same time" rule —
there is no bus contention, because only OpenRGB writes.

Every device is sent the same colour on every frame, so the whole machine
rotates in phase.

The client below is a minimal implementation of the OpenRGB SDK network
protocol, written against `OpenRGB/Documentation/OpenRGBSDK.md` in this repo.
The `openrgb-python` package on PyPI (0.3.6) only understands up to protocol
version 4 and fails to parse this server's protocol 6 device blocks:

    ValueError: 256 is not a valid ZoneType

Usage
-----
    python spin_all.py --list
    python spin_all.py
    python spin_all.py --speed 6 --reverse
    python spin_all.py --palette FF0000,00FF00,0000FF
    python spin_all.py --off

OpenRGB must be running with its SDK server enabled:

    "C:\\Program Files\\OpenRGB-patched\\OpenRGB.exe" --server --startminimized
"""

import argparse
import colorsys
import os
import select
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asrock_gpu_rgb import SPIN_FPS, _palette_color, parse_palette  # noqa: E402

SDK_HOST = "127.0.0.1"
SDK_PORT = 6742
CLIENT_PROTOCOL = 6

PKT_REQUEST_CONTROLLER_COUNT = 0
PKT_REQUEST_CONTROLLER_DATA = 1
PKT_REQUEST_PROTOCOL_VERSION = 40
PKT_SET_CLIENT_NAME = 50
PKT_UPDATE_LEDS = 1050
PKT_SET_CUSTOM_MODE = 1100

# The server pushes packets nobody asked for: an ack (10) after every request,
# its own name (51) right after protocol negotiation, and a device-list-changed
# notification (100). Anything that is not the reply we are waiting for gets
# skipped, otherwise the stream desyncs on the first ack.

HEADER = b"ORGB"
HEADER_LEN = 16

# A desynced stream reads a garbage length out of what it thinks is a header
# and then tries to buffer it. The largest real payload here is one device
# description, a few kB, so anything past this is a framing bug, not a packet.
# Without the cap the read loop happily allocates gigabytes.
MAX_PAYLOAD = 4 << 20


class Reader:
    """Little-endian cursor over a device-description blob."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, n):
        chunk = self.data[self.pos:self.pos + n]
        if len(chunk) != n:
            raise ValueError(f"truncated device data at offset {self.pos}")
        self.pos += n
        return chunk

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def string(self):
        # Length includes the null terminator.
        n = self.u16()
        return self.take(n).rstrip(b"\x00").decode("utf-8", "replace")


def _parse_mode(r, version):
    mode = {"name": r.string()}
    if version < 6:
        r.i32()                     # mode_value, internal-use, dropped in v6
    mode["flags"] = r.u32()
    r.u32(), r.u32()                # speed_min, speed_max
    if version >= 3:
        r.u32(), r.u32()            # brightness_min, brightness_max
    r.u32(), r.u32()                # colors_min, colors_max
    r.u32()                         # speed
    if version >= 3:
        r.u32()                     # brightness
    r.u32(), r.u32()                # direction, color_mode
    for _ in range(r.u16()):        # mode colors
        r.u32()
    return mode


def _parse_matrix(r):
    n = r.u16()
    if n:
        r.take(n)


def _parse_segment(r, version):
    r.string()                      # segment name
    r.i32()                         # segment type
    r.u32(), r.u32()                # start_idx, leds_count
    if version >= 6:
        _parse_matrix(r)
        r.u32()                     # segment flags


def _parse_zone(r, version):
    zone = {"name": r.string()}
    r.i32()                         # zone type
    r.u32(), r.u32()                # leds_min, leds_max
    zone["leds_count"] = r.u32()
    _parse_matrix(r)
    if version >= 4:
        for _ in range(r.u16()):
            _parse_segment(r, version)
    if version >= 5:
        r.u32()                     # zone flags
    if version >= 6:
        r.i32()                     # zone active_mode
        for _ in range(r.u16()):    # zone modes
            _parse_mode(r, version)
        r.string()                  # zone display_name
    return zone


def parse_device(blob, version):
    r = Reader(blob)
    r.u32()                         # data_size, already known
    device = {"type": r.i32(), "name": r.string()}
    if version >= 1:
        device["vendor"] = r.string()
    for field in ("description", "version", "serial", "location"):
        device[field] = r.string()

    num_modes = r.u16()
    device["active_mode"] = r.i32()
    device["modes"] = [_parse_mode(r, version) for _ in range(num_modes)]
    device["zones"] = [_parse_zone(r, version) for _ in range(r.u16())]

    num_leds = r.u16()
    for _ in range(num_leds):
        r.string()                  # led name
        if version < 6:
            r.u32()                 # led_value, dropped in v6
    device["num_leds"] = num_leds

    for _ in range(r.u16()):        # controller colors
        r.u32()
    if version >= 5:
        for _ in range(r.u16()):    # led display names
            r.string()
        device["flags"] = r.u32()
    if version >= 6:
        device["display_name"] = r.string()
        r.take(r.u32())             # configuration string, length is a u32 here
    if r.pos != len(blob):
        raise ValueError(f"device block parsed to {r.pos} of {len(blob)} bytes")
    return device


class OpenRGBSDK:
    def __init__(self, host=SDK_HOST, port=SDK_PORT, name="asrock-spin-all"):
        try:
            self.sock = socket.create_connection((host, port), timeout=5)
        except OSError as e:
            raise RuntimeError(
                f"cannot reach the OpenRGB SDK server at {host}:{port} ({e}). "
                f"Start OpenRGB with --server."
            ) from e
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        server_version = self._protocol_version()
        self.version = min(CLIENT_PROTOCOL, server_version)
        self._send(0, PKT_SET_CLIENT_NAME, name.encode() + b"\x00")
        self.devices = self._read_devices()

    def _send(self, dev, pkt, payload=b""):
        self.sock.sendall(HEADER + struct.pack("<III", dev, pkt, len(payload))
                          + payload)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("OpenRGB closed the connection")
            buf += chunk
        return buf

    def _recv(self, want_pkt):
        """Read packets until the reply with id `want_pkt` shows up."""
        for _ in range(32):
            head = self._recv_exact(HEADER_LEN)
            if head[:4] != HEADER:
                raise RuntimeError(f"bad SDK header magic: {head[:4]!r}")
            _dev, pkt, size = struct.unpack("<III", head[4:16])
            if size > MAX_PAYLOAD:
                raise RuntimeError(
                    f"refusing a {size} byte payload for packet {pkt}; "
                    f"the SDK stream is out of sync"
                )
            body = self._recv_exact(size)
            if pkt == want_pkt:
                return body
        raise RuntimeError(f"no reply with packet id {want_pkt}")

    def _protocol_version(self):
        self._send(0, PKT_REQUEST_PROTOCOL_VERSION,
                   struct.pack("<I", CLIENT_PROTOCOL))
        return struct.unpack("<I", self._recv(PKT_REQUEST_PROTOCOL_VERSION))[0]

    def _read_devices(self):
        self._send(0, PKT_REQUEST_CONTROLLER_COUNT)
        body = self._recv(PKT_REQUEST_CONTROLLER_COUNT)
        count = struct.unpack("<I", body[:4])[0]
        if len(body) >= 4 + 4 * count:
            # Unique-ID scheme: the count is followed by one ID per controller.
            ids = list(struct.unpack(f"<{count}I", body[4:4 + 4 * count]))
        else:
            ids = list(range(count))

        devices = []
        for dev_id in ids:
            self._send(dev_id, PKT_REQUEST_CONTROLLER_DATA,
                       struct.pack("<I", self.version))
            device = parse_device(self._recv(PKT_REQUEST_CONTROLLER_DATA),
                                  self.version)
            device["id"] = dev_id
            devices.append(device)
        return devices

    def set_custom_mode(self, dev_id):
        self._send(dev_id, PKT_SET_CUSTOM_MODE)

    def update_leds(self, dev_id, colors):
        body = struct.pack("<H", len(colors))
        body += b"".join(struct.pack("<I", r | (g << 8) | (b << 16))
                         for r, g, b in colors)
        self._send(dev_id, PKT_UPDATE_LEDS,
                   struct.pack("<I", len(body) + 4) + body)

    def drain(self):
        """Throw away anything the server has pushed at us.

        The server acks every single request. An effect loop never reads those
        acks, so they pile up in the receive buffer until it is full; then the
        server blocks writing to us, stops reading our requests, our send
        buffer fills, and sendall() blocks forever. The effect freezes mid-
        animation with no error and no CPU use. Draining once per frame is what
        keeps that from happening.
        """
        while select.select([self.sock], [], [], 0)[0]:
            if not self.sock.recv(65536):
                raise RuntimeError("OpenRGB closed the connection")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def strips(device):
    """Lengths to animate over, one per zone.

    A device's LEDs are one flat array, but its zones are separate physical
    runs: on this board indices 0..23 are the D_LED fan chain while 24 and 25
    are the CPU header and a PCI-E accent light. Rotating across all 26 as if
    they were one loop sends the comet head into those last two, and the fans
    go dark for two steps every lap. Each zone gets its own rotation instead.
    """
    zones = [z["leds_count"] for z in device["zones"]]
    if sum(zones) != device["num_leds"] or not zones:
        return [device["num_leds"]]
    return zones


def select_devices(client, only):
    """Devices with at least one LED, optionally filtered by name substring."""
    devices = [d for d in client.devices if d["num_leds"] > 0]
    if only:
        needles = [s.strip().lower() for s in only.split(",") if s.strip()]
        devices = [d for d in devices
                   if any(n in d["name"].lower() for n in needles)]
    return devices


def cmd_list(client, args):
    print(f"SDK protocol {client.version}, {len(client.devices)} devices\n")
    for d in client.devices:
        zones = ", ".join(f"{z['name']}({z['leds_count']})" for z in d["zones"])
        modes = ", ".join(m["name"] for m in d["modes"])
        print(f"[{d['id']}] {d['name']}  -  {d['num_leds']} LEDs")
        print(f"     zones : {zones or 'none'}")
        print(f"     modes : {modes}")


def run_spin(client, args):
    devices = select_devices(client, args.only)
    if not devices:
        raise RuntimeError("no matching devices with LEDs")

    for d in devices:
        client.set_custom_mode(d["id"])

    total_leds = sum(d["num_leds"] for d in devices)
    names = ", ".join(f"{d['name']} ({d['num_leds']})" for d in devices)
    print(f"driving {len(devices)} devices / {total_leds} LEDs in phase: {names}")

    if args.off:
        for d in devices:
            client.update_leds(d["id"], [(0, 0, 0)] * d["num_leds"])
        print("all off")
        return

    scale = max(0, min(255, args.brightness)) / 255.0
    period = max(0.05, args.speed)
    interval = 1.0 / max(1.0, args.fps)
    what = (f"palette of {len(args.palette)} colors" if args.palette
            else f"rainbow (saturation {args.saturation:.2f})")
    span = "forever" if args.seconds is None else f"{args.seconds:g}s"
    if args.comet:
        spread = f", comet with a {args.comet:g} tail"
    elif args.spread:
        spread = f", spread {args.spread:g} across each strip"
    else:
        spread = ""
    print(f"spinning {what}, {period:g}s per lap"
          f"{', reversed' if args.reverse else ''}{spread}, {span} (ctrl-c to stop)")

    def colour_at(pos):
        if args.palette:
            r, g, b = _palette_color(args.palette, pos)
        else:
            r, g, b = (int(round(c * 255))
                       for c in colorsys.hsv_to_rgb(pos % 1.0, args.saturation, 1.0))
        return int(r * scale), int(g * scale), int(b * scale)

    start = time.monotonic()
    frame = 0
    while True:
        elapsed = time.monotonic() - start
        if args.seconds is not None and elapsed >= args.seconds:
            break

        pos = (elapsed / period) % 1.0
        if args.reverse:
            pos = 1.0 - pos

        if args.comet:
            # A bright arc travelling over a dark strip. On a diffused fan ring
            # a full rainbow averages out to a constant smear and reads as
            # static; a lit arc against darkness is unmistakably moving.
            head = colour_at(pos)
            for d in devices:
                leds = []
                for length in strips(d):
                    if length <= 1:
                        # Nothing to travel across, so ride the head colour.
                        leds.extend([head] * length)
                        continue
                    for i in range(length):
                        behind = (pos - i / length) % 1.0
                        lit = max(0.0, 1.0 - behind / args.comet)
                        lit *= lit      # steeper falloff, crisper head
                        # Keep a floor under the whole strip. With floor 0 the
                        # arc sweeping past a diffused ring reads as the fan
                        # pulsing rather than as something going round.
                        lit = args.floor + (1.0 - args.floor) * lit
                        leds.append(tuple(int(ch * lit) for ch in head))
                client.update_leds(d["id"], leds)
        elif args.spread == 0:
            # Everything the same colour: the whole machine rotates in phase.
            flat = colour_at(pos)
            for d in devices:
                client.update_leds(d["id"], [flat] * d["num_leds"])
        else:
            # Fan the colour wheel out along each strip, so on an addressable
            # chain the colours physically travel around it. One-LED devices
            # just ride the head of the wave and stay in phase with it.
            for d in devices:
                leds = []
                for length in strips(d):
                    leds.extend(colour_at(pos + args.spread * i / length)
                                for i in range(length))
                client.update_leds(d["id"], leds)

        client.drain()

        frame += 1
        time.sleep(max(0.0, start + frame * interval - time.monotonic()))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Rotate colours across every device OpenRGB controls")
    ap.add_argument("--host", default=SDK_HOST)
    ap.add_argument("--port", type=int, default=SDK_PORT)
    ap.add_argument("--list", action="store_true",
                    help="list the devices OpenRGB sees and exit")
    ap.add_argument("--only", metavar="NAME[,NAME...]",
                    help="only drive devices whose name contains one of these")
    ap.add_argument("--off", action="store_true",
                    help="blank every selected device and exit")
    ap.add_argument("--speed", type=float, default=12.0, metavar="SECONDS",
                    help="seconds per full lap of the colour wheel (default 12)")
    ap.add_argument("--reverse", action="store_true",
                    help="rotate the other way round")
    ap.add_argument("--comet", type=float, nargs="?", const=0.35, default=None,
                    metavar="TAIL",
                    help="rotate a bright arc over a dark strip instead of a "
                         "full rainbow. TAIL is the fraction of the strip that "
                         "stays lit behind the head (default 0.35). This is the "
                         "one that actually reads as spinning on a diffused fan "
                         "ring. Overrides --spread")
    ap.add_argument("--floor", type=float, default=0.3, metavar="0..1",
                    help="minimum brightness everywhere in --comet mode "
                         "(default 0.3), so the strip stays lit and the arc "
                         "reads as rotating instead of the whole thing pulsing. "
                         "0 gives a hard comet on black")
    ap.add_argument("--spread", type=float, default=0.0, metavar="0..1",
                    help="how much of the colour wheel to fan out along each "
                         "strip: 0 (default) paints every LED the same colour "
                         "so the machine rotates in phase, 1 wraps a whole "
                         "rainbow around each addressable chain so the colours "
                         "physically travel")
    ap.add_argument("--palette", type=parse_palette, metavar="RRGGBB,RRGGBB,...",
                    help="crossfade between these colours instead of the "
                         "continuous rainbow")
    ap.add_argument("--saturation", type=float, default=1.0, metavar="0..1",
                    help="rainbow saturation; lower is pastel (default 1.0), "
                         "ignored with --palette")
    ap.add_argument("--brightness", type=int, default=0xFF, metavar="0..255",
                    help="applied by scaling RGB in software (default 255)")
    ap.add_argument("--seconds", type=float, default=None,
                    help="stop after this many seconds (default: run forever)")
    ap.add_argument("--fps", type=float, default=SPIN_FPS, metavar="N",
                    help=f"frames per second (default {SPIN_FPS:g}). SDK writes "
                         f"are fire-and-forget, so pushing frames faster than "
                         f"OpenRGB can write them to hardware just builds a "
                         f"backlog and the LEDs fall behind")
    args = ap.parse_args(argv)

    try:
        client = OpenRGBSDK(args.host, args.port)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        if args.list:
            cmd_list(client, args)
        else:
            run_spin(client, args)
    except KeyboardInterrupt:
        print("\ninterrupted")
    except (RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
