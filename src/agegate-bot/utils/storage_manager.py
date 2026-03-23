"""Fernet-encrypted temporary storage for ID analysis records."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet


class StorageManager:
    """Manages encrypted temporary files with automatic expiry.

    Each verification analysis result is stored as a Fernet-encrypted JSON
    blob. Files are automatically deleted after the retention period.
    Raw images are NEVER stored.
    """

    def __init__(
        self,
        storage_dir: str | Path = "data/verifications",
        encryption_key: str = "",
        retention_hours: int = 24,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = retention_hours * 3600

        if encryption_key:
            self._fernet = Fernet(encryption_key.encode())
        else:
            self._fernet = Fernet(Fernet.generate_key())

    def store(self, record_id: str, data: dict) -> Path:
        """Encrypt and store analysis data.

        Args:
            record_id: Unique identifier for the record.
            data: Analysis result dictionary (no raw image data).

        Returns:
            Path to the encrypted file.
        """
        payload = json.dumps(data).encode("utf-8")
        encrypted = self._fernet.encrypt(payload)
        filepath = self.storage_dir / f"{record_id}.enc"
        filepath.write_bytes(encrypted)
        return filepath

    def retrieve(self, record_id: str) -> dict | None:
        """Decrypt and return stored analysis data.

        Returns:
            Decrypted dict or None if not found / expired.
        """
        filepath = self.storage_dir / f"{record_id}.enc"
        if not filepath.exists():
            return None

        age = time.time() - filepath.stat().st_mtime
        if age > self.retention_seconds:
            filepath.unlink(missing_ok=True)
            return None

        try:
            encrypted = filepath.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            return json.loads(decrypted.decode("utf-8"))
        except Exception:
            return None

    def delete(self, record_id: str) -> bool:
        """Delete a specific record."""
        filepath = self.storage_dir / f"{record_id}.enc"
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def cleanup_expired(self) -> int:
        """Delete all records older than the retention period.

        Returns:
            Number of files deleted.
        """
        deleted = 0
        now = time.time()
        for filepath in self.storage_dir.glob("*.enc"):
            age = now - filepath.stat().st_mtime
            if age > self.retention_seconds:
                filepath.unlink(missing_ok=True)
                deleted += 1
        return deleted

    def purge_user(self, record_id: str) -> bool:
        """GDPR purge — delete a specific user's temp record."""
        return self.delete(record_id)
