"""Fernet-encrypted temporary storage for ID analysis records. Auto-purged after retention window."""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from cryptography.fernet import Fernet

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "verifications")


class StorageManager:
    def __init__(self, encryption_key: str, retention_hours: int = 24) -> None:
        self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        self._retention_seconds = retention_hours * 3600
        os.makedirs(STORAGE_DIR, exist_ok=True)

    def save(self, record_id: str, data: dict) -> str:
        payload = json.dumps({"ts": time.time(), "data": data}).encode()
        encrypted = self._fernet.encrypt(payload)
        path = os.path.join(STORAGE_DIR, f"{record_id}.enc")
        with open(path, "wb") as f:
            f.write(encrypted)
        return path

    def load(self, record_id: str) -> Optional[dict]:
        path = os.path.join(STORAGE_DIR, f"{record_id}.enc")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                encrypted = f.read()
            payload = json.loads(self._fernet.decrypt(encrypted))
            if time.time() - payload["ts"] > self._retention_seconds:
                os.remove(path)
                return None
            return payload["data"]
        except Exception:
            return None

    def delete(self, record_id: str) -> bool:
        path = os.path.join(STORAGE_DIR, f"{record_id}.enc")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def purge_expired(self) -> int:
        count = 0
        now = time.time()
        for fname in os.listdir(STORAGE_DIR):
            if not fname.endswith(".enc"):
                continue
            path = os.path.join(STORAGE_DIR, fname)
            try:
                with open(path, "rb") as f:
                    encrypted = f.read()
                payload = json.loads(self._fernet.decrypt(encrypted))
                if now - payload["ts"] > self._retention_seconds:
                    os.remove(path)
                    count += 1
            except Exception:
                # Corrupted or unreadable — remove
                os.remove(path)
                count += 1
        return count
