"""Invite cog — sends Discord guild invite links to newly activated employees.

Triggered by the backend via POST /internal/invite after an employee's first
login transitions their account from pending_verification → active.
"""

import logging

import discord
from discord.ext import commands

from config import settings

logger = logging.getLogger(__name__)


class InviteCog(commands.Cog, name="Invite"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def send_dm(self, discord_id: str, message: str) -> None:
        """Send a plain DM to a user by Discord ID.

        Used for graduation notifications and other system events.
        Failures are logged but do not raise.
        """
        try:
            user = await self.bot.fetch_user(int(discord_id))
        except (discord.NotFound, discord.HTTPException, ValueError) as e:
            logger.warning("Could not fetch Discord user %s for DM: %s", discord_id, e)
            return
        try:
            await user.send(message)
            logger.info("DM sent to Discord user %s.", discord_id)
        except discord.Forbidden:
            logger.warning("Could not DM user %s — DMs may be disabled.", discord_id)
        except discord.HTTPException as e:
            logger.error("Failed to DM user %s: %s", discord_id, e)

    async def send_guild_invite(self, discord_id: str, name: str) -> None:
        """DM a one-time guild invite link to the employee.

        Steps:
        1. Fetch the guild and its invite channel (uses the drivers channel
           as the landing channel — change DISCORD_INVITE_CHANNEL_ID in .env
           if you want a dedicated #welcome channel).
        2. Create a single-use, 7-day invite.
        3. DM the invite to the user by their Discord ID.

        Failures are logged but do not raise — the account is already active
        in the DB so a failed invite is recoverable (admin can resend manually).
        """
        guild = self.bot.get_guild(settings.discord_guild_id)
        if not guild:
            logger.error("Guild %s not found — cannot send invite to %s.", settings.discord_guild_id, discord_id)
            return

        # Use the configured invite channel, falling back to the drivers channel
        invite_channel_id = getattr(settings, "discord_invite_channel_id", None) or settings.discord_drivers_channel_id
        channel = guild.get_channel(int(invite_channel_id))
        if not channel:
            logger.error("Invite channel %s not found — cannot create invite.", invite_channel_id)
            return

        try:
            invite = await channel.create_invite(
                max_uses=1,
                max_age=7 * 24 * 3600,  # 7 days in seconds
                unique=True,
                reason=f"New employee onboarding: {name}",
            )
        except discord.Forbidden:
            logger.error("Bot lacks permission to create invites in channel %s.", invite_channel_id)
            return
        except discord.HTTPException as e:
            logger.error("Failed to create guild invite: %s", e)
            return

        try:
            user = await self.bot.fetch_user(int(discord_id))
        except (discord.NotFound, discord.HTTPException, ValueError) as e:
            logger.warning("Could not fetch Discord user %s (%s): %s", discord_id, name, e)
            return

        message = (
            f"Hi **{name}**! Your AsheFlow account is now active.\n\n"
            f"Use this link to join the server: {invite.url}\n\n"
            f"This invite is single-use and expires in 7 days."
        )

        try:
            await user.send(message)
            logger.info("Guild invite sent to %s (%s).", name, discord_id)
        except discord.Forbidden:
            logger.warning("Could not DM %s (%s) — DMs may be disabled.", name, discord_id)
        except discord.HTTPException as e:
            logger.error("Failed to DM invite to %s (%s): %s", name, discord_id, e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InviteCog(bot))
