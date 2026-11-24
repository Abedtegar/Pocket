# models/

Taruh model hasil ekspor di sini (tidak masuk git).

- ONNX: `yolov5n_weapon.onnx` (set `vision.model` di `config.yaml`)
- NCNN: folder berisi `*.param` + `*.bin` (set `vision.backend: ncnn`, `vision.model: models/<folder>`,
  dan sesuaikan `ncnn_input` / `ncnn_output` dengan nama blob hasil konversi)

## Uji pipeline dengan model COCO (M5)
Di PC/Colab:
```bash
git clone https://github.com/ultralytics/yolov5 && cd yolov5
pip install -r requirements.txt
python export.py --weights yolov5n.pt --include onnx --img 320 --opset 12 --simplify
```
Salin `yolov5n.onnx` ke `sbc/models/`, lalu di `config.yaml`:
```yaml
vision:
  model: models/yolov5n.onnx
  names: []          # 80 kelas -> nama COCO otomatis
  classes: [knife]   # atau [scissors, knife] untuk uji
```
