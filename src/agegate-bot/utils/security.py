"""Central security utilities — key hashing, field encryption, IP scrubbing, sanitization."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Optional

from cryptography.fernet import Fernet


# ── API Key Hashing ────────────────────────────────────────────
# API keys are stored as SHA-256 hashes in the database.
# The plaintext key is shown to the user once and never stored.

def hash_api_key(key: str) -> str:
    """Hash an API key for storage. One-way — cannot be reversed."""
    return hashlib.sha256(key.encode()).hexdigest()


def verify_api_key(provided: str, stored_hash: str) -> bool:
    """Constant-time comparison of a provided key against a stored hash."""
    provided_hash = hashlib.sha256(provided.encode()).hexdigest()
    return hmac.compare_digest(provided_hash, stored_hash)


# ── Field-Level Encryption ─────────────────────────────────────
# Encrypts sensitive values (DOB, age) at the field level before DB storage.
# Uses the same Fernet key as temp storage.

class FieldEncryptor:
    """Encrypts/decrypts individual field values for database storage."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, value: str) -> str:
        """Encrypt a string value. Returns base64-encoded ciphertext."""
        if not value:
            return ""
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt a base64-encoded ciphertext. Returns plaintext string."""
        if not token:
            return ""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except Exception:
            return "[ENCRYPTED]"

    def encrypt_int(self, value: Optional[int]) -> Optional[str]:
        """Encrypt an integer value."""
        if value is None:
            return None
        return self.encrypt(str(value))

    def decrypt_int(self, token: Optional[str]) -> Optional[int]:
        """Decrypt to an integer."""
        if not token:
            return None
        try:
            return int(self.decrypt(token))
        except (ValueError, Exception):
            return None


# ── IP Scrubbing ─────────────────────────────────────────────────

def scrub_ip(ip: Optional[str]) -> Optional[str]:
    """Remove or anonymize an IP address. Returns None — we don't store IPs."""
    return None


def scrub_headers(headers: dict) -> dict:
    """Remove IP-leaking headers from a request before logging."""
    sensitive = {
        "x-forwarded-for", "x-real-ip", "cf-connecting-ip", "true-client-ip",
        "x-client-ip", "forwarded", "x-forwarded", "via", "x-originating-ip",
        "x-remote-ip", "x-remote-addr", "remote-addr",
    }
    return {k: v for k, v in headers.items() if k.lower() not in sensitive}


# ── Input Sanitization ───────────────────────────────────────────

def sanitize_input(text: str, max_length: int = 200) -> str:
    """Sanitize user input — strip control chars, limit length."""
    # Remove null bytes and control characters
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Strip whitespace
    cleaned = cleaned.strip()
    # Limit length
    return cleaned[:max_length]


def sanitize_search_query(query: str) -> str:
    """Sanitize a search query — prevent SQL wildcard abuse."""
    cleaned = sanitize_input(query, max_length=100)
    # Escape SQL LIKE wildcards
    cleaned = cleaned.replace("%", "").replace("_", "").replace("\\", "")
    return cleaned


# ── Redaction ─────────────────────────────────────────────────────

def redact_hash(h: Optional[str], visible: int = 8) -> str:
    """Show only the first N chars of a hash."""
    if not h:
        return "—"
    return f"{h[:visible]}…"


def redact_id(user_id: int) -> str:
    """Partially redact a user ID for logs. Shows first 4 and last 2 digits."""
    s = str(user_id)
    if len(s) <= 6:
        return s
    return f"{s[:4]}…{s[-2:]}"


# ── Timing-Safe Comparison ────────────────────────────────────────

def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())
