"""Detektor YOLOv5n (output [1, N, 5+C]) dengan backend ONNX Runtime atau NCNN.

Tahap: letterbox -> inferensi -> obj*cls -> NMS -> skala balik ke ukuran frame.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

COCO_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]


def letterbox(img: np.ndarray, size: int, color: int = 114):
    """Resize dengan rasio tetap + padding ke size x size. Return (img, ratio, (pad_x, pad_y))."""
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    if (nw, nh) != (w, h):
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    dw, dh = (size - nw) / 2, (size - nh) / 2
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    out = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(color,) * 3)
    return out, r, (left, top)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """NMS numpy murni. boxes [K,4] xyxy."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_thr]
    return keep


def postprocess(pred: np.ndarray, conf_thr: float, iou_thr: float, ratio: float,
                pad: tuple[int, int], orig_shape: tuple[int, int], names: list[str],
                max_det: int = 50) -> list[dict]:
    """pred: [N, 5+C] (cx, cy, w, h, obj, cls...) dalam koordinat input letterbox."""
    if pred.ndim == 3:
        pred = pred[0]
    pred = pred[pred[:, 4] > conf_thr]
    if not len(pred):
        return []
    scores_all = pred[:, 5:] * pred[:, 4:5]
    cls = scores_all.argmax(1)
    scores = scores_all[np.arange(len(cls)), cls]
    m = scores > conf_thr
    pred, cls, scores = pred[m], cls[m], scores[m]
    if not len(pred):
        return []
    xy, wh = pred[:, :2], pred[:, 2:4]
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], axis=1)
    # NMS per kelas dengan offset koordinat
    offs = (cls[:, None] * 4096.0)
    keep = nms(boxes + offs, scores, iou_thr)[:max_det]
    h, w = orig_shape
    out = []
    for i in keep:
        b = boxes[i].copy()
        b[[0, 2]] = ((b[[0, 2]] - pad[0]) / ratio).clip(0, w)
        b[[1, 3]] = ((b[[1, 3]] - pad[1]) / ratio).clip(0, h)
        c = int(cls[i])
        out.append({
            "cls": c,
            "label": names[c] if c < len(names) else str(c),
            "conf": round(float(scores[i]), 3),
            "box": [int(v) for v in b],
        })
    return out


class OnnxBackend:
    def __init__(self, path: Path, threads: int):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.input_name = self.sess.get_inputs()[0].name

    def infer(self, blob: np.ndarray) -> np.ndarray:
        return self.sess.run(None, {self.input_name: blob})[0]


class NcnnBackend:
    def __init__(self, path: Path, threads: int, input_name: str, output_name: str):
        import ncnn  # opsional
        if path.is_dir():
            params = sorted(path.glob("*.param"))
            if not params:
                raise FileNotFoundError(f"tidak ada *.param di {path}")
            param = params[0]
        else:
            param = path.with_suffix(".param")
        binf = param.with_suffix(".bin")
        self.ncnn = ncnn
        self.net = ncnn.Net()
        self.net.opt.num_threads = threads
        self.net.opt.use_vulkan_compute = False
        if self.net.load_param(str(param)) != 0 or self.net.load_model(str(binf)) != 0:
            raise RuntimeError(f"gagal memuat model NCNN {param}")
        self.input_name, self.output_name = input_name, output_name

    def infer(self, blob: np.ndarray) -> np.ndarray:
        ex = self.net.create_extractor()
        ex.input(self.input_name, self.ncnn.Mat(np.ascontiguousarray(blob[0])))
        ret, out = ex.extract(self.output_name)
        if ret != 0:
            raise RuntimeError(f"ekstraksi NCNN gagal ({ret})")
        arr = np.array(out)
        return arr[None] if arr.ndim == 2 else arr


class Detector:
    def __init__(self, vision_cfg: dict, base_dir: Path):
        self.imgsz = int(vision_cfg.get("imgsz", 320))
        self.backend_name = vision_cfg.get("backend", "onnx")
        path = Path(vision_cfg["model"])
        if not path.is_absolute():
            path = base_dir / path
        if not path.exists():
            raise FileNotFoundError(f"model tidak ditemukan: {path}")
        threads = int(vision_cfg.get("threads", 4))
        if self.backend_name == "ncnn":
            self.backend = NcnnBackend(path, threads, vision_cfg.get("ncnn_input", "in0"),
                                       vision_cfg.get("ncnn_output", "out0"))
        else:
            self.backend = OnnxBackend(path, threads)
        self._names_cfg = list(vision_cfg.get("names") or [])
        self.names: list[str] = self._names_cfg
        self.model_path = path
        log.info("detector siap: %s (%s, %d thread)", path.name, self.backend_name, threads)

    def _resolve_names(self, num_classes: int) -> None:
        if self.names and len(self.names) == num_classes:
            return
        if self._names_cfg and len(self._names_cfg) != num_classes:
            log.warning("jumlah vision.names (%d) != kelas model (%d)", len(self._names_cfg), num_classes)
        if num_classes == 80 and not self._names_cfg:
            self.names = COCO_NAMES
        elif not self._names_cfg:
            self.names = [str(i) for i in range(num_classes)]

    def detect(self, img: np.ndarray, conf: float, iou: float) -> tuple[list[dict], dict[str, float]]:
        t0 = time.perf_counter()
        lb, ratio, pad = letterbox(img, self.imgsz)
        blob = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        blob = np.ascontiguousarray(blob)
        t1 = time.perf_counter()
        pred = self.backend.infer(blob)
        t2 = time.perf_counter()
        self._resolve_names(pred.shape[-1] - 5)
        dets = postprocess(pred, conf, iou, ratio, pad, img.shape[:2], self.names)
        t3 = time.perf_counter()
        return dets, {"letterbox": (t1 - t0) * 1000, "infer": (t2 - t1) * 1000, "nms": (t3 - t2) * 1000}


def draw_detections(img: np.ndarray, dets: list[dict], targets: set[str] | None = None) -> np.ndarray:
    for d in dets:
        x1, y1, x2, y2 = d["box"]
        hot = targets is None or not targets or d["label"] in targets
        color = (0, 0, 255) if hot else (0, 200, 255)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        text = f"{d['label']} {d['conf']:.2f}"
        cv2.putText(img, text, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return img
