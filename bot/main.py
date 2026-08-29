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

    async def trigger_finalize(
        self, dispatch_date: str, company_id: str, truck_id: str | None = None
    ) -> None:
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot finalize.")
            return
        await dispatch_cog.finalize_assignments(dispatch_date, company_id, truck_id)

    async def trigger_hub_finalize(self, payload: dict) -> None:
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot finalize hub.")
            return
        await dispatch_cog.hub_finalize_truck(payload)

    async def trigger_crew_embed_update(self, payload: dict) -> None:
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot update crew embed.")
            return
        await dispatch_cog.update_crew_embed(payload)

    async def trigger_swap(
        self,
        company_id: str,
        discord_id: str | None,
        employee_name: str,
        old_channel_id: int | None,
        new_channel_id: int | None,
        truck_name: str,
        dispatch_date: str,
        announce: bool = True,
        transfer_context: dict | None = None,
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
            announce=announce,
            transfer_context=transfer_context,
        )

    async def trigger_role_sync(self, discord_id: str, company_id: str, action: str) -> None:
        dispatch_cog = self.cogs.get("Dispatch")
        if dispatch_cog is None:
            logger.error("Dispatch cog not loaded — cannot process role-sync.")
            return
        await dispatch_cog.sync_role(discord_id, company_id, action)

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
    """POST /internal/finalize

    body: { "date": "YYYY-MM-DD", "company_id": "...", "truck_id": "..."|null }

    ADR-325 D1 — `truck_id` scopes the run to one truck; null/absent means the
    whole day. It was absent from this contract while the backend had already
    gained a per-truck finalize, so finalizing one truck posted a crew embed
    into every truck's room.
    """
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    dispatch_date = data.get("date")
    company_id = data.get("company_id")
    truck_id = data.get("truck_id")
    if not dispatch_date or not company_id:
        return web.Response(status=400, text="Missing date or company_id")

    asyncio.create_task(bot.trigger_finalize(dispatch_date, company_id, truck_id))
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


async def handle_resolve_users(request: web.Request) -> web.Response:
    """POST /internal/resolve-users  body: { "discord_ids": ["123", ...] }

    Returns { "<id>": "<display name>" } for every id the bot can see.

    CACHE ONLY — deliberately no `fetch_user` fallback (ADR-267). `intents.members`
    is on, so `get_user` is an in-memory lookup: a pool of thirty costs nothing
    and cannot be rate-limited. `fetch_user` is one Discord API call per id, and
    doing that on a page load for an arbitrary-length list is how you get a
    dispatcher staring at a spinner during the emergency the list exists for.

    An id the cache does not hold is simply omitted; the caller falls back to
    showing the raw id, which is what it did before this endpoint existed.
    """
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    ids = data.get("discord_ids") or []
    if not isinstance(ids, list):
        return web.Response(status=400, text="discord_ids must be a list")

    # Bound the work: a caller asking for thousands is a bug, not a use case.
    resolved: dict[str, str] = {}
    for raw in ids[:200]:
        if not isinstance(raw, str) or not raw.isdigit():
            continue
        user = bot.get_user(int(raw))
        if user is not None:
            resolved[raw] = user.global_name or user.name

    return web.json_response({"users": resolved})


