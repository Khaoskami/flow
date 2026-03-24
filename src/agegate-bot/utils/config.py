"""Dataclass-based configuration loaded from environment variables."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    # Required
    discord_token: str

    # Bot settings
    bot_prefix: str = "!"
    verified_role: str = "Verified 18+"
    verify_channel: str = "age-verification"
    log_channel: str = "verification-logs"
    min_age: int = 18

    # Security
    encryption_key: str = ""
    retention_hours: int = 24

    # Analysis tuning
    tamper_threshold: float = 0.60
    ocr_confidence: float = 0.35
    max_attempts: int = 3
    cooldown_minutes: int = 10

    # Web dashboard
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    web_secret: str = ""
    web_base_url: str = "http://localhost:8080"
    api_master_key: str = ""

    # Legal document
    org_name: str = "AgeGate Verification Services"
    legal_contact_email: str = "legal@example.com"

    @classmethod
    def from_env(cls) -> Config:
        load_dotenv()

        token = os.getenv("DISCORD_TOKEN", "")
        if not token:
            raise RuntimeError("DISCORD_TOKEN is required — set it in .env")

        enc_key = os.getenv("ENCRYPTION_KEY", "").strip()
        # Always validate the key — generate a fresh one if missing or invalid
        from cryptography.fernet import Fernet

        try:
            if enc_key:
                Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)
            else:
                raise ValueError("empty")
        except (ValueError, Exception):
            enc_key = Fernet.generate_key().decode()
            print(
                "[config] WARNING: ENCRYPTION_KEY missing or invalid — generated ephemeral key. "
                "Temp records will be lost on restart."
            )

        web_secret = os.getenv("WEB_SECRET", "")
        if not web_secret:
            web_secret = secrets.token_hex(32)
            print("[config] WARNING: No WEB_SECRET set — generated ephemeral session key.")

        return cls(
            discord_token=token,
            bot_prefix=os.getenv("BOT_PREFIX", "!"),
            verified_role=os.getenv("VERIFIED_ROLE", "Verified 18+"),
            verify_channel=os.getenv("VERIFY_CHANNEL", "age-verification"),
            log_channel=os.getenv("LOG_CHANNEL", "verification-logs"),
            min_age=int(os.getenv("MIN_AGE", "18")),
            encryption_key=enc_key,
            retention_hours=int(os.getenv("RETENTION_HOURS", "24")),
            tamper_threshold=float(os.getenv("TAMPER_THRESHOLD", "0.60")),
            ocr_confidence=float(os.getenv("OCR_CONFIDENCE", "0.35")),
            max_attempts=int(os.getenv("MAX_ATTEMPTS", "3")),
            cooldown_minutes=int(os.getenv("COOLDOWN_MINUTES", "10")),
            web_host=os.getenv("WEB_HOST", "0.0.0.0"),
            web_port=int(os.getenv("WEB_PORT", "8080")),
            web_secret=web_secret,
            web_base_url=os.getenv("WEB_BASE_URL", "http://localhost:8080"),
            api_master_key=os.getenv("API_MASTER_KEY", ""),
            org_name=os.getenv("ORG_NAME", "AgeGate Verification Services"),
            legal_contact_email=os.getenv("LEGAL_CONTACT_EMAIL", "legal@example.com"),
        )
