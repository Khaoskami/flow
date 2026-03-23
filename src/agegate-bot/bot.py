"""AgeGate Bot — Entry point.

Starts the Discord bot and web dashboard in a single process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

import discord
from discord.ext import commands, tasks

# Ensure the project root is on sys.path so cogs/ and utils/ are importable
sys.path.insert(0, str(Path(__file__).parent))

from utils.config import Config
from utils.database import Database
from utils.image_analyzer import ImageAnalyzer
from utils.storage_manager import StorageManager

log = logging.getLogger("agegate")


class AgeGateBot(commands.Bot):
    """Main bot class with shared resources."""

    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=config.bot_prefix,
            intents=intents,
            help_command=None,
        )

        self.app_config = config
        self.database = Database(config.data_dir / "agegate.db")
        self.storage_manager = StorageManager(
            storage_dir=config.data_dir / "verifications",
            encryption_key=config.encryption_key,
            retention_hours=config.retention_hours,
        )
        self.image_analyzer = ImageAnalyzer(
            tamper_threshold=config.tamper_threshold,
            ocr_confidence_min=config.ocr_confidence,
            min_age=config.min_age,
        )

    async def setup_hook(self) -> None:
        """Called when the bot is starting up."""
        # Initialize database
        await self.database.init_db()
        log.info("Database initialized at %s", self.database.db_path)

        # Register persistent views
        from cogs.verification import VerifyButton
        self.add_view(VerifyButton())

        # Load cogs
        for cog in ("cogs.verification", "cogs.legal", "cogs.admin"):
            await self.load_extension(cog)
            log.info("Loaded cog: %s", cog)

        # Start background tasks
        self._cleanup_task.start()

        # Start web dashboard
        self._start_web_dashboard()

        # Sync slash commands
        await self.tree.sync()
        log.info("Slash commands synced")

    async def on_ready(self) -> None:
        log.info("AgeGate bot ready as %s (ID: %s)", self.user, self.user.id)
        log.info("Connected to %d guild(s)", len(self.guilds))

        # Auto-register all guilds
        for guild in self.guilds:
            await self.database.register_guild(
                guild.id, guild.name, guild.owner_id
            )
        log.info("All guilds registered")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Auto-register new guilds."""
        await self.database.register_guild(
            guild.id, guild.name, guild.owner_id
        )
        log.info("Joined and registered guild: %s (%d)", guild.name, guild.id)

    async def close(self) -> None:
        """Graceful shutdown."""
        self._cleanup_task.cancel()
        await self.database.close()
        log.info("Database closed")
        await super().close()

    # ── Background Tasks ───────────────────────────────────────

    @tasks.loop(minutes=30)
    async def _cleanup_task(self) -> None:
        """Purge expired temporary verification records."""
        deleted = self.storage_manager.cleanup_expired()
        if deleted > 0:
            log.info("Cleanup: deleted %d expired temp records", deleted)

    @_cleanup_task.before_loop
    async def _before_cleanup(self) -> None:
        await self.wait_until_ready()

    # ── Web Dashboard ──────────────────────────────────────────

    def _start_web_dashboard(self) -> None:
        """Start FastAPI dashboard in a daemon thread."""
        try:
            import uvicorn
            from web.app import create_app

            config = self.app_config
            web_app = create_app(
                database=self.database,
                secret_key=config.web_secret or "agegate-fallback-secret",
                master_api_key=config.api_master_key,
            )

            thread = threading.Thread(
                target=uvicorn.run,
                args=(web_app,),
                kwargs={
                    "host": config.web_host,
                    "port": config.web_port,
                    "log_level": "warning",
                },
                daemon=True,
                name="agegate-web",
            )
            thread.start()
            log.info(
                "Web dashboard started at http://%s:%d",
                config.web_host,
                config.web_port,
            )
        except Exception as e:
            log.error("Failed to start web dashboard: %s", e)


def main() -> None:
    """Application entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        config = Config.from_env()
    except ValueError as e:
        log.error("Configuration error: %s", e)
        sys.exit(1)

    bot = AgeGateBot(config)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
