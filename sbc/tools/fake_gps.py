"""Simulator GPS NMEA lewat pseudo-terminal.

    python tools/fake_gps.py --lat -7.2800 --lon 112.7900
Cetak path pty (mis. /dev/pts/3) dan symlink /tmp/fake_gps; set gps.port: /tmp/fake_gps

Perintah: x = toggle fix hilang/ada, q = keluar
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time
import tty
from datetime import datetime, timezone


def checksum(body: str) -> str:
    c = 0
    for ch in body:
        c ^= ord(ch)
    return f"{c:02X}"


def nmea(body: str) -> bytes:
    return f"${body}*{checksum(body)}\r\n".encode()


def fmt_lat(lat: float) -> tuple[str, str]:
    a = abs(lat)
    d = int(a)
    return f"{d:02d}{(a - d) * 60:07.4f}", "N" if lat >= 0 else "S"


def fmt_lon(lon: float) -> tuple[str, str]:
    a = abs(lon)
    d = int(a)
    return f"{d:03d}{(a - d) * 60:07.4f}", "E" if lon >= 0 else "W"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=-7.2800)
    ap.add_argument("--lon", type=float, default=112.7900)
    ap.add_argument("--radius", type=float, default=300, help="radius lintasan melingkar (m)")
    ap.add_argument("--period", type=float, default=300, help="detik per putaran")
    ap.add_argument("--link", default="/tmp/fake_gps")
    args = ap.parse_args()

    master, slave = os.openpty()
    tty.setraw(slave)
    name = os.ttyname(slave)
    try:
        if os.path.islink(args.link):
            os.unlink(args.link)
        os.symlink(name, args.link)
    except OSError:
        pass
    print(f"GPS palsu di {name} (symlink {args.link}); ketik x=toggle fix, q=keluar")

    state = {"fix": True}

    def loop():
        t0 = time.time()
        while True:
            t = time.time() - t0
            ang = 2 * math.pi * t / args.period
            dlat = args.radius * math.sin(ang) / 111320
            dlon = args.radius * math.cos(ang) / (111320 * math.cos(math.radians(args.lat)))
            lat, lon = args.lat + dlat, args.lon + dlon
            now = datetime.now(timezone.utc)
            hms = now.strftime("%H%M%S.00")
            la, ns = fmt_lat(lat)
            lo, ew = fmt_lon(lon)
            if state["fix"]:
                gga = f"GPGGA,{hms},{la},{ns},{lo},{ew},1,08,0.9,10.0,M,0.0,M,,"
                rmc = f"GPRMC,{hms},A,{la},{ns},{lo},{ew},1.2,90.0,{now:%d%m%y},,,A"
            else:
                gga = f"GPGGA,{hms},,,,,0,00,99.9,,M,,M,,"
                rmc = f"GPRMC,{hms},V,,,,,,,{now:%d%m%y},,,N"
            os.write(master, nmea(gga) + nmea(rmc))
            time.sleep(1)

    threading.Thread(target=loop, daemon=True).start()
    for line in sys.stdin:
        c = line.strip().lower()
        if c == "x":
            state["fix"] = not state["fix"]
            print("fix:", state["fix"])
        elif c == "q":
            break


if __name__ == "__main__":
    main()
