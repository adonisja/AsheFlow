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

from services.api_client import api
from services.guild_config import get_guild_config, get_company_id_for_guild

logger = logging.getLogger(__name__)


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

        company_id = get_company_id_for_guild(guild.id)
        if company_id is None:
            await interaction.followup.send(
                "This server is not linked to an AsheFlow company. "
                "Configure Discord settings in the super admin panel first.",
                ephemeral=True,
            )
            return

        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            await interaction.followup.send(
                "Discord integration is not configured for this company.", ephemeral=True
            )
            return

        privileged_role_ids = cfg.privileged_role_ids()

        errors: list[str] = []
        applied: list[str] = []

        async def lock_channel(
            channel: discord.TextChannel,
            allowed_role_ids: list[int],
        ) -> None:
            """Deny @everyone, grant privileged roles + allowed_role_ids."""
            try:
                await channel.set_permissions(guild.default_role, view_channel=False)
                for role_id in privileged_role_ids + allowed_role_ids:
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
        if cfg.drivers_channel_id:
            drivers_channel = guild.get_channel(cfg.drivers_channel_id)
            if drivers_channel:
                extra = [cfg.role_driver] if cfg.role_driver else []
                await lock_channel(drivers_channel, extra)
            else:
                errors.append(f"#drivers-chat ({cfg.drivers_channel_id}): not found")
        else:
            errors.append("drivers_channel_id not configured")

        # ── #trainers-chat ────────────────────────────────────────────────
        if cfg.trainers_channel_id:
            trainers_channel = guild.get_channel(cfg.trainers_channel_id)
            if trainers_channel:
                extra = [cfg.role_captain] if cfg.role_captain else []
                await lock_channel(trainers_channel, extra)
            else:
                errors.append(f"#trainers-chat ({cfg.trainers_channel_id}): not found")
        else:
            errors.append("trainers_channel_id not configured")

        # ── Truck channels ────────────────────────────────────────────────
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
            interaction.user, applied, errors,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
