"""AsheFlow Discord Bot — entry point.

Loads all cogs and starts the bot. The bot listens for an internal
`publish_dispatch` event which is fired by the backend when dispatch
coordinator clicks "Publish to Discord" in the web app.
"""

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands

from config import settings
from services.api_client import api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

COGS = [
    "cogs.dispatch",
    "cogs.invite",
    "cogs.setup",
]


class AsheFlowBot(commands.Bot):

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True        # needed to fetch guild members for DMs
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        """Called once before the bot connects — load cogs and start the API client."""
        await api.start()

        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: %s", cog)
            except Exception as e:
                logger.error("Failed to load cog %s: %s", cog, e)

    async def on_ready(self) -> None:
        logger.info("AsheFlow bot ready. Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="dispatch assignments",
            )
        )
        try:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("Synced %d slash command(s) to guild.", len(synced))
        except Exception as e:
            logger.error("Failed to sync slash commands: %s", e)

    async def close(self) -> None:
        await api.close()
        await super().close()

    # ------------------------------------------------------------------
    # Member join — welcome to general, assign roles
    # ------------------------------------------------------------------

    # Maps the AsheFlow employee role to the corresponding Discord role ID.
    _ROLE_MAP: dict[str, str] = {
        "driver":     "discord_role_driver",
        "walker":     "discord_role_walker",
        "trainer":    "discord_role_captain",
        "trainee":    "discord_role_walker",
        "dispatch":   "discord_role_dispatch",
        "management": "discord_role_manager",
        "admin":      "discord_role_admin",
    }

    async def on_member_join(self, member: discord.Member) -> None:
        guild = self.get_guild(settings.discord_guild_id)
        if not guild or member.guild.id != guild.id:
            return

        # Always assign the base AsheFlow member role
        roles_to_assign: list[discord.Role] = []
        base_role = guild.get_role(settings.discord_role_asheflow)
        if base_role:
            roles_to_assign.append(base_role)

        # Look up job role by Discord ID
        employee = await api.get_employee_by_discord(str(member.id))
        if employee:
            role_attr = self._ROLE_MAP.get(employee.get("role", ""))
            if role_attr:
                job_role_id = getattr(settings, role_attr, None)
                if job_role_id:
                    job_role = guild.get_role(job_role_id)
                    if job_role:
                        roles_to_assign.append(job_role)

        if roles_to_assign:
            try:
                await member.add_roles(*roles_to_assign, reason="Auto-assigned on join")
                logger.info("Assigned roles %s to %s", [r.name for r in roles_to_assign], member)
            except discord.HTTPException as e:
                logger.error("Failed to assign roles to %s: %s", member, e)

        # Send welcome message to general channel
        general = guild.get_channel(settings.discord_general_channel_id)
        if general:
            try:
                name = employee.get("name", member.display_name) if employee else member.display_name
                await general.send(
                    f"Welcome to AsheFlow, {member.mention} ({name})! "
                    f"Check your email for your sign-in credentials."
                )
            except discord.HTTPException as e:
                logger.error("Failed to send welcome message: %s", e)

    # ------------------------------------------------------------------
    # Internal publish trigger — called by the backend webhook handler
    # ------------------------------------------------------------------

    async def trigger_publish(self, dispatch_date: str) -> None:
        """Fire the publish flow for a given date.

        Called when the backend receives POST /dispatch/{date}/publish
        and forwards the event to the bot via this method.
        """
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot publish.")
            return
        await dispatch_cog.publish_assignments(dispatch_date)

    async def trigger_lockdown_channel(self, channel_id: int) -> None:
        """Strip all crew overwrites from a channel and restore baseline permissions.

        Called when a truck is deactivated. Reuses the setup cog's lock logic
        so the channel matches the same baseline as /setup-channels would set.
        """
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot lockdown channel.")
            return

        guild = self.get_guild(settings.discord_guild_id)
        if not guild:
            logger.error("Guild not found for channel lockdown.")
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            logger.warning("Channel %s not found for lockdown.", channel_id)
            return

        try:
            await dispatch_cog._set_truck_channel_permissions(guild, channel, confirmed_crew=[])
            logger.info("Locked down channel %s (truck deactivated).", channel_id)
        except Exception as e:
            logger.error("Failed to lockdown channel %s: %s", channel_id, e)

    async def trigger_finalize(self, dispatch_date: str) -> None:
        """Fire the finalization flow for a given date.

        Called when dispatch clicks "Finalize" in the web app (~09:10 AM).
        Posts confirmed crew to each truck channel, sets per-day permissions,
        and posts the master driver list to #drivers-chat.
        """
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot finalize.")
            return
        await dispatch_cog.finalize_assignments(dispatch_date)

    async def trigger_dm(self, discord_id: str, message: str) -> None:
        """Send a plain DM to a Discord user by ID.

        Called when the backend fires POST /internal/dm — used for graduation
        notifications, role-change confirmations, and similar system events.
        """
        invite_cog = self.cogs.get("Invite")
        if invite_cog is None:
            logger.error("Invite cog not loaded — cannot send DM to %s.", discord_id)
            return
        await invite_cog.send_dm(discord_id, message)

    async def create_invite_url(self, name: str) -> str | None:
        """Create a guild invite URL for a newly activated employee.

        Returns the invite URL so the caller (handle_invite) can return it
        to the backend, which emails it to the employee.
        """
        invite_cog = self.cogs.get("Invite")
        if invite_cog is None:
            logger.error("Invite cog not loaded — cannot create invite for %s.", name)
            return None
        return await invite_cog.create_guild_invite(name)


