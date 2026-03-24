"""Verification cog — button panel, DM flow, image upload, cross-server."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from bot import AgeGateBot

log = logging.getLogger("agegate.verification")


# ── Persistent Verify Button ───────────────────────────────────

class VerifyButton(discord.ui.View):
    """Persistent verification button that survives bot restarts."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🪪 Verify My Age",
        style=discord.ButtonStyle.green,
        custom_id="agegate:verify_start",
    )
    async def verify_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        bot: AgeGateBot = interaction.client  # type: ignore[assignment]
        user = interaction.user
        guild = interaction.guild

        if not guild:
            return

        # Check if user already has the verified role
        role = discord.utils.get(guild.roles, name=bot.app_config.verified_role)
        if role and isinstance(user, discord.Member) and role in user.roles:
            await interaction.response.send_message(
                "✅ You are already verified on this server!", ephemeral=True
            )
            return

        # Rate limit check
        config = bot.app_config
        attempts = await bot.database.get_attempt_count(user.id)
        if attempts >= config.max_attempts:
            await interaction.response.send_message(
                f"⏳ You have reached the maximum of {config.max_attempts} "
                "attempts in 24 hours. Please try again later.",
                ephemeral=True,
            )
            return

        # Cross-server recognition check
        if await bot.database.is_fully_cleared(user.id):
            await interaction.response.send_message(
                "📨 Check your DMs!", ephemeral=True
            )
            await _send_cross_server_prompt(bot, user, guild)
            return

        # New verification
        await interaction.response.send_message(
            "📨 Check your DMs!", ephemeral=True
        )
        await _start_dm_verification(bot, user, guild)


# ── Cross-Server Recognition ──────────────────────────────────

