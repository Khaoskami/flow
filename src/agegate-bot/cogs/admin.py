"""Admin cog — slash commands for server management and oversight."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from bot import AgeGateBot

log = logging.getLogger("agegate.admin")


class AdminCog(commands.Cog, name="Admin"):
    """Administrative commands for AgeGate management."""

    def __init__(self, bot: AgeGateBot) -> None:
        self.bot = bot

    # ── API Key Management ─────────────────────────────────────

    @app_commands.command(
        name="get-api-key",
        description="Get your guild's dashboard API key",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def get_api_key(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        settings = await self.bot.database.get_guild_settings(guild.id)
        if not settings:
            api_key = await self.bot.database.register_guild(
                guild.id, guild.name, guild.owner_id
            )
            if not api_key:
                await interaction.followup.send(
                    "❌ Could not generate API key.", ephemeral=True
                )
                return
        else:
            # Key is hashed — generate a new one so user can see it
            api_key = await self.bot.database.regenerate_api_key(guild.id)

        config = self.bot.app_config
        embed = discord.Embed(
            title="🔑 Dashboard API Key",
            description=(
                f"```\n{api_key}\n```\n"
                f"Use this key to log in to the web dashboard at "
                f"**{config.web_base_url}**\n\n"
                "⚠️ Keep this key secret! Anyone with it can access "
                "your server's verification data.\n"
                "⚠️ This key is shown once — save it now."
            ),
            color=0x5865F2,
        )
        embed.set_footer(text="Use /regen-api-key to rotate this key")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="regen-api-key",
        description="Regenerate your guild's dashboard API key",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def regen_api_key(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        new_key = await self.bot.database.regenerate_api_key(guild.id)

        await self.bot.database.add_audit_entry(
            "API_KEY_ROTATED",
            guild_id=guild.id,
            actor_id=interaction.user.id,
            details="API key regenerated",
        )

        embed = discord.Embed(
            title="🔄 API Key Regenerated",
            description=(
                f"```\n{new_key}\n```\n"
                "The old key is now invalid. Update your dashboard login."
            ),
            color=0x57F287,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── View Agreement ─────────────────────────────────────────

    @app_commands.command(
        name="view-agreement",
        description="View a user's signed consent agreement summary",
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def view_agreement(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        agreement = await self.bot.database.get_agreement(user.id)
        if not agreement:
            await interaction.followup.send(
                f"❌ {user.mention} has not signed a consent agreement.",
                ephemeral=True,
            )
            return

        status = "🟢 Active" if not agreement.get("revoked") else "🔴 Revoked"
        embed = discord.Embed(
            title=f"📜 Agreement — {user.name}",
            color=0x57F287 if not agreement.get("revoked") else 0xED4245,
        )
        embed.add_field(name="Agreement ID", value=agreement["agreement_id"])
        embed.add_field(name="Status", value=status)
        embed.add_field(name="Signed", value=agreement["signed_at"][:19])
        embed.add_field(name="Version", value=str(agreement.get("version", 1)))
        embed.add_field(
            name="Document Hash",
            value=f"`{agreement['document_hash'][:24]}…`",
        )
        if agreement.get("revoked"):
            embed.add_field(
                name="Revoked At", value=agreement.get("revoked_at", "N/A")[:19]
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Audit Log ──────────────────────────────────────────────

    @app_commands.command(
        name="audit-log",
        description="View recent audit log entries for this server",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def audit_log(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        entries = await self.bot.database.get_audit_log(guild.id, limit=15)
        if not entries:
            await interaction.followup.send(
                "📋 No audit log entries found.", ephemeral=True
            )
            return

        lines = []
        for entry in entries:
            ts = entry["timestamp"][:16]
            action = entry["action"]
            uid = entry.get("user_id", "—")
            details = entry.get("details", "")
            if len(details) > 60:
                details = details[:57] + "…"
            lines.append(f"`{ts}` **{action}** | User: {uid}\n{details}")

        embed = discord.Embed(
            title=f"📋 Audit Log — {guild.name}",
            description="\n\n".join(lines[:15]),
            color=0x5865F2,
        )
        embed.set_footer(text=f"Showing last {len(entries)} entries")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── User Management ────────────────────────────────────────

    @app_commands.command(
        name="unverify",
        description="Remove verification from a user on this server",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def unverify(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        config = self.bot.app_config

        # Remove guild membership
        await self.bot.database.remove_guild_member(user.id, guild.id)

        # Revoke agreement
        await self.bot.database.revoke_agreement(user.id)

        # Remove role
        member = guild.get_member(user.id)
        if member:
            role = discord.utils.get(guild.roles, name=config.verified_role)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="AgeGate: Unverified by admin")
                except discord.Forbidden:
                    pass

        # Purge temp records
        verification = await self.bot.database.get_verification(user.id)
        if verification:
            self.bot.storage_manager.delete(verification["verification_id"])

        await self.bot.database.add_audit_entry(
            "USER_UNVERIFIED",
            user_id=user.id,
            guild_id=guild.id,
            actor_id=interaction.user.id,
            details=f"Unverified by {interaction.user.name}",
        )

        await interaction.followup.send(
            f"✅ {user.mention} has been unverified and their agreement revoked.",
            ephemeral=True,
        )

    @app_commands.command(
        name="purge-user",
        description="GDPR: Delete ALL data for a user across all servers",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def purge_user(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        # Delete verification temp records
        verification = await self.bot.database.get_verification(user.id)
        if verification:
            self.bot.storage_manager.delete(verification["verification_id"])

        # Purge all database records
        await self.bot.database.purge_user(user.id)

        await self.bot.database.add_audit_entry(
            "USER_DATA_PURGED",
            user_id=user.id,
            guild_id=guild.id,
            actor_id=interaction.user.id,
            details=f"Full data purge requested by {interaction.user.name}",
        )

        # Remove role if possible
        config = self.bot.app_config
        member = guild.get_member(user.id)
        if member:
            role = discord.utils.get(guild.roles, name=config.verified_role)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="AgeGate: Data purged")
                except discord.Forbidden:
                    pass

        await interaction.followup.send(
            f"🗑️ All data for {user.mention} has been permanently deleted.",
            ephemeral=True,
        )

    @app_commands.command(
        name="force-purge",
        description="Manually trigger cleanup of expired temporary records",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def force_purge(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        deleted = self.bot.storage_manager.purge_expired()

        await self.bot.database.add_audit_entry(
            "FORCE_PURGE",
            guild_id=interaction.guild.id if interaction.guild else None,
            actor_id=interaction.user.id,
            details=f"Deleted {deleted} expired temp records",
        )

        await interaction.followup.send(
            f"🧹 Purged {deleted} expired temporary record(s).",
            ephemeral=True,
        )


async def setup(bot: AgeGateBot) -> None:
    await bot.add_cog(AdminCog(bot))
