"""Rekam sesi dataset langsung dari stream kacamata (tanpa service guardian).

ESP hanya melayani SATU klien, jadi hentikan service dulu:
    sudo systemctl stop guardian
    python tools/record_session.py --cahaya malam --lokasi jalan --benda pisau --duration 120

Saat service berjalan, pakai tombol "Rekam dataset" di tab Kamera (hasilnya sama).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from guardian.config import load_config  # noqa: E402
from guardian.ingest.stream_reader import StreamReader  # noqa: E402
from guardian.recorder import DatasetRecorder  # noqa: E402
from guardian.state import State  # noqa: E402


def main() -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=cfg.get("glasses.stream_url"))
    ap.add_argument("--duration", type=float, default=0, help="detik (0 = sampai Ctrl+C)")
    for k in ("nama", "lokasi", "cahaya", "jarak", "gerak", "benda", "relawan_id", "catatan", "preset"):
        ap.add_argument(f"--{k}", default="")
    args = ap.parse_args()

    state = State()
    reader = StreamReader(args.url, state)
    rec = DatasetRecorder(cfg.path(cfg.get("recorder.dir", "dataset_raw")),
                          cfg.path(cfg.get("recorder.log_csv", "dataset_raw/dataset_log.csv")), state, cfg.tz)
    info = {k: getattr(args, k) for k in ("nama", "lokasi", "cahaya", "jarak", "gerak", "benda", "relawan_id", "catatan")}
    rec.start(info, {"preset_name": args.preset or "?", "source_url": args.url, "tool": "record_session.py"})
    reader.add_frame_callback(rec.on_frame)
    reader.start()
    t0 = time.time()
    try:
        while not args.duration or time.time() - t0 < args.duration:
            time.sleep(1)
            st = rec.status()
            print(f"\r{st['session']}: {st['frames']} frame, {st['fps']} fps, {st['elapsed_s']} s", end="", flush=True)
    except KeyboardInterrupt:
        pass
    reader.remove_frame_callback(rec.on_frame)
    reader.stop()
    print("\n", rec.stop())


if __name__ == "__main__":
    main()
