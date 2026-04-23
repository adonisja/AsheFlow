"""Setup cog — one-time server permission configuration.

Provides a single admin slash command: /setup-channels

Safe to re-run at any time — overwrites always win (idempotent).

Permission matrix applied:

  Channel          │ Admin │ Manager │ Dispatch │ Driver │ Captain │ Walker │ Trainee
  ─────────────────┼───────┼─────────┼──────────┼────────┼─────────┼────────┼────────
  #drivers-chat    │  R/W  │   R/W   │   R/W    │  R/W   │    -    │   -    │   -
  #trainers-chat   │  R/W  │   R/W   │   R/W    │   -    │   R/W   │   -    │   -
  Truck channels   │  R/W  │   R/W   │   R/W    │   *    │    *    │   *    │   *
  (baseline)

  * Truck channel access for Driver/Captain/Walker/Trainee is NOT set here.
    It is granted per-day at finalization time (only to confirmed crew),
    and left in place until the next finalization overwrites it.

  AsheFlow app role and Bot role: R/W everywhere (same as Admin).
  @everyone: denied on all managed channels.

Run with: /setup-channels   (admin only)
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import settings
from services.api_client import api

logger = logging.getLogger(__name__)

# Roles that always get view + send on ALL channels
PRIVILEGED_ROLE_IDS = [
    settings.discord_role_admin,
    settings.discord_role_manager,
    settings.discord_role_asheflow,
    settings.discord_role_bot,
    settings.discord_role_dispatch,
]


class SetupCog(commands.Cog, name="Setup"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="setup-channels",
        description="[Admin only] Apply baseline channel permissions for the AsheFlow server.",
    )
    @app_commands.default_permissions(administrator=True)
    async def setup_channels(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Must be run inside the server.", ephemeral=True)
            return

        errors: list[str] = []
        applied: list[str] = []

        # ── Helper ────────────────────────────────────────────────────────
        async def lock_channel(
            channel: discord.TextChannel,
            allowed_role_ids: list[int],
        ) -> None:
            """Deny @everyone, grant privileged roles + allowed_role_ids."""
            try:
                await channel.set_permissions(guild.default_role, view_channel=False)
                for role_id in PRIVILEGED_ROLE_IDS + allowed_role_ids:
                    role = guild.get_role(role_id)
                    if role:
                        await channel.set_permissions(
                            role, view_channel=True, send_messages=True
                        )
                applied.append(f"#{channel.name}")
            except discord.Forbidden:
                errors.append(f"#{channel.name}: missing Manage Channel permission")
            except Exception as e:
                errors.append(f"#{channel.name}: {e}")

        # ── #drivers-chat ─────────────────────────────────────────────────
        drivers_channel = guild.get_channel(settings.discord_drivers_channel_id)
        if drivers_channel:
            await lock_channel(drivers_channel, [settings.discord_role_driver])
        else:
            errors.append(f"#drivers-chat ({settings.discord_drivers_channel_id}): not found")

        # ── #trainers-chat ────────────────────────────────────────────────
        trainers_channel = guild.get_channel(settings.discord_trainers_channel_id)
        if trainers_channel:
            await lock_channel(trainers_channel, [settings.discord_role_captain])
        else:
            errors.append(f"#trainers-chat ({settings.discord_trainers_channel_id}): not found")

        # ── Truck channels ────────────────────────────────────────────────
        # Fetch truck list from API to get channel IDs (avoids hardcoding here)
        try:
            trucks = await api.get_trucks()
        except Exception as e:
            errors.append(f"Could not fetch trucks from API: {e}")
            trucks = []

        for truck in trucks:
            channel_id = truck.get("discord_channel_id")
            truck_name = truck.get("name", "Unknown")
            if not channel_id:
                errors.append(f"{truck_name}: no discord_channel_id in DB")
                continue
            truck_channel = guild.get_channel(int(channel_id))
            if not truck_channel:
                errors.append(f"{truck_name}: channel {channel_id} not found in guild")
                continue
            # Truck channels: privileged roles only at baseline.
            # Crew members are granted access per-day at finalization.
            await lock_channel(truck_channel, [])

        # ── Report ────────────────────────────────────────────────────────
        lines = []
        if applied:
            lines.append("**Applied:**\n" + "\n".join(f"  ✅ {c}" for c in applied))
        if errors:
            lines.append("**Errors:**\n" + "\n".join(f"  ❌ {e}" for e in errors))

        result = "\n\n".join(lines) or "Nothing changed."
        await interaction.followup.send(result, ephemeral=True)

        logger.info(
            "setup-channels run by %s. Applied: %s. Errors: %s",
            interaction.user,
            applied,
            errors,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
