#!/usr/bin/env bash
# Setup pocket device di Orange Pi Zero 2W (jalankan dari folder sbc/):
#   bash deploy/setup_pi.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== paket sistem =="
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev mosquitto mosquitto-clients alsa-utils i2c-tools \
  libgpiod-dev gpiod

echo "== grup akses hardware =="
for g in gpio i2c dialout audio; do
  getent group "$g" >/dev/null || sudo groupadd "$g"
  sudo usermod -aG "$g" "$USER"
done

echo "== mosquitto =="
sudo install -m 644 deploy/mosquitto-guardian.conf /etc/mosquitto/conf.d/guardian.conf
sudo systemctl enable --now mosquitto
sudo systemctl restart mosquitto || echo "!! mosquitto gagal restart: pastikan wlan0 sudah 192.168.50.1 (AP) atau hapus listener kedua"

echo "== venv + dependensi =="
python3 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt

echo "== aset =="
.venv/bin/python tools/make_sounds.py
.venv/bin/python tools/make_icons.py
mkdir -p data models
[ -f .env ] || { cp .env.example .env; echo "!! isi .env (python tools/hash_password.py)"; }

echo "== izin shutdown =="
sudo visudo -cf deploy/guardian-shutdown.sudoers && \
  sudo install -m 440 deploy/guardian-shutdown.sudoers /etc/sudoers.d/guardian-shutdown

echo "== aturan udev agar grup gpio/i2c bisa akses perangkat =="
sudo tee /etc/udev/rules.d/60-guardian.rules >/dev/null <<'EOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"
SUBSYSTEM=="i2c-dev", GROUP="i2c", MODE="0660"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "== service =="
sudo install -m 644 systemd/guardian.service /etc/systemd/system/guardian.service
sudo systemctl daemon-reload
echo "Selesai. Verifikasi pin di config.yaml, lalu: sudo systemctl enable --now guardian"
echo "Logout/login ulang agar keanggotaan grup berlaku."
