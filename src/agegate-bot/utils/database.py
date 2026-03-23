"""Persistent SQLite database for agreements, verifications, guilds, and audit."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

import aiosqlite

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agreements (
    agreement_id TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL UNIQUE,
    user_name    TEXT NOT NULL,
    document_text TEXT NOT NULL,
    document_hash TEXT NOT NULL,
    signed_at    TEXT NOT NULL,
    ip_hint      TEXT DEFAULT NULL,
    version      INTEGER DEFAULT 1,
    revoked      INTEGER DEFAULT 0,
    revoked_at   TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS verifications (
    verification_id TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL UNIQUE,
    user_name       TEXT NOT NULL,
    verified_at     TEXT NOT NULL,
    age_detected    INTEGER,
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
    api_key       TEXT UNIQUE,
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Async SQLite database manager."""

    def __init__(self, db_path: str | Path = "data/agegate.db") -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not initialized — call init_db() first")
        return self._db

    # ── Agreements ──────────────────────────────────────────────

    async def store_agreement(
        self,
        user_id: int,
        user_name: str,
        document_text: str,
        document_hash: str,
        version: int = 1,
    ) -> str:
        agreement_id = uuid4().hex[:16]
        await self.db.execute(
            """INSERT OR REPLACE INTO agreements
               (agreement_id, user_id, user_name, document_text, document_hash,
                signed_at, version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agreement_id, user_id, user_name, document_text, document_hash,
             _now(), version),
        )
        await self.db.commit()
        return agreement_id

    async def get_agreement(self, user_id: int) -> dict[str, Any] | None:
        async with self.db.execute(
            "SELECT * FROM agreements WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    async def get_agreement_by_id(self, agreement_id: str) -> dict[str, Any] | None:
        async with self.db.execute(
            "SELECT * FROM agreements WHERE agreement_id = ?", (agreement_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    async def revoke_agreement(self, user_id: int) -> bool:
        cur = await self.db.execute(
            "UPDATE agreements SET revoked = 1, revoked_at = ? WHERE user_id = ?",
            (_now(), user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ── Verifications ──────────────────────────────────────────

    async def store_verification(
        self,
        user_id: int,
        user_name: str,
        age_detected: int | None = None,
        dob_extracted: str | None = None,
        tamper_score: float | None = None,
        confidence: float | None = None,
        image_hash: str | None = None,
        flags: list[str] | None = None,
    ) -> str:
        vid = uuid4().hex[:16]
        await self.db.execute(
            """INSERT OR REPLACE INTO verifications
               (verification_id, user_id, user_name, verified_at,
                age_detected, dob_extracted, tamper_score, confidence,
                image_hash, flags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vid, user_id, user_name, _now(), age_detected, dob_extracted,
             tamper_score, confidence, image_hash,
             json.dumps(flags or [])),
        )
        await self.db.commit()
        return vid

    async def get_verification(self, user_id: int) -> dict[str, Any] | None:
        async with self.db.execute(
            "SELECT * FROM verifications WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            result = dict(zip(cols, row))
            result["flags"] = json.loads(result.get("flags", "[]"))
            return result

    # ── Guild Members ──────────────────────────────────────────

    async def register_guild_member(
        self, user_id: int, guild_id: int, guild_name: str
    ) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO guild_members
               (user_id, guild_id, guild_name, joined_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, guild_id, guild_name, _now()),
        )
        await self.db.commit()

    async def get_user_guilds(self, user_id: int) -> list[dict[str, Any]]:
        async with self.db.execute(
            "SELECT * FROM guild_members WHERE user_id = ?", (user_id,)
        ) as cur:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in await cur.fetchall()]

    async def get_guild_members(self, guild_id: int) -> list[dict[str, Any]]:
        async with self.db.execute(
            """SELECT gm.*, v.age_detected, v.verified_at, a.agreement_id
               FROM guild_members gm
               LEFT JOIN verifications v ON gm.user_id = v.user_id
               LEFT JOIN agreements a ON gm.user_id = a.user_id
               WHERE gm.guild_id = ?
               ORDER BY gm.joined_at DESC""",
            (guild_id,),
        ) as cur:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in await cur.fetchall()]

    async def remove_guild_member(self, user_id: int, guild_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM guild_members WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ── Guild Settings ─────────────────────────────────────────

    async def register_guild(
        self, guild_id: int, guild_name: str, owner_id: int
    ) -> str:
        api_key = f"ag_{token_urlsafe(32)}"
        await self.db.execute(
            """INSERT OR IGNORE INTO guild_settings
               (guild_id, guild_name, owner_id, api_key, registered_at)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, guild_name, owner_id, api_key, _now()),
        )
        await self.db.commit()
        return api_key

    async def get_guild_settings(self, guild_id: int) -> dict[str, Any] | None:
        async with self.db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    async def get_guild_by_api_key(self, api_key: str) -> dict[str, Any] | None:
        async with self.db.execute(
            "SELECT * FROM guild_settings WHERE api_key = ?", (api_key,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    async def regenerate_api_key(self, guild_id: int) -> str:
        new_key = f"ag_{token_urlsafe(32)}"
        await self.db.execute(
            "UPDATE guild_settings SET api_key = ? WHERE guild_id = ?",
            (new_key, guild_id),
        )
        await self.db.commit()
        return new_key

    # ── Audit Log ──────────────────────────────────────────────

    async def add_audit_entry(
        self,
        action: str,
        user_id: int | None = None,
        guild_id: int | None = None,
        details: str | None = None,
        actor_id: int | None = None,
    ) -> None:
        await self.db.execute(
            """INSERT INTO audit_log (timestamp, action, user_id, guild_id, details, actor_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_now(), action, user_id, guild_id, details, actor_id),
        )
        await self.db.commit()

    async def get_audit_log(
        self, guild_id: int | None = None, limit: int = 15
    ) -> list[dict[str, Any]]:
        if guild_id:
            sql = "SELECT * FROM audit_log WHERE guild_id = ? ORDER BY id DESC LIMIT ?"
            params: tuple = (guild_id, limit)
        else:
            sql = "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?"
            params = (limit,)
        async with self.db.execute(sql, params) as cur:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in await cur.fetchall()]

    # ── Cross-Server Recognition ───────────────────────────────

    async def is_fully_cleared(self, user_id: int) -> bool:
        agreement = await self.get_agreement(user_id)
        verification = await self.get_verification(user_id)
        if not agreement or not verification:
            return False
        return agreement.get("revoked", 0) == 0

    # ── Search ─────────────────────────────────────────────────

    async def search_users(self, query: str) -> list[dict[str, Any]]:
        async with self.db.execute(
            """SELECT v.user_id, v.user_name, v.verified_at, v.age_detected,
                      a.agreement_id, a.signed_at
               FROM verifications v
               LEFT JOIN agreements a ON v.user_id = a.user_id
               WHERE CAST(v.user_id AS TEXT) LIKE ? OR v.user_name LIKE ?
               ORDER BY v.verified_at DESC LIMIT 50""",
            (f"%{query}%", f"%{query}%"),
        ) as cur:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in await cur.fetchall()]

    # ── Stats ──────────────────────────────────────────────────

    async def get_guild_stats(self, guild_id: int) -> dict[str, int]:
        async with self.db.execute(
            "SELECT COUNT(*) FROM guild_members WHERE guild_id = ?", (guild_id,)
        ) as cur:
            total = (await cur.fetchone())[0]
        async with self.db.execute(
            """SELECT COUNT(*) FROM guild_members gm
               JOIN agreements a ON gm.user_id = a.user_id AND a.revoked = 0
               WHERE gm.guild_id = ?""",
            (guild_id,),
        ) as cur:
            with_agreement = (await cur.fetchone())[0]
        return {"total_verified": total, "with_agreement": with_agreement}

    async def get_global_stats(self) -> dict[str, int]:
        async with self.db.execute("SELECT COUNT(*) FROM verifications") as cur:
            verifications = (await cur.fetchone())[0]
        async with self.db.execute(
            "SELECT COUNT(*) FROM agreements WHERE revoked = 0"
        ) as cur:
            agreements = (await cur.fetchone())[0]
        async with self.db.execute(
            "SELECT COUNT(DISTINCT guild_id) FROM guild_members"
        ) as cur:
            guilds = (await cur.fetchone())[0]
        return {
            "total_verifications": verifications,
            "total_agreements": agreements,
            "total_guilds": guilds,
        }

    # ── Purge (GDPR) ──────────────────────────────────────────

    async def purge_user(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM agreements WHERE user_id = ?", (user_id,))
        await self.db.execute(
            "DELETE FROM verifications WHERE user_id = ?", (user_id,)
        )
        await self.db.execute(
            "DELETE FROM guild_members WHERE user_id = ?", (user_id,)
        )
        await self.db.commit()

    # ── Rate Limiting ──────────────────────────────────────────

    async def get_attempt_count(self, user_id: int, hours: int = 24) -> int:
        cutoff = datetime.now(timezone.utc).isoformat()
        async with self.db.execute(
            """SELECT COUNT(*) FROM audit_log
               WHERE user_id = ? AND action IN ('VERIFICATION_PASSED', 'VERIFICATION_FAILED')
               AND timestamp > datetime(?, '-' || ? || ' hours')""",
            (user_id, cutoff, hours),
        ) as cur:
            return (await cur.fetchone())[0]
