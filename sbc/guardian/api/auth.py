"""Login sederhana: satu password (hash bcrypt di .env), sesi berupa cookie bertanda tangan."""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

import bcrypt
from fastapi import HTTPException, Request, WebSocket
from itsdangerous import BadSignature, URLSafeTimedSerializer

log = logging.getLogger(__name__)

COOKIE = "guardian_session"
MAX_AGE = 30 * 24 * 3600


class Auth:
    def __init__(self, password_hash: str, secret: str, data_dir: Path):
        self.password_hash = password_hash.strip()
        if not secret:
            f = data_dir / "session_secret"
            data_dir.mkdir(parents=True, exist_ok=True)
            if not f.exists():
                f.write_text(secrets.token_urlsafe(48))
            secret = f.read_text().strip()
        self.serializer = URLSafeTimedSerializer(secret, salt="guardian")
        self.enabled = bool(self.password_hash)
        if not self.enabled:
            log.warning("WEB_PASSWORD_HASH kosong: web TANPA login (isi .env sebelum dipakai di lapangan)")

    def check_password(self, password: str) -> bool:
        if not self.enabled:
            return True
        try:
            return bcrypt.checkpw(password.encode(), self.password_hash.encode())
        except ValueError:
            log.error("WEB_PASSWORD_HASH bukan hash bcrypt yang valid")
            return False

    def make_token(self) -> str:
        return self.serializer.dumps({"u": "user"})

    def valid_token(self, token: str | None) -> bool:
        if not self.enabled:
            return True
        if not token:
            return False
        try:
            self.serializer.loads(token, max_age=MAX_AGE)
            return True
        except BadSignature:
            return False


def require_auth(request: Request) -> None:
    auth: Auth = request.app.state.auth
    if not auth.valid_token(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="login diperlukan")


def ws_authorized(ws: WebSocket) -> bool:
    auth: Auth = ws.app.state.auth
    return auth.valid_token(ws.cookies.get(COOKIE))
