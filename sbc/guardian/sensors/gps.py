"""Pembaca GPS NMEA (VK2828U7G5LF / u-blox 7) lewat UART."""
from __future__ import annotations

import logging
import threading
import time

import pynmea2
import serial

log = logging.getLogger(__name__)


class GpsReader(threading.Thread):
    def __init__(self, port: str, baud: int, state):
        super().__init__(name="gps", daemon=True)
        self.port, self.baud = port, baud
        self.state = state
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def handle_sentence(self, line: str) -> None:
        if not line.startswith("$"):
            return
        try:
            msg = pynmea2.parse(line)
        except pynmea2.ParseError:
            return
        now = time.time()
        st = msg.sentence_type
        if st == "GGA":
            qual = int(msg.gps_qual or 0)
            sats = int(msg.num_sats or 0)
            hdop = float(msg.horizontal_dil) if msg.horizontal_dil else None
            if qual > 0 and msg.latitude and msg.longitude:
                self.state.update("gps", fix=True, lat=round(msg.latitude, 6), lon=round(msg.longitude, 6),
                                  sats=sats, hdop=hdop, fix_ts=now, last_sentence=now)
            else:
                self.state.update("gps", fix=False, sats=sats, hdop=hdop, last_sentence=now)
        elif st == "RMC":
            if msg.status == "A" and msg.latitude and msg.longitude:
                self.state.update("gps", fix=True, lat=round(msg.latitude, 6), lon=round(msg.longitude, 6),
                                  fix_ts=now, last_sentence=now)
            else:
                self.state.update("gps", last_sentence=now)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                with serial.Serial(self.port, self.baud, timeout=1) as ser:
                    log.info("GPS terbuka di %s @%d", self.port, self.baud)
                    while not self._stop.is_set():
                        raw = ser.readline()
                        if raw:
                            self.handle_sentence(raw.decode("ascii", errors="ignore").strip())
            except (serial.SerialException, OSError) as e:
                log.warning("GPS error (%s): %s", self.port, e)
                self.state.update("gps", fix=False)
                self._stop.wait(3)