async def handle_swap(request: web.Request) -> web.Response:
    """POST /internal/swap

    body: {
        "company_id":     "...",
        "discord_id":     "..." | null,
        "employee_name":  "...",
        "old_channel_id": 123 | null,
        "new_channel_id": 123 | null,
        "truck_name":     "...",
        "dispatch_date":  "YYYY-MM-DD",
        "announce":       true | false   (default true)
    }

    Adjusts Discord channel permissions for a post-finalize mutation:
    - swap: removes old overwrite, grants new, posts @mention (announce=true)
    - add:  grants new channel only, no announcement (announce=false)
    - remove: removes old overwrite only, no new channel
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

    discord_id        = data.get("discord_id")
    old_channel_id    = int(data["old_channel_id"]) if data.get("old_channel_id") else None
    new_channel_id    = int(data["new_channel_id"]) if data.get("new_channel_id") else None
    announce          = data.get("announce", True)
    transfer_context  = data.get("transfer_context")  # present only for truck_transfer calls

    asyncio.create_task(bot.trigger_swap(
        company_id=company_id,
        discord_id=discord_id,
        employee_name=employee_name,
        old_channel_id=old_channel_id,
        new_channel_id=new_channel_id,
        truck_name=truck_name,
        dispatch_date=dispatch_date,
        announce=announce,
        transfer_context=transfer_context,
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


async def handle_revoke_member(request: web.Request) -> web.Response:
    """POST /internal/revoke-member

    body: { "discord_id": "...", "channel_id": "...", "company_id": "..." }

    Removes a member's permission overwrite from a truck channel immediately.
    Used when a trainee declines their assignment or is marked NCNS after
    finalization has already granted channel access.
    """
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data       = await request.json()
    discord_id = data.get("discord_id")
    channel_id = data.get("channel_id")
    company_id = data.get("company_id")

    if not discord_id or not channel_id or not company_id:
        return web.Response(status=400, text="Missing discord_id, channel_id, or company_id")

    cfg = await get_guild_config(company_id)
    if not cfg or not cfg.is_configured:
        return web.json_response({"status": "no_guild_config"})

    guild = bot.get_guild(cfg.guild_id)
    if not guild:
        return web.json_response({"status": "guild_not_found"})

    dispatch_cog = bot.cogs.get("Dispatch")
    if not dispatch_cog:
        return web.Response(status=503, text="Dispatch cog not loaded")

    asyncio.create_task(dispatch_cog.revoke_member_from_channel(discord_id, int(channel_id)))
    return web.json_response({"status": "queued", "discord_id": discord_id, "channel_id": channel_id})


async def handle_role_sync(request: web.Request) -> web.Response:
    """POST /internal/role-sync

    body: { "discord_id": "...", "company_id": "...",
             "action": "grant_trainer"|"revoke_trainer"|"grant_captain"|"revoke_captain" }

    Grants or revokes the Captain (trainer) Discord role for the given member.
    """
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data       = await request.json()
    discord_id = data.get("discord_id")
    company_id = data.get("company_id")
    action     = data.get("action")

    if not discord_id or not company_id or action not in (
        "grant_trainer", "revoke_trainer", "grant_captain", "revoke_captain",
    ):
        return web.Response(status=400, text="Missing or invalid fields")

    asyncio.create_task(bot.trigger_role_sync(discord_id, company_id, action))
    return web.json_response({"status": "queued"})


async def handle_hub_finalize(request: web.Request) -> web.Response:
    """POST /internal/hub-finalize

    body: {
        "date":               "YYYY-MM-DD",
        "company_id":         "...",
        "truck_id":           "...",
        "truck_name":         "...",
        "discord_channel_id": "123" | null,
        "crew": [{ "employee_id": "...", "name": "...", "role": "...",
                   "discord_id": "...", "paired_trainer_id": "..." | null }]
    }

    Posts the hub crew embed to the truck's Discord channel and sends DMs.
    """
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    dispatch_date = data.get("date")
    company_id    = data.get("company_id")
    if not dispatch_date or not company_id:
        return web.Response(status=400, text="Missing date or company_id")

    asyncio.create_task(bot.trigger_hub_finalize(data))
    return web.json_response({"status": "queued", "date": dispatch_date})


async def handle_crew_embed_update(request: web.Request) -> web.Response:
    """POST /internal/crew-embed-update  (ADR-295 D3)

    body: {
        "company_id", "date", "truck_id", "truck_name",
        "discord_channel_id", "message_id": int | null,
        "crew": [ ... ],                 # roster AS IT NOW STANDS
        "change": {"verb": "added"|"removed", "employee_name": "..."}
    }

    Edits the truck's posted crew embed in place and posts a one-line notice
    saying it changed.
    """
    if not _check_secret(request):
        return web.Response(status=401, text="Unauthorized")

    data = await request.json()
    if not data.get("company_id") or not data.get("date"):
        return web.Response(status=400, text="Missing company_id or date")

    asyncio.create_task(bot.trigger_crew_embed_update(data))
    return web.json_response({"status": "queued"})


async def start_webhook_server() -> None:
    app = web.Application()
    app.router.add_post("/internal/publish",          handle_publish)
    app.router.add_post("/internal/finalize",         handle_finalize)
    app.router.add_post("/internal/hub-finalize",     handle_hub_finalize)
    app.router.add_post("/internal/crew-embed-update", handle_crew_embed_update)
    app.router.add_post("/internal/role-sync",        handle_role_sync)
    app.router.add_post("/internal/swap",             handle_swap)
    app.router.add_post("/internal/alert",            handle_alert)
    app.router.add_post("/internal/lockdown-channel", handle_lockdown_channel)
    app.router.add_post("/internal/invite",           handle_invite)
    app.router.add_post("/internal/revoke-member",    handle_revoke_member)
    app.router.add_post("/internal/dm",               handle_dm)
    app.router.add_post("/internal/resolve-users",    handle_resolve_users)
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
