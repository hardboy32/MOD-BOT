"""Tenant accounts and isolated, encrypted per-user configuration storage."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class TenantStoreError(Exception):
    pass


class EmailAlreadyExists(TenantStoreError):
    pass


class InvalidCredentials(TenantStoreError):
    pass


class TenantStore:
    """Small SQLite store. Chat message bodies are deliberately never accepted here."""

    def __init__(self, database_path: str | None = None, encryption_key: str | None = None):
        self.database_path = database_path or os.getenv("DATABASE_PATH", "data/modbot.sqlite3")
        key = encryption_key or os.getenv("TENANT_ENCRYPTION_KEY", "")
        if not key:
            raise RuntimeError("TENANT_ENCRYPTION_KEY is required for the multi-user dashboard")
        try:
            self.fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise RuntimeError("TENANT_ENCRYPTION_KEY must be a valid Fernet key") from exc
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.database_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _initialize(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    created_at INTEGER NOT NULL,
                    subscription_status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS tenant_settings (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    encrypted_payload BLOB NOT NULL,
                    updated_at INTEGER NOT NULL
                );
            """)

    @staticmethod
    def _password(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)

    def create_user(self, email: str, password: str) -> str:
        email = email.strip().casefold()
        if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Enter a valid email address")
        if len(password) < 12 or len(password) > 256:
            raise ValueError("Password must be 12–256 characters")
        salt = secrets.token_bytes(16)
        digest = self._password(password, salt)
        user_id = str(uuid.uuid4())
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO users(id,email,password_salt,password_hash,created_at) VALUES(?,?,?,?,?)",
                    (user_id, email, salt, digest, int(time.time())),
                )
        except sqlite3.IntegrityError as exc:
            raise EmailAlreadyExists("An account with this email already exists") from exc
        return user_id

    def authenticate(self, email: str, password: str) -> str:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE email = ?", (email.strip().casefold(),)).fetchone()
        if row is None:
            raise InvalidCredentials("Email or password is incorrect")
        candidate = self._password(password, row["password_salt"])
        if not hmac.compare_digest(candidate, row["password_hash"]):
            raise InvalidCredentials("Email or password is incorrect")
        return str(row["id"])

    def create_session(self, user_id: str, lifetime_seconds: int = 7 * 24 * 3600) -> tuple[str, str]:
        token = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
            db.execute(
                "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES(?,?,?,?)",
                (token_hash, user_id, csrf, int(time.time()) + lifetime_seconds),
            )
        return token, csrf

    def get_session(self, token: str | None) -> dict[str, str] | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connect() as db:
            row = db.execute(
                "SELECT s.user_id,s.csrf_token,u.email FROM sessions s "
                "JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
                (token_hash, int(time.time())),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def save_settings(self, user_id: str, settings: dict[str, Any]) -> None:
        raw = json.dumps(settings, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self.fernet.encrypt(raw)
        with self._connect() as db:
            db.execute(
                "INSERT INTO tenant_settings(user_id,encrypted_payload,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET encrypted_payload=excluded.encrypted_payload, "
                "updated_at=excluded.updated_at",
                (user_id, encrypted, int(time.time())),
            )

    def get_settings(self, user_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT encrypted_payload FROM tenant_settings WHERE user_id=?", (user_id,)
            ).fetchone()
        if row is None:
            return {}
        try:
            return json.loads(self.fernet.decrypt(row["encrypted_payload"]).decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise TenantStoreError("Could not decrypt this account's settings") from exc