bot = AsheFlowBot()


# ---------------------------------------------------------------------------
# Internal webhook server — receives publish triggers from the backend
# ---------------------------------------------------------------------------

from aiohttp import web

async def handle_publish(request: web.Request) -> web.Response:
    """POST /internal/publish  body: { "date": "YYYY-MM-DD" }"""
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("INTERNAL_SECRET", ""):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    dispatch_date = data.get("date")
    if not dispatch_date:
        return web.Response(status=400, text="Missing date")

    asyncio.create_task(bot.trigger_publish(dispatch_date))
    return web.json_response({"status": "queued", "date": dispatch_date})


async def handle_invite(request: web.Request) -> web.Response:
    """POST /internal/invite  body: { "name": "..." }

    Called by the backend when a new employee activates their account on
    first login. Creates a single-use guild invite and returns the URL so
    the backend can email it to the employee. Discord DMs are not used —
    the bot cannot DM users who don't already share a server with it.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("INTERNAL_SECRET", ""):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    name = data.get("name", "New Employee")

    invite_url = await bot.create_invite_url(name)
    if not invite_url:
        return web.Response(status=502, text="Failed to create guild invite")

    return web.json_response({"invite_url": invite_url})


async def handle_lockdown_channel(request: web.Request) -> web.Response:
    """POST /internal/lockdown-channel  body: { "channel_id": 1234567890 }

    Strips all member-level permission overwrites from a truck channel and
    re-applies the baseline (privileged roles only, @everyone denied).
    Called when a truck is deactivated so yesterday's crew loses access.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("INTERNAL_SECRET", ""):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    channel_id = data.get("channel_id")
    if not channel_id:
        return web.Response(status=400, text="Missing channel_id")

    asyncio.create_task(bot.trigger_lockdown_channel(int(channel_id)))
    return web.json_response({"status": "queued", "channel_id": channel_id})


async def handle_alert(request: web.Request) -> web.Response:
    """POST /internal/alert  body: { "date": "YYYY-MM-DD", "message": "..." }

    Posts a plain-text alert to #drivers-chat. Used by the Celery 09:05 reminder.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("INTERNAL_SECRET", ""):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    message = data.get("message", "")
    if not message:
        return web.Response(status=400, text="Missing message")

    guild = bot.get_guild(settings.discord_guild_id)
    if guild:
        channel = guild.get_channel(settings.discord_drivers_channel_id)
        if channel:
            asyncio.create_task(channel.send(f"🕘 {message}"))

    return web.json_response({"status": "ok"})


async def handle_finalize(request: web.Request) -> web.Response:
    """POST /internal/finalize  body: { "date": "YYYY-MM-DD" }

    Called by the backend when dispatch clicks "Finalize" (~09:10 AM).
    Posts finalized crew assignments to truck channels and #drivers-chat.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("INTERNAL_SECRET", ""):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    dispatch_date = data.get("date")
    if not dispatch_date:
        return web.Response(status=400, text="Missing date")

    asyncio.create_task(bot.trigger_finalize(dispatch_date))
    return web.json_response({"status": "queued", "date": dispatch_date})