class CrossServerView(discord.ui.View):
    """Buttons for accepting or declining cross-server recognition."""

    def __init__(self, bot: AgeGateBot, guild: discord.Guild) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild = guild
        self.value: bool | None = None

    @discord.ui.button(
        label="✅ Yes — Apply My Verification",
        style=discord.ButtonStyle.green,
    )
    async def accept(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(
        label="No — Verify Fresh",
        style=discord.ButtonStyle.secondary,
    )
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.value = False
        self.stop()
        await interaction.response.defer()


async def _send_cross_server_prompt(
    bot: AgeGateBot, user: discord.User, guild: discord.Guild
) -> None:
    """Prompt user to accept cross-server recognition or re-verify."""
    agreement = await bot.database.get_agreement(user.id)
    verification = await bot.database.get_verification(user.id)

    embed = discord.Embed(
        title="🔗 Existing Verification Found",
        description=(
            "You have already been verified on another server using AgeGate.\n"
            "Would you like to apply your existing verification here?"
        ),
        color=0x5865F2,
    )
    if agreement:
        embed.add_field(name="Agreement ID", value=agreement["agreement_id"])
        embed.add_field(name="Signed", value=agreement["signed_at"][:10])
    if verification and verification.get("age_detected"):
        embed.add_field(name="Age", value=str(verification["age_detected"]))
    embed.add_field(
        name="Server", value=f"{guild.name} ({guild.id})", inline=False
    )

    view = CrossServerView(bot, guild)
    try:
        dm = await user.create_dm()
        await dm.send(embed=embed, view=view)
    except discord.Forbidden:
        return

    await view.wait()

    if view.value is True:
        await _apply_verification(bot, user, guild)
    elif view.value is False:
        await _start_dm_verification(bot, user, guild)


async def _apply_verification(
    bot: AgeGateBot, user: discord.User, guild: discord.Guild
) -> None:
    """Apply existing verification to a new guild."""
    config = bot.app_config
    await bot.database.register_guild_member(user.id, guild.id, guild.name)
    await bot.database.add_audit_entry(
        "CROSS_SERVER_APPLIED", user.id, guild.id,
        f"Existing verification applied to {guild.name}",
    )

    # Assign role
    member = guild.get_member(user.id)
    if member:
        role = discord.utils.get(guild.roles, name=config.verified_role)
        if role:
            try:
                await member.add_roles(role, reason="AgeGate cross-server verification")
            except discord.Forbidden:
                pass

    dm = await user.create_dm()
    embed = discord.Embed(
        title="✅ Verification Applied",
        description=(
            f"Your existing verification has been applied to **{guild.name}**.\n"
            "You now have the verified role on this server."
        ),
        color=0x57F287,
    )
    await dm.send(embed=embed)

    # Admin log
    await _log_to_admin(bot, guild, user, "CROSS_SERVER_APPLIED", passed=True)


# ── DM Verification Flow ──────────────────────────────────────

async def _start_dm_verification(
    bot: AgeGateBot, user: discord.User, guild: discord.Guild
) -> None:
    """Full DM-based verification flow: guide → image → analysis → legal."""
    config = bot.app_config
    attempts = await bot.database.get_attempt_count(user.id)
    remaining = config.max_attempts - attempts

    try:
        dm = await user.create_dm()
    except discord.Forbidden:
        return

    # Embed 1 — Context card
    ctx_embed = discord.Embed(
        title="🔒 Age Verification",
        description=f"Verification for **{guild.name}**",
        color=0x2B2D31,
    )
    ctx_embed.add_field(name="Remaining Attempts", value=str(remaining))

    # Embed 2 — Full guide
    guide_embed = discord.Embed(
        title="📋 ID Verification Guide",
        color=0x5865F2,
    )
    guide_embed.add_field(
        name="🪪 ID Requirements",
        value=(
            "• Government-issued photo ID (passport, driver's license, national ID)\n"
            "• You may cover personal info EXCEPT date of birth and expiry date\n"
            "• The ID must be clearly readable"
        ),
        inline=False,
    )
    guide_embed.add_field(
        name="📝 Handwritten Note",
        value=(
            "• Write your Discord username and today's date on a piece of paper\n"
            "• Place the note next to your ID in the photo"
        ),
        inline=False,
    )
    guide_embed.add_field(
        name="✋ Hand Requirement",
        value="Hold your ID in your hand — this proves it's a live photo, not a screenshot.",
        inline=False,
    )
    guide_embed.add_field(
        name="📸 Photo Tips",
        value=(
            "• Good lighting, no glare\n"
            "• Steady camera, no blur\n"
            "• PNG, JPG, or WebP format\n"
            "• Maximum 15 MB"
        ),
        inline=False,
    )
    guide_embed.add_field(
        name="🔐 Privacy",
        value=(
            "Your image is analyzed by automated software only — no humans see it. "
            "The image is immediately deleted after analysis. Only verification "
            "results (pass/fail, age) are stored."
        ),
        inline=False,
    )

    # Embed 3 — Quick summary
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    summary_embed = discord.Embed(
        title="✏️ Write This on Your Paper",
        description=f"```\n{user.name}\n{today}\n```",
        color=0xFEE75C,
    )
    summary_embed.set_footer(text="Send a photo of your ID + note when ready.")

    await dm.send(embeds=[ctx_embed, guide_embed, summary_embed])

    # Wait for image
    def check(m: discord.Message) -> bool:
        return m.author.id == user.id and m.channel.id == dm.id and len(m.attachments) > 0

    try:
        msg = await bot.wait_for("message", check=check, timeout=600)
    except TimeoutError:
        await dm.send(
            embed=discord.Embed(
                title="⏰ Verification Timed Out",
                description="You took too long to send your photo. Please try again.",
                color=0xED4245,
            )
        )
        return

    attachment = msg.attachments[0]

    # Validate file
    valid_types = ("image/png", "image/jpeg", "image/webp")
    if attachment.content_type and attachment.content_type not in valid_types:
        await dm.send(
            embed=discord.Embed(
                title="❌ Invalid File Type",
                description="Please send a PNG, JPG, or WebP image.",
                color=0xED4245,
            )
        )
        return

    if attachment.size > 15 * 1024 * 1024:
        await dm.send(
            embed=discord.Embed(
                title="❌ File Too Large",
                description="Maximum file size is 15 MB.",
                color=0xED4245,
            )
        )
        return

    # Processing embed
    processing = await dm.send(
        embed=discord.Embed(
            title="⏳ Analyzing Your Photo…",
            description=(
                "Running verification checks:\n"
                "• Resolution validation\n"
                "• Image integrity analysis\n"
                "• Hand/skin detection\n"
                "• Text recognition (OCR)\n"
                "• Username & date verification\n"
                "• Document type & age validation"
            ),
            color=0xFEE75C,
        )
    )

    # Download and analyze
    image_bytes = await attachment.read()
    analyzer = bot.image_analyzer
    analysis = await analyzer.analyze(image_bytes, user.name)

    # Explicitly delete image bytes
    del image_bytes

    if not analysis.passed:
        # Log failure
        await bot.database.add_audit_entry(
            "VERIFICATION_FAILED", user.id, guild.id,
            f"Reason: {analysis.rejection_reason}",
        )

        fail_embed = discord.Embed(
            title="❌ Verification Failed",
            description=analysis.rejection_reason,
            color=0xED4245,
        )
        checks_str = "\n".join(
            f"{'✅' if v else '❌'} {k.replace('_', ' ').title()}"
            for k, v in analysis.checks.items()
        )
        if checks_str:
            fail_embed.add_field(name="Checks", value=checks_str, inline=False)
        if analysis.flags:
            fail_embed.add_field(
                name="Flags", value=", ".join(analysis.flags), inline=False
            )
        fail_embed.set_footer(text=f"Remaining attempts: {remaining - 1}")

        await processing.edit(embed=fail_embed)
        await _log_to_admin(
            bot, guild, user, "VERIFICATION_FAILED",
            passed=False, analysis=analysis,
        )
        return

    # Store verification
    vid = await bot.database.store_verification(
        user_id=user.id,
        user_name=user.name,
        age_detected=analysis.age_detected,
        dob_extracted=analysis.dob_extracted,
        tamper_score=analysis.tamper_score,
        confidence=analysis.ocr_confidence,
        image_hash=analysis.image_hash,
        flags=analysis.flags,
    )

    # Store temp record
    bot.storage_manager.save(vid, {
        "verification_id": vid,
        "user_id": user.id,
        "tamper_score": analysis.tamper_score,
        "confidence": analysis.ocr_confidence,
        "age_detected": analysis.age_detected,
        "checks": analysis.checks,
        "flags": analysis.flags,
    })

    # Success embed
    checks_str = "\n".join(
        f"{'✅' if v else '❌'} {k.replace('_', ' ').title()}"
        for k, v in analysis.checks.items()
    )
    pass_embed = discord.Embed(
        title="✅ ID Verification Passed",
        description="Your photo has passed all verification checks.",
        color=0x57F287,
    )
    pass_embed.add_field(name="Record ID", value=vid)
    pass_embed.add_field(name="Integrity Score", value=f"{1 - analysis.tamper_score:.0%}")
    if analysis.age_detected:
        pass_embed.add_field(name="Age", value=str(analysis.age_detected))
    pass_embed.add_field(name="Checks", value=checks_str, inline=False)

    await processing.edit(embed=pass_embed)

    await bot.database.add_audit_entry(
        "VERIFICATION_PASSED", user.id, guild.id,
        f"Age: {analysis.age_detected}, Tamper: {analysis.tamper_score:.4f}",
    )

    # Hand off to legal consent flow
    from cogs.legal import start_legal_flow
    await start_legal_flow(bot, user, guild, vid)


# ── Admin Logging ──────────────────────────────────────────────

async def _log_to_admin(
    bot: AgeGateBot,
    guild: discord.Guild,
    user: discord.User,
    action: str,
    passed: bool,
    analysis=None,
) -> None:
    """Send a log embed to the admin logging channel."""
    config = bot.app_config
    log_channel = discord.utils.get(guild.text_channels, name=config.log_channel)
    if not log_channel:
        return

    color = 0x57F287 if passed else 0xED4245
    embed = discord.Embed(
        title=f"{'✅' if passed else '❌'} {action.replace('_', ' ').title()}",
        color=color,
    )
    embed.add_field(name="User", value=f"{user.mention} ({user.id})")

    if analysis:
        embed.add_field(name="Tamper Score", value=f"{analysis.tamper_score:.4f}")
        if analysis.age_detected:
            embed.add_field(name="Age", value=str(analysis.age_detected))
        embed.add_field(name="OCR Confidence", value=f"{analysis.ocr_confidence:.0%}")
        embed.add_field(
            name="Skin Coverage", value=f"{analysis.skin_coverage:.1%}"
        )
        if analysis.flags:
            embed.add_field(
                name="Flags", value=", ".join(analysis.flags), inline=False
            )
        if analysis.image_hash:
            embed.add_field(
                name="Image Hash", value=analysis.image_hash[:16] + "…"
            )

    try:
        await log_channel.send(embed=embed)
    except discord.Forbidden:
        log.warning("Cannot send to log channel in %s", guild.name)


# ── Cog ────────────────────────────────────────────────────────

class VerificationCog(commands.Cog, name="Verification"):
    """Age verification commands and flows."""

    def __init__(self, bot: AgeGateBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="setup-verify",
        description="Deploy the age verification panel in this channel",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verify(self, interaction: discord.Interaction) -> None:
        config = self.bot.app_config
        guild = interaction.guild
        if not guild:
            return

        # Acknowledge the interaction immediately (must be within 3 seconds)
        await interaction.response.send_message(
            "✅ Verification panel deployed!", ephemeral=True
        )

        # Register guild (async DB work — safe now that interaction is acknowledged)
        await self.bot.database.register_guild(
            guild.id, guild.name, guild.owner_id
        )

        embed = discord.Embed(
            title="🔒 Age Verification Required",
            description=(
                "This server requires age verification to access certain channels.\n\n"
                "**How it works:**\n"
                "1️⃣ Click the button below\n"
                "2️⃣ Follow the instructions in your DMs\n"
                "3️⃣ Submit a photo of your ID with a handwritten note\n"
                "4️⃣ Sign the consent agreement\n"
                "5️⃣ Get verified!\n\n"
                "🔗 **Already verified on another server?** Your verification "
                "will be recognized automatically — no need to re-verify!\n\n"
                "🔐 Your privacy is protected. Photos are analyzed by automated "
                "software and immediately deleted. No humans see your ID."
            ),
            color=0x2B2D31,
        )
        embed.set_footer(text=f"Powered by AgeGate | {config.org_name}")

        await interaction.channel.send(embed=embed, view=VerifyButton())

        await self.bot.database.add_audit_entry(
            "PANEL_DEPLOYED", actor_id=interaction.user.id,
            guild_id=guild.id, details=f"Channel: {interaction.channel.name}",
        )

    @app_commands.command(
        name="verify-status",
        description="Check a user's verification status",
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def verify_status(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        verification = await self.bot.database.get_verification(user.id)
        agreement = await self.bot.database.get_agreement(user.id)
        guilds = await self.bot.database.get_user_guilds(user.id)

        if not verification:
            await interaction.followup.send(
                f"❌ {user.mention} has not been verified.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"📋 Verification Status — {user.name}",
            color=0x57F287 if agreement else 0xFEE75C,
        )
        embed.add_field(name="User ID", value=str(user.id))
        embed.add_field(name="Verified", value=verification["verified_at"][:10])
        if verification.get("age_detected"):
            embed.add_field(name="Age", value=str(verification["age_detected"]))
        embed.add_field(
            name="Tamper Score", value=f"{verification.get('tamper_score', 0):.4f}"
        )

        if agreement:
            status = "🟢 Active" if not agreement.get("revoked") else "🔴 Revoked"
            embed.add_field(name="Agreement", value=agreement["agreement_id"])
            embed.add_field(name="Status", value=status)

        if guilds:
            guild_list = ", ".join(g["guild_name"] for g in guilds[:10])
            embed.add_field(
                name=f"Servers ({len(guilds)})", value=guild_list, inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="verify-stats",
        description="Show verification statistics",
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def verify_stats(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            return

        await interaction.response.defer(ephemeral=True)

        local = await self.bot.database.get_guild_stats(guild.id)
        global_stats = await self.bot.database.get_global_stats()

        embed = discord.Embed(title="📊 Verification Statistics", color=0x5865F2)
        embed.add_field(
            name="This Server",
            value=(
                f"Verified: {local['total_verified']}\n"
                f"With Agreement: {local['with_agreement']}"
            ),
        )
        embed.add_field(
            name="Global",
            value=(
                f"Verifications: {global_stats['total_verifications']}\n"
                f"Agreements: {global_stats['total_agreements']}\n"
                f"Servers: {global_stats['total_guilds']}"
            ),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: AgeGateBot) -> None:
    await bot.add_cog(VerificationCog(bot))
