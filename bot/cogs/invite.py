"""Invite cog — sends Discord guild invite links to newly activated employees.

Triggered by the backend via POST /internal/invite after an employee's first
login transitions their account from pending_verification → active.
"""

import logging

import discord
from discord.ext import commands

from services.guild_config import get_guild_config

logger = logging.getLogger(__name__)


class InviteCog(commands.Cog, name="Invite"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def send_dm(self, discord_id: str, message: str) -> None:
        """Send a plain DM to a user by Discord ID."""
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

    async def create_guild_invite(self, name: str, company_id: str) -> str | None:
        """Create a single-use, 7-day guild invite for a company's guild and return the URL.

        Returns None if Discord is not configured for the company or invite creation fails.
        """
        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            logger.info("create_guild_invite: Discord not configured for company %s — skipping.", company_id)
            return None

        guild = self.bot.get_guild(cfg.guild_id)
        if not guild:
            logger.error("Guild %s not found — cannot create invite for %s.", cfg.guild_id, name)
            return None

        invite_channel_id = cfg.invite_channel_id or cfg.drivers_channel_id
        if not invite_channel_id:
            logger.error("No invite or drivers channel configured for company %s.", company_id)
            return None

        channel = guild.get_channel(int(invite_channel_id))
        if not channel:
            logger.error("Invite channel %s not found — cannot create invite.", invite_channel_id)
            return None

        try:
            invite = await channel.create_invite(
                max_uses=1,
                max_age=7 * 24 * 3600,
                unique=True,
                reason=f"New employee onboarding: {name}",
            )
            logger.info("Guild invite created for %s: %s", name, invite.url)
            return invite.url
        except discord.Forbidden:
            logger.error("Bot lacks permission to create invites in channel %s.", invite_channel_id)
            return None
        except discord.HTTPException as e:
            logger.error("Failed to create guild invite for %s: %s", name, e)
            return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InviteCog(bot))
