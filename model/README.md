# Training model senjata tajam (M8)

Keputusan: YOLOv5n 320 (K1), **satu kelas `senjata_tajam`** (K13), training di **Google Colab**, tahap 1 dengan
**data publik** lalu tahap 2 fine-tune dengan data primer kacamata (K14, plan 9.1).

| File | Isi |
|---|---|
| `train.ipynb` | notebook Colab: unduh dataset → gabung 1 kelas → negatif COCO → train → evaluasi → ekspor ONNX |
| `data.yaml` | definisi kelas (nc 1) |

---

## Tahap 1 — model awal dari data publik

### 1. Siapkan akun
- Google Drive (hasil disimpan di `MyDrive/guardian/`).
- Akun Roboflow (gratis): *Settings → API Keys*, salin **Private API Key**.

### 2. Pilih dataset di Roboflow Universe
Cari *knife*, *sickle*, *machete*, *scissors*, *sharp weapon*. Kriteria:
- tipe **Object Detection** (bounding box), bukan klasifikasi;
- gambar beragam (orang memegang benda, jalan, ruangan), bukan katalog benda di latar putih;
- jumlah ≥ beberapa ratus gambar, label terlihat rapi di preview;
- lisensi jelas (CC BY 4.0 / Public Domain paling aman).

Target awal: total **≥ 2.000 gambar positif** dari 2–5 dataset, dengan pisau dominan dan sedikit celurit/parang/gunting.
Catat setiap dataset di tabel **Sumber data** di bawah.

### 3. Jalankan notebook
1. Buka https://colab.research.google.com → *Upload* → `model/train.ipynb`.
2. *Runtime → Change runtime type → T4 GPU*.
3. Panel 🔑 *Secrets*: tambah `ROBOFLOW_API_KEY`, aktifkan akses notebook.
4. Isi `DATASETS` di sel 2, mis. `dict(workspace='abc', project='knife-detection-xyz', version=3, keep=['knife'])`.
   `keep` = nama kelas yang dianggap senjata tajam. Kelas lain, misalnya `gun`, dibuang.
5. Jalankan sel berurutan. Di sel **3c**, periksa gambar sampel: kotak harus rapat di benda.
6. Training sekitar 1–3 jam. Kalau Colab terputus, jalankan sel 0, 1, lalu **5b** (resume).

### 4. Baca hasil (sel 6)
| Metrik | Arti | Patokan tahap 1 |
|---|---|---|
| P (precision) | dari semua deteksi, berapa yang benar | ≥ 0.7 |
| R (recall) | dari semua senjata, berapa yang terdeteksi | ≥ 0.7, **lebih penting** |
| mAP50 | ringkasan akurasi | ≥ 0.7 |

Patokan ini hanya untuk validation set data publik. Angka di kamera kacamata akan lebih rendah, dan itu
yang diperbaiki di tahap 2.

### 5. Pasang di Orange Pi
Unduh `MyDrive/guardian/yolov5n_weapon.onnx` ke laptop, lalu:
```bash
scp yolov5n_weapon.onnx teen@guardian.local:~/Pocket/sbc/models/
```
Di Orange Pi (`config.yaml` sudah diset `names/classes: [senjata_tajam]`):
```bash
cd ~/Pocket/sbc
.venv/bin/python tools/bench_detector.py --model models/yolov5n_weapon.onnx   # catat FPS + latensi (K2, K4)
.venv/bin/python -m guardian                                                    # uji langsung dengan kacamata
```
Tunjukkan benda (aman, mata ditumpulkan) ke kacamata, pantau `http://guardian.local:8000`. Catat jarak
maksimum yang masih terdeteksi dan false positive (ponsel, sendok, dll) di `docs/PROGRESS.md`.
Ubah `vision.conf` dari web bila perlu.

---

## Tahap 2: fine-tune dengan data primer kacamata (plan 9A)
1. **Rekam**: tombol *Rekam dataset* di tab Kamera, atau `tools/record_session.py` (service dihentikan dulu).
   Gunakan **preset kamera yang sama** dengan operasi. Hasilnya disimpan di `sbc/dataset_raw/Sxxx_.../frames/`.
2. **Seleksi frame**: ambil 1 dari tiap 10 frame, buang yang mirip atau blur (plan 9A.8).
3. **Label** di Roboflow/CVAT dengan kelas rinci `pisau, celurit, parang_golok, gunting, lainnya_tajam`.
   Gambar negatif dibiarkan tanpa kotak (plan 9A.9).
4. **Bagi per sesi**: sesi test (≥ 3) tidak pernah dipakai training.
5. Tambahkan ke `DATASETS`. Di proyek Roboflow sendiri, `keep=None` membuat semua kelas rinci digabung ke 0.
   Latih dari `best.pt` tahap 1 (`--weights .../weapon_v5n_s1/weights/best.pt`, sekitar 50–100 epoch).
6. Pilih `vision.conf` dari kurva PR **di test set primer**, utamakan recall.

Saat ini notebook baru mendukung tahap 1. Skrip seleksi frame dan split per sesi untuk tahap 2 dibuat setelah
data primer ada.

---

## Sumber data (isi setiap kali menambah dataset)
| Dataset (workspace/project/version) | Jumlah gambar | Kelas dipakai | Lisensi | URL |
|---|---|---|---|---|
| COCO 2017 val (negatif sulit) | ≤ 1.500 | – (label kosong) | CC BY 4.0 | https://cocodataset.org |

> YOLOv5 berlisensi AGPL-3.0: aman untuk riset/lomba, tinjau ulang bila dikomersialkan.
> Dataset tidak disimpan di git, hanya di Google Drive.
