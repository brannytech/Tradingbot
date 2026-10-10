"""Loopback application auth. Secrets stay in backend environment variables."""
import hashlib
import hmac
import os
import secrets
import time
import threading
from dataclasses import dataclass, field


@dataclass
class Config:
    environment: str = "paper"
    password: str = field(default="", repr=False)
    demo_key: str = field(default="", repr=False)
    demo_secret: str = field(default="", repr=False)
    port: int = 8765

    def __post_init__(self):
        if self.environment not in ("paper", "demo"):
            raise ValueError("Live mode is locked: readiness process incomplete")
        if self.password and len(self.password) < 12:
            raise ValueError("TRADINGBOT_PASSWORD must contain at least 12 characters")

    @classmethod
    def from_env(cls):
        return cls(os.getenv("TRADINGBOT_ENV", "paper"), os.getenv("TRADINGBOT_PASSWORD", ""),
                   os.getenv("BYBIT_DEMO_KEY", ""), os.getenv("BYBIT_DEMO_SECRET", ""),
                   int(os.getenv("TRADINGBOT_PORT", "8765")))


class Auth:
    def __init__(self, password, lifetime=3600):
        self.salt = secrets.token_bytes(32)
        self.digest = self._hash(password) if password else None
        self.lifetime = lifetime
        self.sessions = {}
        self.failures = {}
        self.lock = threading.Lock()

    def _hash(self, password):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), self.salt, 200_000)

    def configure(self, password):
        with self.lock:
            if self.digest is not None or not isinstance(password,str) or len(password)<12:
                raise ValueError("Setup unavailable or password too short")
            self.digest=self._hash(password)
            return dict(salt=self.salt.hex(),digest=self.digest.hex())

    def restore(self,record):
        self.salt=bytes.fromhex(record["salt"])
        self.digest=bytes.fromhex(record["digest"])

    def login(self, password, client):
        with self.lock:
            now = time.time()
            failed = [x for x in self.failures.get(client, []) if now-x < 60]
            self.failures[client] = failed
            if len(failed) >= 5:
                return None
            if self.digest is None or not hmac.compare_digest(self.digest, self._hash(password)):
                failed.append(now)
                return None
            self.failures.pop(client, None)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions[token] = (now+self.lifetime, csrf)
            return token, csrf

    def check(self, token, csrf=None, write=False):
        with self.lock:
            session = self.sessions.get(token)
            if not session or session[0] <= time.time():
                self.sessions.pop(token, None)
                return False
            return not write or (isinstance(csrf, str) and hmac.compare_digest(session[1], csrf))

    def session_csrf(self, token):
        with self.lock:
            session = self.sessions.get(token)
            if not session or session[0] <= time.time():
                self.sessions.pop(token, None)
                return None
            return session[1]

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token, None)
