"""Vercel serverless entry point for the AgeGate web dashboard."""

from __future__ import annotations

import os
import sys

# Add parent directory to path so imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import Config
from utils.database import Database
from utils.security import FieldEncryptor
from web.app import create_app

# Build a lightweight config from environment variables (no DISCORD_TOKEN required for web-only)
_enc_key = os.getenv("ENCRYPTION_KEY", "")
if _enc_key:
    try:
        from cryptography.fernet import Fernet
        Fernet(_enc_key.encode())
    except Exception:
        _enc_key = ""

if not _enc_key:
    from cryptography.fernet import Fernet
    _enc_key = Fernet.generate_key().decode()

_field_enc = FieldEncryptor(_enc_key)
_database = Database(field_encryptor=_field_enc)

_secret = os.getenv("WEB_SECRET", "agegate-vercel-secret")
_master_key = os.getenv("API_MASTER_KEY", "")

app = create_app(_database, secret_key=_secret, master_api_key=_master_key)


@app.on_event("startup")
async def _connect_db():
    await _database.connect()
