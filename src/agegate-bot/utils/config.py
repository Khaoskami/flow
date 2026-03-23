"""Dataclass-based environment configuration with validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Immutable application configuration loaded from environment variables."""

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

    # Paths
    data_dir: Path = field(default_factory=lambda: Path("data"))

    @classmethod
    def from_env(cls, env_path: str | None = None) -> Config:
        """Load configuration from environment variables.

        Args:
            env_path: Optional path to .env file. Defaults to .env in cwd.

        Returns:
            Validated Config instance.

        Raises:
            ValueError: If DISCORD_TOKEN is missing.
        """
        load_dotenv(env_path or ".env")

        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_TOKEN environment variable is required")

        return cls(
            discord_token=token,
            bot_prefix=os.getenv("BOT_PREFIX", "!"),
            verified_role=os.getenv("VERIFIED_ROLE", "Verified 18+"),
            verify_channel=os.getenv("VERIFY_CHANNEL", "age-verification"),
            log_channel=os.getenv("LOG_CHANNEL", "verification-logs"),
            min_age=int(os.getenv("MIN_AGE", "18")),
            encryption_key=os.getenv("ENCRYPTION_KEY", ""),
            retention_hours=int(os.getenv("RETENTION_HOURS", "24")),
            tamper_threshold=float(os.getenv("TAMPER_THRESHOLD", "0.60")),
            ocr_confidence=float(os.getenv("OCR_CONFIDENCE", "0.35")),
            max_attempts=int(os.getenv("MAX_ATTEMPTS", "3")),
            cooldown_minutes=int(os.getenv("COOLDOWN_MINUTES", "10")),
            web_host=os.getenv("WEB_HOST", "0.0.0.0"),
            web_port=int(os.getenv("WEB_PORT", "8080")),
            web_secret=os.getenv("WEB_SECRET", ""),
            web_base_url=os.getenv("WEB_BASE_URL", "http://localhost:8080"),
            api_master_key=os.getenv("API_MASTER_KEY", ""),
            org_name=os.getenv("ORG_NAME", "AgeGate Verification Services"),
            legal_contact_email=os.getenv(
                "LEGAL_CONTACT_EMAIL", "legal@example.com"
            ),
            data_dir=Path(os.getenv("DATA_DIR", "data")),
        )
