"""Benchmark detektor di Orange Pi: FPS + latensi per tahap, RAM, suhu CPU.

    python tools/bench_detector.py --model models/yolov5n.onnx --runs 100
    python tools/bench_detector.py --backend ncnn --model models/yolov5n_ncnn_model --image uji.jpg
    python tools/bench_detector.py --model models/yolov5n.onnx --clahe   # ukur biaya CLAHE
"""
from __future__ import annotations

import argparse
import resource
import statistics
import sys
import time
from glob import glob
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from guardian.vision.detector import Detector  # noqa: E402
from guardian.vision.preprocess import PreprocessConfig, Preprocessor  # noqa: E402


def cpu_temp() -> float | None:
    temps = []
    for f in glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            temps.append(int(open(f).read().strip()) / 1000)
        except (OSError, ValueError):
            pass
    return max(temps) if temps else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--backend", default="onnx", choices=["onnx", "ncnn"])
    ap.add_argument("--image", help="gambar uji (default: frame sintetis 320x240)")
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--height", type=int, default=240)
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--clahe", action="store_true")
    ap.add_argument("--denoise", action="store_true")
    args = ap.parse_args()

    if args.image:
        img = cv2.imread(args.image)
        img = cv2.resize(img, (args.width, args.height))
    else:
        img = np.random.randint(0, 255, (args.height, args.width, 3), np.uint8)
    _, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    jpg = jpg.tobytes()

    det = Detector({"model": args.model, "backend": args.backend, "imgsz": args.imgsz, "threads": args.threads},
                   Path.cwd())
    pre = Preprocessor(PreprocessConfig.from_dict({"clahe": args.clahe, "denoise": args.denoise}))
    t_before = cpu_temp()
    stages: dict[str, list[float]] = {k: [] for k in ("decode", "preprocess", "letterbox", "infer", "nms", "total")}
    ndet = 0
    for i in range(args.warmup + args.runs):
        t0 = time.perf_counter()
        frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        t1 = time.perf_counter()
        proc = pre.apply(frame)
        t2 = time.perf_counter()
        dets, tm = det.detect(proc, args.conf, 0.45)
        t3 = time.perf_counter()
        if i >= args.warmup:
            stages["decode"].append((t1 - t0) * 1000)
            stages["preprocess"].append((t2 - t1) * 1000)
            for k in ("letterbox", "infer", "nms"):
                stages[k].append(tm[k])
            stages["total"].append((t3 - t0) * 1000)
            ndet = len(dets)

    print(f"\nModel   : {args.model} ({args.backend}, {args.threads} thread, imgsz {args.imgsz})")
    print(f"Frame   : {args.width}x{args.height}, runs {args.runs}, clahe={args.clahe}, denoise={args.denoise}")
    print(f"{'tahap':<11}{'mean ms':>9}{'p95 ms':>9}")
    for k, v in stages.items():
        v.sort()
        print(f"{k:<11}{statistics.mean(v):>9.1f}{v[int(len(v) * 0.95) - 1]:>9.1f}")
    print(f"FPS     : {1000 / statistics.mean(stages['total']):.2f}")
    print(f"RAM max : {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")
    print(f"Suhu CPU: {t_before} -> {cpu_temp()} °C")
    print(f"Deteksi di frame terakhir: {ndet}")


if __name__ == "__main__":
    main()
