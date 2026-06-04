"""AsheFlow Discord Bot — entry point.

Loads all cogs and starts the bot. The bot listens for internal webhook
events fired by the backend when dispatch coordinators take action in the
web app.

Guild configuration (guild/channel/role IDs) is fetched per-company from
the backend's /internal/guild-config/{company_id} endpoint and cached for
5 minutes.  This allows one bot token to serve multiple DSP tenants, each
with their own Discord server.
"""

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands

from config import settings
from services.api_client import api
from services.guild_config import get_guild_config, get_company_id_for_guild

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
        # Sync slash commands to all guilds the bot is in
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info("Synced %d slash command(s) to guild %s.", len(synced), guild.id)
            except Exception as e:
                logger.error("Failed to sync slash commands to guild %s: %s", guild.id, e)

    async def close(self) -> None:
        await api.close()
        await super().close()

    # ------------------------------------------------------------------
    # Member join — welcome to general, assign roles
    # ------------------------------------------------------------------

    _ROLE_MAP: dict[str, str] = {
        "driver":     "role_driver",
        "walker":     "role_walker",
        "trainer":    "role_captain",
        "trainee":    "role_walker",
        "dispatch":   "role_dispatch",
        "management": "role_manager",
        "admin":      "role_admin",
    }

    async def on_member_join(self, member: discord.Member) -> None:
        guild_id = member.guild.id
        company_id = get_company_id_for_guild(guild_id)
        if company_id is None:
            logger.debug("on_member_join: guild %s has no mapped company — skipping.", guild_id)
            return

        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            return

        guild = self.get_guild(cfg.guild_id)
        if not guild or member.guild.id != guild.id:
            return

        roles_to_assign: list[discord.Role] = []

        if cfg.role_asheflow:
            base_role = guild.get_role(cfg.role_asheflow)
            if base_role:
                roles_to_assign.append(base_role)

        employee = await api.get_employee_by_discord(str(member.id))
        if employee:
            role_attr = self._ROLE_MAP.get(employee.get("role", ""))
            if role_attr:
                job_role_id = getattr(cfg, role_attr, None)
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

        if cfg.general_channel_id:
            general = guild.get_channel(cfg.general_channel_id)
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
    # Internal publish trigger
    # ------------------------------------------------------------------

    async def trigger_publish(self, dispatch_date: str, company_id: str) -> None:
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot publish.")
            return
        await dispatch_cog.publish_assignments(dispatch_date, company_id)

    async def trigger_lockdown_channel(self, channel_id: int, company_id: str) -> None:
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot lockdown channel.")
            return

        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            logger.info("Lockdown skipped for company %s — Discord not configured.", company_id)
            return

        guild = self.get_guild(cfg.guild_id)
        if not guild:
            logger.error("Guild %s not found for channel lockdown.", cfg.guild_id)
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            logger.warning("Channel %s not found for lockdown.", channel_id)
            return

        try:
            await dispatch_cog._set_truck_channel_permissions(guild, channel, confirmed_crew=[], cfg=cfg)
            logger.info("Locked down channel %s (truck deactivated).", channel_id)
        except Exception as e:
            logger.error("Failed to lockdown channel %s: %s", channel_id, e)

    async def trigger_finalize(self, dispatch_date: str, company_id: str) -> None:
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot finalize.")
            return
        await dispatch_cog.finalize_assignments(dispatch_date, company_id)

    async def trigger_swap(
        self,
        company_id: str,
        discord_id: str | None,
        employee_name: str,
        old_channel_id: int | None,
        new_channel_id: int | None,
        truck_name: str,
        dispatch_date: str,
    ) -> None:
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot process swap.")
            return
        await dispatch_cog.swap_truck_channel(
            company_id=company_id,
            discord_id=discord_id,
            employee_name=employee_name,
            old_channel_id=old_channel_id,
            new_channel_id=new_channel_id,
            truck_name=truck_name,
            dispatch_date=dispatch_date,
        )

    async def trigger_dm(self, discord_id: str, message: str) -> None:
        invite_cog = self.cogs.get("Invite")
        if invite_cog is None:
            logger.error("Invite cog not loaded — cannot send DM to %s.", discord_id)
            return
        await invite_cog.send_dm(discord_id, message)

    async def create_invite_url(self, name: str, company_id: str) -> str | None:
        invite_cog = self.cogs.get("Invite")
        if invite_cog is None:
            logger.error("Invite cog not loaded — cannot create invite for %s.", name)
            return None
        return await invite_cog.create_guild_invite(name, company_id)


bot = AsheFlowBot()


# ---------------------------------------------------------------------------
# Internal webhook server — receives triggers from the backend
# ---------------------------------------------------------------------------

from aiohttp import web


def _check_secret(request: web.Request) -> bool:
    return request.headers.get("X-Internal-Secret", "") == os.environ.get("INTERNAL_SECRET", "")


async def handle_publish(request: web.Request) -> web.Response:
    """POST /internal/publish  body: { "date": "YYYY-MM-DD", "company_id": "..." }"""
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    dispatch_date = data.get("date")
    company_id = data.get("company_id")
    if not dispatch_date or not company_id:
        return web.Response(status=400, text="Missing date or company_id")

    asyncio.create_task(bot.trigger_publish(dispatch_date, company_id))
    return web.json_response({"status": "queued", "date": dispatch_date})


async def handle_invite(request: web.Request) -> web.Response:
    """POST /internal/invite  body: { "name": "...", "company_id": "..." }"""
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    name = data.get("name", "New Employee")
    company_id = data.get("company_id")
    if not company_id:
        return web.Response(status=400, text="Missing company_id")

    invite_url = await bot.create_invite_url(name, company_id)
    if not invite_url:
        return web.Response(status=502, text="Failed to create guild invite")

    return web.json_response({"invite_url": invite_url})


