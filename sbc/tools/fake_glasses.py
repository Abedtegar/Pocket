"""Simulator kacamata: server MJPEG + MQTT palsu (hr, status, online/LWT, camera/state).

Contoh:
    python tools/fake_glasses.py --video uji.mp4            # MJPEG di :8081/stream
    python tools/fake_glasses.py --port 8081 --mqtt 127.0.0.1

Lalu di config.yaml: glasses.stream_url: http://127.0.0.1:8081/stream

Perintah keyboard (ketik lalu Enter):
    n = HR normal   h = HR tinggi (135)   l = HR rendah (40)   f = toggle jari
    o = kirim offline (online=0)   c = online lagi   s = hentikan stream 30 s   q = keluar
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import paho.mqtt.client as mqtt

FRAMESIZES = {"QQVGA": (160, 120), "QVGA": (320, 240), "CIF": (400, 296), "VGA": (640, 480), "SVGA": (800, 600)}


class Sim:
    def __init__(self, args):
        self.args = args
        self.hr_mode = "normal"
        self.finger = True
        self.bpm = 78.0
        self.stream_pause_until = 0.0
        self.cam = {"framesize": "QVGA", "quality": 12, "brightness": 0, "contrast": 0, "saturation": 0,
                    "hmirror": 0, "vflip": 0}
        self.frame_lock = threading.Lock()
        self.jpeg = b""
        self.start = time.time()
        self.cap = cv2.VideoCapture(args.video) if args.video else None

    # ---- video ----
    def make_frame(self, t: float) -> np.ndarray:
        w, h = FRAMESIZES.get(self.cam["framesize"], (320, 240))
        img = None
        if self.cap is not None:
            ok, img = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, img = self.cap.read()
            if ok:
                img = cv2.resize(img, (w, h))
        if img is None:
            img = np.full((h, w, 3), 60, np.uint8)
            x = int((np.sin(t) * 0.4 + 0.5) * w)
            cv2.circle(img, (x, h // 2), max(8, h // 8), (0, 180, 255), -1)
            cv2.putText(img, time.strftime("%H:%M:%S"), (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        img = cv2.convertScaleAbs(img, alpha=1 + 0.25 * self.cam.get("contrast", 0),
                                  beta=25 * self.cam.get("brightness", 0))
        if self.cam.get("hmirror"):
            img = cv2.flip(img, 1)
        if self.cam.get("vflip"):
            img = cv2.flip(img, 0)
        return img

    def video_loop(self) -> None:
        while True:
            img = self.make_frame(time.time() - self.start)
            q = int(100 - (self.cam.get("quality", 12) - 4) * 1.5)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, max(10, min(95, q))])
            if ok:
                with self.frame_lock:
                    self.jpeg = buf.tobytes()
            time.sleep(1.0 / self.args.fps)

    # ---- MQTT ----
    def mqtt_start(self) -> None:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-glasses")
        c.will_set("glasses/online", "0", qos=1, retain=True)
        c.on_connect = self.on_connect
        c.on_message = self.on_message
        c.connect(self.args.mqtt, self.args.mqtt_port, keepalive=10)
        c.loop_start()
        self.client = c

    def on_connect(self, client, userdata, flags, rc, props=None):
        print("[mqtt] terhubung")
        client.subscribe([("glasses/camera/set", 1), ("glasses/cmd", 1)])
        client.publish("glasses/online", "1", qos=1, retain=True)
        client.publish("glasses/camera/state", json.dumps(self.cam), qos=1, retain=True)

    def on_message(self, client, userdata, msg):
        data = json.loads(msg.payload or b"{}")
        print(f"[mqtt] {msg.topic} {data}")
        if msg.topic == "glasses/camera/set":
            self.cam.update(data)
            if "framesize" in data:
                self.stream_pause_until = time.time() + 1.0  # ESP asli memutus stream saat ganti resolusi
            client.publish("glasses/camera/state", json.dumps(self.cam), qos=1, retain=True)

    def sensor_loop(self) -> None:
        last_status = 0.0
        while True:
            target = {"normal": 78, "high": 135, "low": 40}[self.hr_mode]
            self.bpm += (target - self.bpm) * 0.3 + random.uniform(-2, 2)
            bpm = int(self.bpm) if self.finger else 0
            self.client.publish("glasses/hr", json.dumps({"bpm": bpm, "finger": self.finger,
                                                          "ir": 80000 if self.finger else 1200,
                                                          "ts": int((time.time() - self.start) * 1000)}))
            if time.time() - last_status >= 10:
                last_status = time.time()
                self.client.publish("glasses/status", json.dumps({
                    "batt_mv": 3900 - int((time.time() - self.start) / 60), "rssi": random.randint(-65, -50),
                    "uptime": int(time.time() - self.start), "heap": 120000, "cam_ok": True}))
            time.sleep(1)


def make_handler(sim: Sim):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/capture"):
                with sim.frame_lock:
                    jpg = sim.jpeg
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpg)))
                self.end_headers()
                self.wfile.write(jpg)
                return
            if not self.path.startswith("/stream"):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=123456789000000000000987654321")
            self.end_headers()
            print("[http] klien stream terhubung:", self.client_address[0])
            try:
                while True:
                    if time.time() < sim.stream_pause_until:
                        return  # putuskan koneksi (simulasi ganti framesize / stream mati)
                    with sim.frame_lock:
                        jpg = sim.jpeg
                    if jpg:
                        self.wfile.write(b"\r\n--123456789000000000000987654321\r\n")
                        self.wfile.write(f"Content-Type: image/jpeg\r\nContent-Length: {len(jpg)}\r\n\r\n".encode())
                        self.wfile.write(jpg)
                    time.sleep(1.0 / sim.args.fps)
            except (BrokenPipeError, ConnectionResetError):
                print("[http] klien stream terputus")
    return H


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", help="file video sumber (default: gambar sintetis)")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--fps", type=float, default=12)
    ap.add_argument("--mqtt", default="127.0.0.1")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--no-mqtt", action="store_true")
    ap.add_argument("--hr-high", action="store_true", help="mulai dengan HR tinggi")
    args = ap.parse_args()

    sim = Sim(args)
    if args.hr_high:
        sim.hr_mode = "high"
    threading.Thread(target=sim.video_loop, daemon=True).start()
    if not args.no_mqtt:
        sim.mqtt_start()
        threading.Thread(target=sim.sensor_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(sim))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"MJPEG: http://0.0.0.0:{args.port}/stream  — ketik n/h/l/f/o/c/s/q lalu Enter")

    for line in sys.stdin:
        cmd = line.strip().lower()
        if cmd == "n":
            sim.hr_mode = "normal"
        elif cmd == "h":
            sim.hr_mode = "high"
        elif cmd == "l":
            sim.hr_mode = "low"
        elif cmd == "f":
            sim.finger = not sim.finger
        elif cmd == "o" and not args.no_mqtt:
            sim.client.publish("glasses/online", "0", qos=1, retain=True)
        elif cmd == "c" and not args.no_mqtt:
            sim.client.publish("glasses/online", "1", qos=1, retain=True)
        elif cmd == "s":
            sim.stream_pause_until = time.time() + 30
        elif cmd == "q":
            break
        print(f"hr={sim.hr_mode} finger={sim.finger}")
    if not args.no_mqtt:
        sim.client.publish("glasses/online", "0", qos=1, retain=True).wait_for_publish(2)


if __name__ == "__main__":
    main()
