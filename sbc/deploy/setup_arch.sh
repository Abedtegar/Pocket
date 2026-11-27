#!/usr/bin/env bash
# Setup pocket device di Orange Pi OS (Arch Linux ARM). Jalankan dari mana saja:
#   bash deploy/setup_arch.sh
# Padanan deploy/setup_pi.sh (Debian/apt). Aman dijalankan ulang.
set -euo pipefail
cd "$(dirname "$0")/.."
SBC_DIR="$(pwd)"
RUN_USER="${SUDO_USER:-$USER}"

echo "== paket sistem (pacman) =="
sudo pacman -S --needed --noconfirm python mosquitto alsa-utils i2c-tools libgpiod

echo "== grup akses hardware =="
# Arch: port serial dimiliki grup 'uucp' (bukan 'dialout'); gpio/i2c dibuat sendiri.
for g in gpio i2c; do getent group "$g" >/dev/null || sudo groupadd --system "$g"; done
for g in gpio i2c uucp audio; do sudo usermod -aG "$g" "$RUN_USER"; done

echo "== aturan udev (gpio/i2c) =="
sudo tee /etc/udev/rules.d/60-guardian.rules >/dev/null <<'EOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"
SUBSYSTEM=="i2c-dev", GROUP="i2c", MODE="0660"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "== mosquitto =="
sudo install -d -m 755 /etc/mosquitto/conf.d
sudo install -d -o mosquitto -g mosquitto -m 755 /var/lib/mosquitto
# mosquitto.conf bawaan Arch tidak membaca conf.d
grep -q '^include_dir /etc/mosquitto/conf.d' /etc/mosquitto/mosquitto.conf 2>/dev/null || \
  echo 'include_dir /etc/mosquitto/conf.d' | sudo tee -a /etc/mosquitto/mosquitto.conf >/dev/null
{
  echo "# dibuat oleh deploy/setup_arch.sh (sumber: deploy/mosquitto-guardian.conf)"
  echo "listener 1883 127.0.0.1"
  if ip -4 addr show | grep -q 'inet 192\.168\.50\.1/'; then
    echo "listener 1883 192.168.50.1"
  else
    echo "# listener 1883 192.168.50.1   # AP belum aktif; aktifkan baris ini setelah wlan0 = 192.168.50.1"
    echo "!! AP 192.168.50.1 belum ada: mosquitto hanya mendengar 127.0.0.1" >&2
  fi
  echo "allow_anonymous true"
  echo "persistence true"
  echo "persistence_location /var/lib/mosquitto/"
} | sudo tee /etc/mosquitto/conf.d/guardian.conf >/dev/null
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

echo "== venv + dependensi =="
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip wheel
.venv/bin/pip install -q -r requirements.txt

echo "== aset =="
.venv/bin/python tools/make_sounds.py
.venv/bin/python tools/make_icons.py
mkdir -p data models
[ -f .env ] || { cp .env.example .env; echo "!! isi .env (python tools/hash_password.py)"; }

echo "== izin shutdown =="
TMP_SUDOERS="$(mktemp)"
sed "s/^orangepi /$RUN_USER /" deploy/guardian-shutdown.sudoers > "$TMP_SUDOERS"
sudo visudo -cf "$TMP_SUDOERS" && sudo install -m 440 "$TMP_SUDOERS" /etc/sudoers.d/guardian-shutdown
rm -f "$TMP_SUDOERS"

echo "== service =="
sed -e "s|^User=orangepi|User=$RUN_USER|" \
    -e "s|/home/orangepi/guardian/sbc|$SBC_DIR|g" \
    -e "s|SupplementaryGroups=.*|SupplementaryGroups=gpio i2c uucp audio|" \
    systemd/guardian.service | sudo tee /etc/systemd/system/guardian.service >/dev/null
sudo systemctl daemon-reload

echo
echo "Selesai. Langkah berikutnya:"
echo "  1. Logout/login ulang (atau reboot) agar keanggotaan grup berlaku."
echo "  2. Isi .env, verifikasi nilai VERIFIKASI di config.yaml."
echo "  3. sudo systemctl enable --now guardian ; journalctl -u guardian -f"