async def handle_lockdown_channel(request: web.Request) -> web.Response:
    """POST /internal/lockdown-channel  body: { "channel_id": 123, "company_id": "..." }"""
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    channel_id = data.get("channel_id")
    company_id = data.get("company_id")
    if not channel_id or not company_id:
        return web.Response(status=400, text="Missing channel_id or company_id")

    asyncio.create_task(bot.trigger_lockdown_channel(int(channel_id), company_id))
    return web.json_response({"status": "queued", "channel_id": channel_id})


async def handle_alert(request: web.Request) -> web.Response:
    """POST /internal/alert  body: { "date": "YYYY-MM-DD", "message": "...", "company_id": "..." }"""
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    message = data.get("message", "")
    company_id = data.get("company_id")
    if not message or not company_id:
        return web.Response(status=400, text="Missing message or company_id")

    cfg = await get_guild_config(company_id)
    if cfg and cfg.is_configured and cfg.drivers_channel_id:
        guild = bot.get_guild(cfg.guild_id)
        if guild:
            channel = guild.get_channel(cfg.drivers_channel_id)
            if channel:
                asyncio.create_task(channel.send(f"🕘 {message}"))

    return web.json_response({"status": "ok"})


async def handle_finalize(request: web.Request) -> web.Response:
    """POST /internal/finalize  body: { "date": "YYYY-MM-DD", "company_id": "..." }"""
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    dispatch_date = data.get("date")
    company_id = data.get("company_id")
    if not dispatch_date or not company_id:
        return web.Response(status=400, text="Missing date or company_id")

    asyncio.create_task(bot.trigger_finalize(dispatch_date, company_id))
    return web.json_response({"status": "queued", "date": dispatch_date})


async def handle_dm(request: web.Request) -> web.Response:
    """POST /internal/dm  body: { "discord_id": "...", "message": "..." }"""
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    discord_id = data.get("discord_id")
    message = data.get("message", "")
    if not discord_id or not message:
        return web.Response(status=400, text="Missing discord_id or message")

    asyncio.create_task(bot.trigger_dm(discord_id, message))
    return web.json_response({"status": "queued", "discord_id": discord_id})


async def handle_swap(request: web.Request) -> web.Response:
    """POST /internal/swap

    body: {
        "company_id":     "...",
        "discord_id":     "..." | null,
        "employee_name":  "...",
        "old_channel_id": 123 | null,
        "new_channel_id": 123 | null,
        "truck_name":     "...",
        "dispatch_date":  "YYYY-MM-DD"
    }

    Removes the member from their old truck channel, grants them access to the
    new one, and posts a tagged announcement in the new channel.
    Only called for post-finalize swaps (completed phase).
    """
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    company_id    = data.get("company_id")
    dispatch_date = data.get("dispatch_date")
    employee_name = data.get("employee_name", "Unknown")
    truck_name    = data.get("truck_name", "Unknown Truck")
    if not company_id or not dispatch_date:
        return web.Response(status=400, text="Missing company_id or dispatch_date")

    discord_id    = data.get("discord_id")
    old_channel_id = int(data["old_channel_id"]) if data.get("old_channel_id") else None
    new_channel_id = int(data["new_channel_id"]) if data.get("new_channel_id") else None

    asyncio.create_task(bot.trigger_swap(
        company_id=company_id,
        discord_id=discord_id,
        employee_name=employee_name,
        old_channel_id=old_channel_id,
        new_channel_id=new_channel_id,
        truck_name=truck_name,
        dispatch_date=dispatch_date,
    ))
    return web.json_response({"status": "queued", "employee_name": employee_name})


async def handle_post_to_channel(request: web.Request) -> web.Response:
    """POST /internal/post-to-channel  body: { "channel_id": 123, "message": "...", "company_id": "..." }"""
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    channel_id = data.get("channel_id")
    message = data.get("message", "")
    company_id = data.get("company_id")
    if not channel_id or not message or not company_id:
        return web.Response(status=400, text="Missing channel_id, message, or company_id")

    cfg = await get_guild_config(company_id)
    if cfg and cfg.is_configured:
        guild = bot.get_guild(cfg.guild_id)
        if guild:
            channel = guild.get_channel(int(channel_id))
            if channel:
                asyncio.create_task(channel.send(message))

    return web.json_response({"status": "ok"})


async def handle_post_embed(request: web.Request) -> web.Response:
    """POST /internal/post-embed  body: { "channel_id": 123, "title": "...", "company_id": "...", ... }"""
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    channel_id = data.get("channel_id")
    title = data.get("title", "")
    company_id = data.get("company_id")
    if not channel_id or not title or not company_id:
        return web.Response(status=400, text="Missing channel_id, title, or company_id")

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

    cfg = await get_guild_config(company_id)
    if cfg and cfg.is_configured:
        guild = bot.get_guild(cfg.guild_id)
        if guild:
            channel = guild.get_channel(int(channel_id))
            if channel:
                asyncio.create_task(channel.send(embed=embed))

    return web.json_response({"status": "ok"})


async def start_webhook_server() -> None:
    app = web.Application()
    app.router.add_post("/internal/publish",          handle_publish)
    app.router.add_post("/internal/finalize",         handle_finalize)
    app.router.add_post("/internal/swap",             handle_swap)
    app.router.add_post("/internal/alert",            handle_alert)
    app.router.add_post("/internal/lockdown-channel", handle_lockdown_channel)
    app.router.add_post("/internal/invite",           handle_invite)
    app.router.add_post("/internal/dm",               handle_dm)
    app.router.add_post("/internal/post-to-channel",  handle_post_to_channel)
    app.router.add_post("/internal/post-embed",       handle_post_embed)
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