async def handle_dm(request: web.Request) -> web.Response:
    """POST /internal/dm  body: { "discord_id": "...", "message": "..." }

    Sends a plain DM to a Discord user by their Discord ID (snowflake string).
    Used for graduation notifications, role-change confirmations, etc.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("INTERNAL_SECRET", ""):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    discord_id = data.get("discord_id")
    message = data.get("message", "")
    if not discord_id or not message:
        return web.Response(status=400, text="Missing discord_id or message")

    asyncio.create_task(bot.trigger_dm(discord_id, message))
    return web.json_response({"status": "queued", "discord_id": discord_id})


async def handle_post_to_channel(request: web.Request) -> web.Response:
    """POST /internal/post-to-channel  body: { "channel_id": 123, "message": "..." }

    Posts a plain-text message to any guild channel by ID.
    Used by the backend for anchor point submissions and other driver-initiated
    events that need to appear in the truck's Discord channel.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("INTERNAL_SECRET", ""):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    channel_id = data.get("channel_id")
    message = data.get("message", "")
    if not channel_id or not message:
        return web.Response(status=400, text="Missing channel_id or message")

    guild = bot.get_guild(settings.discord_guild_id)
    if guild:
        channel = guild.get_channel(int(channel_id))
        if channel:
            asyncio.create_task(channel.send(message))

    return web.json_response({"status": "ok"})


async def handle_post_embed(request: web.Request) -> web.Response:
    """POST /internal/post-embed

    Body:
    {
        "channel_id": 123456789,
        "title": "...",
        "description": "...",      # optional
        "color": 0x00ff00,         # optional, defaults to 0x5865F2 (Discord blurple)
        "fields": [                # optional
            { "name": "Label", "value": "text", "inline": true }
        ],
        "footer": "..."            # optional
    }

    Posts a rich Discord embed to the given channel.
    Used by the backend for anchor point events so the truck room sees
    nicely formatted AP updates.
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("INTERNAL_SECRET", ""):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    channel_id = data.get("channel_id")
    title = data.get("title", "")
    if not channel_id or not title:
        return web.Response(status=400, text="Missing channel_id or title")

    embed = discord.Embed(
        title=title,
        description=data.get("description"),
        color=data.get("color", 0x5865F2),
    )
    for field in data.get("fields", []):
        embed.add_field(
            name=field.get("name", ""),
            value=field.get("value", ""),
            inline=field.get("inline", False),
        )
    if footer := data.get("footer"):
        embed.set_footer(text=footer)

    guild = bot.get_guild(settings.discord_guild_id)
    if guild:
        channel = guild.get_channel(int(channel_id))
        if channel:
            asyncio.create_task(channel.send(embed=embed))

    return web.json_response({"status": "ok"})


async def start_webhook_server() -> None:
    app = web.Application()
    app.router.add_post("/internal/publish", handle_publish)
    app.router.add_post("/internal/finalize", handle_finalize)
    app.router.add_post("/internal/alert", handle_alert)
    app.router.add_post("/internal/lockdown-channel", handle_lockdown_channel)
    app.router.add_post("/internal/invite", handle_invite)
    app.router.add_post("/internal/dm", handle_dm)
    app.router.add_post("/internal/post-to-channel", handle_post_to_channel)
    app.router.add_post("/internal/post-embed", handle_post_embed)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8001)
    await site.start()
    logger.info("Internal webhook server listening on :8001")


async def main() -> None:
    async with bot:
        await start_webhook_server()
        await bot.start(settings.discord_bot_token)


if __name__ == "__main__":
    asyncio.run(main())
