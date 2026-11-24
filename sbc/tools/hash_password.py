"""Buat hash bcrypt untuk WEB_PASSWORD_HASH dan SESSION_SECRET acak untuk .env.

    python tools/hash_password.py
"""
import getpass
import secrets

import bcrypt

pw = getpass.getpass("Password web: ")
if pw != getpass.getpass("Ulangi: "):
    raise SystemExit("password tidak sama")
print("\nTambahkan ke .env (kutip tunggal penting karena hash mengandung '$'):")
print(f"WEB_PASSWORD_HASH='{bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()}'")
print(f"SESSION_SECRET={secrets.token_urlsafe(48)}")
