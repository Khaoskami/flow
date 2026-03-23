"""Legal consent cog — paginated documents, signing, cross-server accept."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from utils.legal_document import (
    DOCUMENT_VERSION,
    generate_agreement,
    generate_summary,
    hash_document,
    split_for_embeds,
)

if TYPE_CHECKING:
    from bot import AgeGateBot

log = logging.getLogger("agegate.legal")


# ── Paginated Document View ────────────────────────────────────

class LegalDocumentView(discord.ui.View):
    """Paginated legal document with navigation and sign button."""

    def __init__(
        self,
        pages: list[str],
        bot: AgeGateBot,
        user: discord.User,
        guild: discord.Guild,
        document_text: str,
        document_hash: str,
        verification_id: str,
    ) -> None:
        super().__init__(timeout=600)
        self.pages = pages
        self.current_page = 0
        self.bot = bot
        self.user = user
        self.guild = guild
        self.document_text = document_text
        self.document_hash = document_hash
        self.verification_id = verification_id
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= len(self.pages) - 1
        # Sign button only enabled on last page
        self.sign_btn.disabled = self.current_page < len(self.pages) - 1

    def _make_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📜 Consent Agreement",
            description=f"```\n{self.pages[self.current_page]}\n```",
            color=0x2B2D31,
        )
        embed.set_footer(
            text=f"Page {self.current_page + 1}/{len(self.pages)} | "
                 f"Version {DOCUMENT_VERSION} | Hash: {self.document_hash[:12]}…"
        )
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.current_page = max(0, self.current_page - 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self._make_embed(), view=self
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self._make_embed(), view=self
        )

    @discord.ui.button(
        label="✍️ I Agree — Sign Document",
        style=discord.ButtonStyle.green,
    )
    async def sign_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # Show confirmation
        view = ConfirmSignView(
            self.bot, self.user, self.guild,
            self.document_text, self.document_hash,
            self.verification_id,
        )
        embed = discord.Embed(
            title="⚠️ Final Confirmation",
            description=(
                "**Are you absolutely sure you want to sign this agreement?**\n\n"
                "By signing, you confirm:\n"
                "• You are 18 years of age or older\n"
                "• The ID you submitted is genuine and yours\n"
                "• You agree to all terms in the consent agreement\n"
                "• This is a legally binding electronic signature\n\n"
                f"**Document Hash:** `{self.document_hash[:24]}…`\n"
                f"**Version:** {DOCUMENT_VERSION}"
            ),
            color=0xFEE75C,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        embed = discord.Embed(
            title="❌ Cancelled",
            description="You have cancelled the signing process. You can try again later.",
            color=0xED4245,
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ── Confirmation View ──────────────────────────────────────────

class ConfirmSignView(discord.ui.View):
    """Double-confirmation for signing the legal agreement."""

    def __init__(
        self,
        bot: AgeGateBot,
        user: discord.User,
        guild: discord.Guild,
        document_text: str,
        document_hash: str,
        verification_id: str,
    ) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.user = user
        self.guild = guild
        self.document_text = document_text
        self.document_hash = document_hash
        self.verification_id = verification_id

    @discord.ui.button(
        label="✅ Yes, I'm Sure — Sign Now",
        style=discord.ButtonStyle.green,
    )
    async def confirm_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()

        # Store agreement
        agreement_id = await self.bot.database.store_agreement(
            user_id=self.user.id,
            user_name=self.user.name,
            document_text=self.document_text,
            document_hash=self.document_hash,
            version=DOCUMENT_VERSION,
        )

        # Register guild membership
        await self.bot.database.register_guild_member(
            self.user.id, self.guild.id, self.guild.name
        )

        # Audit log
        await self.bot.database.add_audit_entry(
            "AGREEMENT_SIGNED",
            user_id=self.user.id,
            guild_id=self.guild.id,
            details=f"Agreement: {agreement_id}, Version: {DOCUMENT_VERSION}",
        )

        # Success embed
        embed = discord.Embed(
            title="✅ Agreement Signed Successfully",
            description=(
                f"**Agreement ID:** `{agreement_id}`\n"
                f"**Version:** {DOCUMENT_VERSION}\n"
                f"**Hash:** `{self.document_hash[:24]}…`\n\n"
                "🔗 Your verification is now recognized across all servers "
                "using AgeGate. You will not need to verify again."
            ),
            color=0x57F287,
        )
        await interaction.response.edit_message(embed=embed, view=None)

        # Assign verified role
        config = self.bot.app_config
        member = self.guild.get_member(self.user.id)
        if member:
            role = discord.utils.get(self.guild.roles, name=config.verified_role)
            if role:
                try:
                    await member.add_roles(
                        role, reason="AgeGate verification complete"
                    )
                except discord.Forbidden:
                    log.warning(
                        "Cannot assign role in %s — missing permissions",
                        self.guild.name,
                    )

        # Admin log
        log_channel = discord.utils.get(
            self.guild.text_channels, name=config.log_channel
        )
        if log_channel:
            log_embed = discord.Embed(
                title="✅ Verification Complete",
                color=0x57F287,
            )
            log_embed.add_field(
                name="User", value=f"{self.user.mention} ({self.user.id})"
            )
            log_embed.add_field(name="Agreement", value=agreement_id)
            log_embed.add_field(name="Version", value=str(DOCUMENT_VERSION))
            try:
                await log_channel.send(embed=log_embed)
            except discord.Forbidden:
                pass

    @discord.ui.button(
        label="No, Go Back",
        style=discord.ButtonStyle.secondary,
    )
    async def goback_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        embed = discord.Embed(
            title="↩️ Signing Cancelled",
            description="You can try the verification process again.",
            color=0x2B2D31,
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ── Entry Point for Legal Flow ─────────────────────────────────

async def start_legal_flow(
    bot: AgeGateBot,
    user: discord.User,
    guild: discord.Guild,
    verification_id: str,
) -> None:
    """Initiate the legal consent signing flow after successful ID verification."""
    config = bot.app_config

    # Generate the document
    document_text = generate_agreement(
        user_name=user.name,
        user_id=user.id,
        guild_name=guild.name,
        guild_id=guild.id,
        org_name=config.org_name,
        contact_email=config.legal_contact_email,
    )
    doc_hash = hash_document(document_text)
    pages = split_for_embeds(document_text)

    try:
        dm = await user.create_dm()
    except discord.Forbidden:
        return

    # Summary embed
    summary_embed = discord.Embed(
        title="📜 Legal Consent Agreement",
        description=(
            "Before we can complete your verification, you must review and sign "
            "the following consent agreement.\n\n"
            + generate_summary()
        ),
        color=0x5865F2,
    )
    summary_embed.set_footer(
        text=f"Version {DOCUMENT_VERSION} | Navigate through the full document below"
    )
    await dm.send(embed=summary_embed)

    # Paginated document
    view = LegalDocumentView(
        pages=pages,
        bot=bot,
        user=user,
        guild=guild,
        document_text=document_text,
        document_hash=doc_hash,
        verification_id=verification_id,
    )
    await dm.send(embed=view._make_embed(), view=view)


# ── Cog ────────────────────────────────────────────────────────

class LegalCog(commands.Cog, name="Legal"):
    """Legal consent document management."""

    def __init__(self, bot: AgeGateBot) -> None:
        self.bot = bot


async def setup(bot: AgeGateBot) -> None:
    await bot.add_cog(LegalCog(bot))
