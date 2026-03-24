"""AgeGate — Entry point. Starts the Discord bot and FastAPI web dashboard."""

from __future__ import annotations

import logging
import threading

import discord
import uvicorn
from discord.ext import commands, tasks

from utils import Config, Database, ImageAnalyzer, StorageManager, FieldEncryptor
from web import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("agegate")


class AgeGateBot(commands.Bot):
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
        self.database = Database(field_encryptor=FieldEncryptor(config.encryption_key))
        self.image_analyzer = ImageAnalyzer(
            tamper_threshold=config.tamper_threshold,
            ocr_confidence=config.ocr_confidence,
            min_age=config.min_age,
        )
        self.storage_manager = StorageManager(
            encryption_key=config.encryption_key,
            retention_hours=config.retention_hours,
        )

    async def setup_hook(self) -> None:
        # Connect database
        await self.database.connect()
        log.info("Database connected")

        # Load cogs
        await self.load_extension("cogs.verification")
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.legal")
        log.info("Cogs loaded")

        # Sync slash commands
        await self.tree.sync()
        log.info("Commands synced")

        # Register persistent views
        from cogs.verification import VerifyButton
        self.add_view(VerifyButton())

        # Start background tasks
        self.purge_loop.start()

        # Start web dashboard in a daemon thread
        self._start_web_dashboard()

    async def on_ready(self) -> None:
        log.info(f"Logged in as {self.user} ({self.user.id})")
        log.info(f"Connected to {len(self.guilds)} guild(s)")

        # Auto-register all guilds
        for guild in self.guilds:
            await self.database.register_guild(guild.id, guild.name, guild.owner_id)
        log.info("All guilds registered")

        # Set presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="age verification",
            )
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.database.register_guild(guild.id, guild.name, guild.owner_id)
        await self.database.audit("GUILD_JOINED", guild_id=guild.id, details=guild.name)
        log.info(f"Joined guild: {guild.name} ({guild.id})")

    @tasks.loop(minutes=30)
    async def purge_loop(self) -> None:
        count = self.storage_manager.purge_expired()
        if count > 0:
            log.info(f"Purged {count} expired temp records")

    @purge_loop.before_loop
    async def before_purge_loop(self) -> None:
        await self.wait_until_ready()

    def _start_web_dashboard(self) -> None:
        web_app = create_app(
            self.database,
            secret_key=self.app_config.web_secret,
            master_api_key=self.app_config.api_master_key,
        )

        def run() -> None:
            uvicorn.run(
                web_app,
                host=self.app_config.web_host,
                port=self.app_config.web_port,
                log_level="warning",
            )

        thread = threading.Thread(target=run, daemon=True, name="agegate-web")
        thread.start()
        log.info(f"Web dashboard running on {self.app_config.web_base_url}")


def main() -> None:
    config = Config.from_env()
    bot = AgeGateBot(config)

    try:
        bot.run(config.discord_token, log_handler=None, reconnect=True)
    except KeyboardInterrupt:
        log.info("Shutting down…")


if __name__ == "__main__":
    main()
