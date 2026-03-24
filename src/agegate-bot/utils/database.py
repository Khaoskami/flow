"""Hardened SQLite database — hashed API keys, encrypted PII, guild-scoped access, no IP storage."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import aiosqlite

from .security import hash_api_key, verify_api_key, FieldEncryptor, sanitize_search_query

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "agegate.db")


class Database:
    def __init__(self, field_encryptor: Optional[FieldEncryptor] = None) -> None:
        self._db: Optional[aiosqlite.Connection] = None
        self._enc = field_encryptor

    async def connect(self) -> None:
        os.makedirs(DB_DIR, exist_ok=True)
        self._db = await aiosqlite.connect(DB_PATH)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._init_tables()
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    def _encrypt_field(self, value: Optional[str]) -> Optional[str]:
        if self._enc and value:
            return self._enc.encrypt(value)
        return value

    def _decrypt_field(self, value: Optional[str]) -> Optional[str]:
        if self._enc and value:
            return self._enc.decrypt(value)
        return value

    def _encrypt_int(self, value: Optional[int]) -> Optional[str]:
        if self._enc and value is not None:
            return self._enc.encrypt_int(value)
        return str(value) if value is not None else None

    def _decrypt_int(self, value) -> Optional[int]:
        if value is None:
            return None
        if self._enc:
            if isinstance(value, int):
                return value
            return self._enc.decrypt_int(value)
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    async def _init_tables(self) -> None:
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS agreements (
                agreement_id  TEXT PRIMARY KEY,
                user_id       INTEGER NOT NULL UNIQUE,
                user_name     TEXT NOT NULL,
                document_text TEXT NOT NULL,
                document_hash TEXT NOT NULL,
                signed_at     TEXT NOT NULL,
                version       INTEGER DEFAULT 1,
                revoked       INTEGER DEFAULT 0,
                revoked_at    TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS verifications (
                verification_id TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL UNIQUE,
                user_name       TEXT NOT NULL,
                verified_at     TEXT NOT NULL,
                age_detected    TEXT,
                dob_extracted   TEXT,
                tamper_score    REAL,
                confidence      REAL,
                image_hash      TEXT,
                flags           TEXT DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS guild_members (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                guild_id      INTEGER NOT NULL,
                guild_name    TEXT NOT NULL,
                joined_at     TEXT NOT NULL,
                role_assigned INTEGER DEFAULT 1,
                UNIQUE(user_id, guild_id)
            );
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id      INTEGER PRIMARY KEY,
                guild_name    TEXT NOT NULL,
                owner_id      INTEGER NOT NULL,
                api_key_hash  TEXT UNIQUE,
                registered_at TEXT NOT NULL,
                webhook_url   TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action    TEXT NOT NULL,
                user_id   INTEGER,
                guild_id  INTEGER,
                details   TEXT,
                actor_id  INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_agreements_user ON agreements(user_id);
            CREATE INDEX IF NOT EXISTS idx_verifications_user ON verifications(user_id);
            CREATE INDEX IF NOT EXISTS idx_guild_members_user ON guild_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_guild_members_guild ON guild_members(guild_id);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_guild ON audit_log(guild_id);
            """
        )
        # Migrate old schema: api_key → api_key_hash
        try:
            cur = await self._db.execute("PRAGMA table_info(guild_settings)")
            columns = [row[1] for row in await cur.fetchall()]
            if "api_key" in columns and "api_key_hash" not in columns:
                await self._db.execute("ALTER TABLE guild_settings RENAME COLUMN api_key TO api_key_hash")
                await self._db.commit()
        except Exception:
            pass

    # ── Agreements ────────────────────────────────────────────────────

    async def save_agreement(self, user_id: int, user_name: str, document_text: str, document_hash: str, version: int = 1) -> str:
        agreement_id = uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT OR REPLACE INTO agreements (agreement_id, user_id, user_name, document_text, document_hash, signed_at, version) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (agreement_id, user_id, user_name, document_text, document_hash, now, version),
        )
        await self._db.commit()
        return agreement_id

    async def get_agreement_by_user(self, user_id: int) -> Optional[dict]:
        cur = await self._db.execute("SELECT * FROM agreements WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_agreement_by_id(self, agreement_id: str) -> Optional[dict]:
        cur = await self._db.execute("SELECT * FROM agreements WHERE agreement_id = ?", (agreement_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def revoke_agreement(self, user_id: int) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        cur = await self._db.execute("UPDATE agreements SET revoked = 1, revoked_at = ? WHERE user_id = ? AND revoked = 0", (now, user_id))
        await self._db.commit()
        return cur.rowcount > 0

    # ── Verifications ─────────────────────────────────────────────────

    async def save_verification(self, user_id: int, user_name: str, age_detected: Optional[int] = None, dob_extracted: Optional[str] = None, tamper_score: Optional[float] = None, confidence: Optional[float] = None, image_hash: Optional[str] = None, flags: Optional[list[str]] = None) -> str:
        vid = uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        enc_age = self._encrypt_int(age_detected)
        enc_dob = self._encrypt_field(dob_extracted)
        await self._db.execute(
            "INSERT OR REPLACE INTO verifications (verification_id, user_id, user_name, verified_at, age_detected, dob_extracted, tamper_score, confidence, image_hash, flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (vid, user_id, user_name, now, enc_age, enc_dob, tamper_score, confidence, image_hash, json.dumps(flags or [])),
        )
        await self._db.commit()
        return vid

    async def get_verification(self, user_id: int) -> Optional[dict]:
        cur = await self._db.execute("SELECT * FROM verifications WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return None
        result = dict(row)
        result["age_detected"] = self._decrypt_int(result.get("age_detected"))
        result["dob_extracted"] = self._decrypt_field(result.get("dob_extracted"))
        return result

    async def get_verification_safe(self, user_id: int) -> Optional[dict]:
        """Verification with PII stripped — safe for dashboard display."""
        v = await self.get_verification(user_id)
        if not v:
            return None
        return {
            "verification_id": v["verification_id"],
            "user_id": v["user_id"],
            "user_name": v["user_name"],
            "verified_at": v["verified_at"],
            "is_verified": True,
            "is_adult": v.get("age_detected") is not None and v["age_detected"] >= 18,
            "tamper_score": v.get("tamper_score"),
            "confidence": v.get("confidence"),
            "flags": v.get("flags"),
        }

    async def is_fully_cleared(self, user_id: int) -> bool:
        agreement = await self.get_agreement_by_user(user_id)
        verification = await self.get_verification(user_id)
        return agreement is not None and verification is not None and agreement.get("revoked", 0) == 0

    # ── Guild Members ─────────────────────────────────────────────────

    async def register_guild_member(self, user_id: int, guild_id: int, guild_name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("INSERT OR IGNORE INTO guild_members (user_id, guild_id, guild_name, joined_at) VALUES (?, ?, ?, ?)", (user_id, guild_id, guild_name, now))
        await self._db.commit()

    async def get_user_guilds(self, user_id: int) -> list[dict]:
        cur = await self._db.execute("SELECT * FROM guild_members WHERE user_id = ?", (user_id,))
        return [dict(r) for r in await cur.fetchall()]

    async def get_user_guilds_scoped(self, user_id: int, requesting_guild_id: int) -> list[dict]:
        cur = await self._db.execute("SELECT * FROM guild_members WHERE user_id = ? AND guild_id = ?", (user_id, requesting_guild_id))
        return [dict(r) for r in await cur.fetchall()]

    async def get_guild_members(self, guild_id: int) -> list[dict]:
        cur = await self._db.execute(
            """SELECT gm.user_id, gm.guild_name, gm.joined_at, v.verified_at, a.agreement_id, a.signed_at AS agreement_date
               FROM guild_members gm
               LEFT JOIN verifications v ON gm.user_id = v.user_id
               LEFT JOIN agreements a ON gm.user_id = a.user_id
               WHERE gm.guild_id = ?
               ORDER BY gm.joined_at DESC""",
            (guild_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def remove_guild_member(self, user_id: int, guild_id: int) -> None:
        await self._db.execute("DELETE FROM guild_members WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        await self._db.commit()

    # ── Guild Settings (Hashed API Keys) ──────────────────────────────

    async def register_guild(self, guild_id: int, guild_name: str, owner_id: int) -> str:
        existing = await self.get_guild_settings(guild_id)
        if existing:
            await self._db.execute("UPDATE guild_settings SET guild_name = ?, owner_id = ? WHERE guild_id = ?", (guild_name, owner_id, guild_id))
            await self._db.commit()
            return ""
        plaintext_key = "ag_" + secrets.token_urlsafe(32)
        key_hash = hash_api_key(plaintext_key)
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("INSERT INTO guild_settings (guild_id, guild_name, owner_id, api_key_hash, registered_at) VALUES (?, ?, ?, ?, ?)", (guild_id, guild_name, owner_id, key_hash, now))
        await self._db.commit()
        return plaintext_key

    async def get_guild_settings(self, guild_id: int) -> Optional[dict]:
        cur = await self._db.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_guild_by_api_key(self, api_key: str) -> Optional[dict]:
        key_hash = hash_api_key(api_key)
        cur = await self._db.execute("SELECT * FROM guild_settings WHERE api_key_hash = ?", (key_hash,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def rotate_api_key(self, guild_id: int) -> str:
        plaintext_key = "ag_" + secrets.token_urlsafe(32)
        key_hash = hash_api_key(plaintext_key)
        await self._db.execute("UPDATE guild_settings SET api_key_hash = ? WHERE guild_id = ?", (key_hash, guild_id))
        await self._db.commit()
        return plaintext_key

    async def generate_api_key_for_guild(self, guild_id: int) -> str:
        plaintext_key = "ag_" + secrets.token_urlsafe(32)
        key_hash = hash_api_key(plaintext_key)
        await self._db.execute("UPDATE guild_settings SET api_key_hash = ? WHERE guild_id = ?", (key_hash, guild_id))
        await self._db.commit()
        return plaintext_key

    # ── Audit Log ─────────────────────────────────────────────────────

    async def audit(self, action: str, user_id: Optional[int] = None, guild_id: Optional[int] = None, details: Optional[str] = None, actor_id: Optional[int] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if details:
            details = details[:500].replace("\n", " ").replace("\r", "")
        await self._db.execute("INSERT INTO audit_log (timestamp, action, user_id, guild_id, details, actor_id) VALUES (?, ?, ?, ?, ?, ?)", (now, action, user_id, guild_id, details, actor_id))
        await self._db.commit()

    async def get_audit_log(self, guild_id: Optional[int] = None, user_id: Optional[int] = None, limit: int = 15) -> list[dict]:
        limit = min(limit, 50)
        if user_id:
            cur = await self._db.execute("SELECT * FROM audit_log WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        elif guild_id:
            cur = await self._db.execute("SELECT * FROM audit_log WHERE guild_id = ? ORDER BY id DESC LIMIT ?", (guild_id, limit))
        else:
            cur = await self._db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]

    # ── Stats ─────────────────────────────────────────────────────────

    async def get_guild_stats(self, guild_id: int) -> dict:
        cur = await self._db.execute("SELECT COUNT(*) as c FROM guild_members WHERE guild_id = ?", (guild_id,))
        total = (await cur.fetchone())["c"]
        cur = await self._db.execute("SELECT COUNT(*) as c FROM guild_members gm JOIN agreements a ON gm.user_id = a.user_id AND a.revoked = 0 WHERE gm.guild_id = ?", (guild_id,))
        with_agreement = (await cur.fetchone())["c"]
        return {"total_verified": total, "with_agreement": with_agreement}

    async def get_global_stats(self) -> dict:
        cur = await self._db.execute("SELECT COUNT(*) as c FROM verifications")
        total_v = (await cur.fetchone())["c"]
        cur = await self._db.execute("SELECT COUNT(*) as c FROM agreements WHERE revoked = 0")
        total_a = (await cur.fetchone())["c"]
        cur = await self._db.execute("SELECT COUNT(DISTINCT guild_id) as c FROM guild_settings")
        total_g = (await cur.fetchone())["c"]
        return {"total_verifications": total_v, "total_agreements": total_a, "total_guilds": total_g}

    async def purge_user(self, user_id: int) -> None:
        await self._db.execute("DELETE FROM agreements WHERE user_id = ?", (user_id,))
        await self._db.execute("DELETE FROM verifications WHERE user_id = ?", (user_id,))
        await self._db.execute("DELETE FROM guild_members WHERE user_id = ?", (user_id,))
        await self._db.commit()

    async def search_users(self, query: str, guild_id: Optional[int] = None) -> list[dict]:
        query = sanitize_search_query(query)
        if not query:
            return []
        if query.isdigit():
            v = await self.get_verification_safe(int(query))
            return [v] if v else []
        a = await self.get_agreement_by_id(query)
        if a:
            v = await self.get_verification_safe(a["user_id"])
            return [v or {"user_id": a["user_id"], "user_name": a["user_name"]}]
        if guild_id:
            cur = await self._db.execute("SELECT v.user_id, v.user_name, v.verified_at FROM verifications v JOIN guild_members gm ON v.user_id = gm.user_id WHERE gm.guild_id = ? AND v.user_name LIKE ? LIMIT 20", (guild_id, f"%{query}%"))
        else:
            cur = await self._db.execute("SELECT user_id, user_name, verified_at FROM verifications WHERE user_name LIKE ? LIMIT 20", (f"%{query}%",))
        return [dict(r) for r in await cur.fetchall()]

    async def count_recent_attempts(self, user_id: int, hours: int = 24) -> int:
        cur = await self._db.execute("SELECT COUNT(*) as c FROM audit_log WHERE user_id = ? AND action IN ('VERIFICATION_PASSED', 'VERIFICATION_FAILED') AND timestamp > datetime('now', ?)", (user_id, f"-{hours} hours"))
        return (await cur.fetchone())["c"]

    # ── Aliases (match cog method names) ───────────────────────────────

    async def get_attempt_count(self, user_id: int) -> int:
        return await self.count_recent_attempts(user_id)

    async def store_verification(self, **kwargs) -> str:
        return await self.save_verification(**kwargs)

    async def store_agreement(self, **kwargs) -> str:
        return await self.save_agreement(**kwargs)

    async def get_agreement(self, user_id: int) -> Optional[dict]:
        return await self.get_agreement_by_user(user_id)

    async def add_audit_entry(self, action: str, user_id: Optional[int] = None, guild_id: Optional[int] = None, details: Optional[str] = None, actor_id: Optional[int] = None) -> None:
        return await self.audit(action, user_id=user_id, guild_id=guild_id, details=details, actor_id=actor_id)

    async def regenerate_api_key(self, guild_id: int) -> str:
        return await self.rotate_api_key(guild_id)
