import numpy as np
import pytest

from guardian.ingest.stream_reader import extract_jpegs
from guardian.vision.detector import letterbox, nms, postprocess
from guardian.vision.preprocess import PreprocessConfig, Preprocessor
from guardian.vision.temporal import TemporalFilter
from guardian.vision.camera_presets import validate_sensor


def test_letterbox_shape_and_pad():
    img = np.zeros((240, 320, 3), np.uint8)
    out, r, (px, py) = letterbox(img, 320)
    assert out.shape == (320, 320, 3)
    assert r == pytest.approx(1.0)
    assert px == 0 and py == 40


def test_nms_suppresses_overlap():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 10, 10], [50, 50, 60, 60]], float)
    scores = np.array([0.9, 0.8, 0.7])
    assert sorted(nms(boxes, scores, 0.5)) == [0, 2]


def test_postprocess_scales_back():
    # satu kotak di tengah input 320 (frame 320x240 -> pad y 40)
    pred = np.zeros((1, 3, 7), np.float32)
    pred[0, 0] = [160, 160, 40, 40, 0.9, 0.1, 0.95]   # kelas 1
    pred[0, 1] = [160, 160, 42, 42, 0.8, 0.1, 0.90]   # duplikat -> NMS
    pred[0, 2] = [10, 10, 5, 5, 0.1, 0.9, 0.1]        # obj rendah -> dibuang
    dets = postprocess(pred, 0.45, 0.45, 1.0, (0, 40), (240, 320), ["a", "knife"])
    assert len(dets) == 1
    d = dets[0]
    assert d["label"] == "knife"
    assert d["box"] == [140, 100, 180, 140]


def test_preprocess_identity_and_ops():
    img = np.full((240, 320, 3), 100, np.uint8)
    p = Preprocessor(PreprocessConfig())
    assert np.array_equal(p.apply(img), img)
    p.set_config(PreprocessConfig.from_dict({"brightness": 20, "rotate": 90, "clahe": True, "sharpen": 0.5}))
    out = p.apply(img)
    assert out.shape == (320, 240, 3)
    p.set_config(PreprocessConfig.from_dict({"roi": [0.5, 0.5, 0.5, 0.5]}))
    assert p.apply(img).shape == (120, 160, 3)


def test_preprocess_validation():
    c = PreprocessConfig.from_dict({"contrast": 9, "gamma": 0.1})
    assert c.contrast == 2.0 and c.gamma == 0.5
    with pytest.raises(ValueError):
        PreprocessConfig.from_dict({"rotate": 45})
    assert PreprocessConfig.from_dict({"roi": None}).is_geometric_identity


def test_temporal_n_of_m():
    tf = TemporalFilter(3, 5)
    hit = [{"label": "knife", "conf": 0.8, "box": [0, 0, 1, 1]}]
    results = [tf.update(d, {"knife"}, 0.5)[0] for d in (hit, [], hit, [], hit)]
    assert results == [False, False, False, False, True]
    tf.reset()
    assert tf.update(hit, {"knife"}, 0.9)[0] is False  # conf di bawah ambang


def test_extract_jpegs_partial():
    buf = bytearray(b"--b\r\n\xff\xd8abc\xff\xd9\r\n--b\r\n\xff\xd8de")
    frames = extract_jpegs(buf)
    assert frames == [b"\xff\xd8abc\xff\xd9"]
    buf.extend(b"f\xff\xd9")
    assert extract_jpegs(buf) == [b"\xff\xd8def\xff\xd9"]


def test_validate_sensor():
    ok, err = validate_sensor({"brightness": 1, "quality": 99, "framesize": "vga", "vflip": True, "x": 1})
    assert ok == {"brightness": 1, "framesize": "VGA", "vflip": 1}
    assert set(err) == {"quality", "x"}
