"""Dispatch cog — handles the two-phase assignment flow.

Phase 1 — Initial DM (triggered by dispatch clicking "Publish"):
  - Drivers: DM with truck name + Confirm/Decline (deadline 08:20)
  - All other roles: DM with attendance request only, no truck details (deadline 09:00)
  - Declines are immediately surfaced to #drivers-chat so dispatch can backfill.

Phase 2 — Finalization (triggered by dispatch clicking "Finalize" ~09:10):
  - Reads confirmed crew from the API.
  - Clears previous-day permission overwrites on all truck channels.
  - Sets per-day access: only confirmed crew members + permanently privileged roles.
  - Posts crew embed to each truck channel.
  - Posts master driver/truck list to #drivers-chat.
  - Errors are reported back to #drivers-chat so dispatch sees them immediately.
"""

import logging

import discord
from discord.ext import commands

from services.api_client import api
from services.guild_config import GuildConfig, get_guild_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role display config
# ---------------------------------------------------------------------------

ROLE_ORDER = ["driver", "trainer", "trainee", "walker"]
ROLE_LABELS = {
    "driver":  "🚛 Driver",
    "trainer": "🎓 Trainer",
    "trainee": "📋 Trainee",
    "walker":  "🚶 Walker",
}


# ---------------------------------------------------------------------------
# Confirmation button view — sent in Phase 1 DMs
# ---------------------------------------------------------------------------

class ConfirmationView(discord.ui.View):
    """Persistent two-button view: Confirm / Decline."""

    def __init__(
        self,
        dispatch_date: str,
        employee_id: str,
        employee_name: str,
        company_id: str,
    ) -> None:
        super().__init__(timeout=None)
        self.dispatch_date = dispatch_date
        self.employee_id = employee_id
        self.employee_name = employee_name
        self.company_id = company_id

    @discord.ui.button(label="Confirm ✓", style=discord.ButtonStyle.success, custom_id="confirm_yes")
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._record(interaction, "confirmed")

    @discord.ui.button(label="Decline ✗", style=discord.ButtonStyle.danger, custom_id="confirm_no")
    async def decline(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._record(interaction, "declined")

    async def _record(self, interaction: discord.Interaction, status: str) -> None:
        try:
            await api.post_confirmation(self.dispatch_date, self.employee_id, status)
        except Exception as e:
            logger.error("Failed to record confirmation for %s: %s", self.employee_id, e)
            await interaction.response.send_message(
                "⚠️ Something went wrong recording your response. Please contact dispatch.",
                ephemeral=True,
            )
            return

        for item in self.children:
            item.disabled = True

        label = "confirmed ✓" if status == "confirmed" else "declined ✗"
        await interaction.response.edit_message(
            content=f"Response recorded — you **{label}** your assignment for {self.dispatch_date}.",
            view=self,
        )

        if status == "declined":
            cfg = await get_guild_config(self.company_id)
            if cfg and cfg.is_configured and cfg.drivers_channel_id:
                guild = interaction.client.get_guild(cfg.guild_id)
                if guild:
                    channel = guild.get_channel(cfg.drivers_channel_id)
                    if channel:
                        await channel.send(
                            f"⚠️ **{self.employee_name}** has **declined** their assignment for "
                            f"`{self.dispatch_date}`. Dispatch — please review and reassign."
                        )


# ---------------------------------------------------------------------------
# Helpers: phase-lookup for trainer DMs
# ---------------------------------------------------------------------------

async def _fetch_trainee_phases(trainees: list[dict]) -> list[tuple[str, str]]:
    """Return (name, phase_label) for each trainee. Falls back to '?' on error."""
    results = []
    for t in trainees:
        phase = await api.get_trainee_current_phase(t["employee_id"])
        results.append((t["name"], str(phase) if phase is not None else "?"))
    return results


# ---------------------------------------------------------------------------
# Helper: build truck channel crew embed
# ---------------------------------------------------------------------------

def _build_truck_channel_embed(truck_name: str, crew: list[dict], dispatch_date: str) -> discord.Embed:
    SEP = "------------------------------------------"
    COL = 16
    HEADER_WIDTH = 34

    embed = discord.Embed(color=0x5865F2)

    by_role: dict[str, list[str]] = {r: [] for r in ROLE_ORDER}
    for member in crew:
        by_role.setdefault(member.get("role", "walker"), []).append(member["name"])

    def pills_paired(names: list[str]) -> str:
        lines = []
        for i in range(0, len(names), 2):
            pair = names[i:i + 2]
            left  = f"`{pair[0]:<{COL}}`"
            right = f"`{pair[1]:<{COL}}`" if len(pair) == 2 else f"`{'':<{COL}}`"
            lines.append(f"{left} {right}")
        return "\n".join(lines)

    padded_name = f"{truck_name:^{HEADER_WIDTH}}"
    embed.add_field(name="​", value=f"`{padded_name}`\n{SEP}", inline=False)

    drivers  = by_role.get("driver",  [])
    trainers = by_role.get("trainer", [])

    leadership_lines = []
    if drivers:
        leadership_lines.append(f"**Driver:** `{drivers[0]}`")
    if trainers:
        if leadership_lines:
            leadership_lines.append("")
        leadership_lines.append("**Trainers:**")
        leadership_lines.append(pills_paired(trainers))

    if leadership_lines:
        embed.add_field(name="📋 Crew Leadership", value="\n".join(leadership_lines), inline=False)

    walkers = by_role.get("walker", [])
    if walkers:
        embed.add_field(name="​", value=f"{SEP}\n**Walkers:**\n{pills_paired(walkers)}", inline=False)

    trainees = by_role.get("trainee", [])
    if trainees:
        embed.add_field(name="​", value=f"{SEP}\n**Trainees:**\n{pills_paired(trainees)}", inline=False)

    embed.set_footer(text=f"{SEP}\nDispatch date: {dispatch_date}")
    return embed


# ---------------------------------------------------------------------------
# Helper: build the #drivers-chat finalization post
# ---------------------------------------------------------------------------

def _build_drivers_chat_message(trucks_data: list[dict], dispatch_date: str) -> str:
    COL = 16
    SEP = "-" * 38

    inner: list[str] = [f"Finalized Dispatch  {dispatch_date}", SEP]
    for entry in trucks_data:
        truck_name = entry["truck_name"]
        crew = entry["crew"]
        driver = next((m["name"] for m in crew if m["role"] == "driver"), "TBD")
        inner.append(f"{truck_name:<{COL}}  Driver: {driver}")
    inner.append(SEP)
    inner.append("Full crew details posted in each truck's channel.")

    return "✅ **Dispatch Finalized**\n```\n" + "\n".join(inner) + "\n```"


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class DispatchCog(commands.Cog, name="Dispatch"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # PHASE 1 — Initial publish
    # ------------------------------------------------------------------

    async def publish_assignments(self, dispatch_date: str, company_id: str) -> None:
        """Send initial DMs. Drivers get truck name; all others get attendance-only."""
        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            logger.info("publish_assignments: Discord not configured for company %s — skipping.", company_id)
            return

        guild = self.bot.get_guild(cfg.guild_id)
        drivers_channel = guild.get_channel(cfg.drivers_channel_id) if guild and cfg.drivers_channel_id else None

        async def report_error(msg: str) -> None:
            logger.error(msg)
            if drivers_channel:
                await drivers_channel.send(f"⚠️ **Dispatch bot error:** {msg}")

        if not guild:
            await report_error(f"Guild {cfg.guild_id} not found.")
            return
        if not drivers_channel:
            await report_error(f"#drivers-chat channel {cfg.drivers_channel_id} not found.")
            return

        try:
            dispatch = await api.get_dispatch(dispatch_date)
            trucks   = await api.get_trucks()
        except Exception as e:
            await report_error(f"Failed to fetch dispatch data for `{dispatch_date}`: {e}")
            return

        truck_map = {str(t["id"]): t for t in trucks}
        assigned_crews: dict[str, list] = dispatch.get("assigned_crews", {})

        if not assigned_crews:
            await drivers_channel.send(f"No dispatch found for `{dispatch_date}`. Run dispatch first.")
            return

        header = discord.Embed(
            title=f"📋 Dispatch Published — {dispatch_date}",
            description=(
                "Initial assignments have been sent. Crew members: check your DMs.\n"
                "**Driver deadline: 08:20 AM | Crew deadline: 09:00 AM**"
            ),
            color=discord.Color.blurple(),
        )
        await drivers_channel.send(embed=header)

        dm_failures: list[str] = []

        for truck_id, crew in assigned_crews.items():
            truck_info = truck_map.get(truck_id, {})
            truck_name = truck_info.get("name", f"Truck {truck_id[:8]}")

            for member in crew:
                discord_id = member.get("discord_id")
                if not discord_id or not discord_id.isdigit():
                    logger.warning("No snowflake discord_id for %s — skipping DM.", member.get("name"))
                    continue

                try:
                    discord_user = await self.bot.fetch_user(int(discord_id))
                except (discord.NotFound, discord.HTTPException, ValueError) as e:
                    logger.warning("Could not fetch user %s: %s", discord_id, e)
                    dm_failures.append(member["name"])
                    continue

                role = member.get("role", "walker")

                if role == "driver":
                    dm_embed = self._build_driver_dm(truck_name, dispatch_date)
                else:
                    dm_embed = await self._build_crew_dm(member, crew, dispatch_date)

                view = ConfirmationView(
                    dispatch_date=dispatch_date,
                    employee_id=member["employee_id"],
                    employee_name=member["name"],
                    company_id=company_id,
                )

                try:
                    await discord_user.send(embed=dm_embed, view=view)
                except discord.Forbidden:
                    logger.warning("DMs disabled for %s.", member["name"])
                    dm_failures.append(member["name"])

        if dm_failures:
            await drivers_channel.send(
                "⚠️ Could not DM the following (DMs may be disabled): "
                + ", ".join(f"**{n}**" for n in dm_failures)
                + ". Please contact them directly."
            )

        logger.info("Dispatch published for %s. DM failures: %s", dispatch_date, dm_failures)

    def _build_driver_dm(self, truck_name: str, dispatch_date: str) -> discord.Embed:
        return discord.Embed(
            title=f"🚛 Your Assignment — {dispatch_date}",
            description=(
                f"**Truck:** {truck_name}\n"
                f"**Your role:** {ROLE_LABELS.get('driver', 'Driver')}\n\n"
                "Please **confirm** your assignment by **08:20 AM**.\n"
                "After confirming, proceed to sign in on Amazon Flex and head to the offsite."
            ),
            color=discord.Color.blurple(),
        )

    async def _build_crew_dm(self, member: dict, crew: list[dict], dispatch_date: str) -> discord.Embed:
        role = member.get("role", "walker")

        pairing_note = ""
        if role == "trainer":
            trainees_on_crew = [m for m in crew if m["role"] == "trainee"]
            if trainees_on_crew:
                phase_info = await _fetch_trainee_phases(trainees_on_crew)
                lines = "\n".join(f"  📋 **{name}** — Phase {phase}" for name, phase in phase_info)
                pairing_note = f"\n\n📋 **Your trainee(s) today:**\n{lines}"
            else:
                pairing_note = "\n\n*(No trainees on your truck today.)*"
        elif role == "trainee":
            trainers_on_crew = [m for m in crew if m["role"] == "trainer"]
            if trainers_on_crew:
                trainer_names = ", ".join(f"**{m['name']}**" for m in trainers_on_crew)
                pairing_note = f"\n\n🎓 **Your trainer today:** {trainer_names}"
            else:
                pairing_note = "\n\n⚠️ No trainer assigned to your truck — contact dispatch."

        return discord.Embed(
            title=f"📋 Attendance Confirmation — {dispatch_date}",
            description=(
                f"**Your role today:** {ROLE_LABELS.get(role, role)}\n\n"
                "You have been assigned a shift today. Please confirm your attendance.\n"
                "**Deadline: 09:00 AM**\n"
                "Full crew and truck details will be sent after finalization."
                f"{pairing_note}"
            ),
            color=discord.Color.blurple(),
        )

    # ------------------------------------------------------------------
    # PHASE 2 — Finalization
    # ------------------------------------------------------------------

    async def finalize_assignments(self, dispatch_date: str, company_id: str) -> None:
        """Post finalized assignments to truck channels and #drivers-chat."""
        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            logger.info("finalize_assignments: Discord not configured for company %s — skipping.", company_id)
            return

        guild = self.bot.get_guild(cfg.guild_id)
        drivers_channel = guild.get_channel(cfg.drivers_channel_id) if guild and cfg.drivers_channel_id else None

        async def report_error(msg: str) -> None:
            logger.error(msg)
            if drivers_channel:
                await drivers_channel.send(f"⚠️ **Finalization error:** {msg}")

        if not guild:
            await report_error(f"Guild {cfg.guild_id} not found.")
            return
        if not drivers_channel:
            await report_error(f"#drivers-chat {cfg.drivers_channel_id} not found.")
            return

        try:
            dispatch = await api.get_dispatch(dispatch_date)
            trucks   = await api.get_trucks()
            confs    = await api.get_confirmations(dispatch_date)
        except Exception as e:
            await report_error(f"Failed to fetch data for `{dispatch_date}`: {e}")
            return

        truck_map = {str(t["id"]): t for t in trucks}
        assigned_crews: dict[str, list] = dispatch.get("assigned_crews", {})
        confirmations: dict[str, str] = confs.get("confirmations", {})

        if not assigned_crews:
            await drivers_channel.send(f"No dispatch found for `{dispatch_date}` — nothing to finalize.")
            return

        trucks_summary: list[dict] = []
        channel_errors: list[str]  = []

        for truck_id, full_crew in assigned_crews.items():
            truck_info = truck_map.get(truck_id, {})
            truck_name = truck_info.get("name", f"Truck {truck_id[:8]}")
            channel_id = truck_info.get("discord_channel_id")

            confirmed_crew = [
                m for m in full_crew
                if confirmations.get(m["employee_id"], "pending") == "confirmed"
            ]

            trucks_summary.append({"truck_name": truck_name, "crew": confirmed_crew})

            if not channel_id:
                channel_errors.append(f"{truck_name}: no discord_channel_id set in DB")
                continue

            truck_channel = guild.get_channel(int(channel_id))
            if not truck_channel:
                channel_errors.append(f"{truck_name}: channel {channel_id} not found in guild")
                continue

            try:
                await self._set_truck_channel_permissions(guild, truck_channel, confirmed_crew, cfg)
            except discord.Forbidden:
                channel_errors.append(f"{truck_name}: missing Manage Channel permission")
            except Exception as e:
                channel_errors.append(f"{truck_name}: permission error — {e}")

            crew_embed = _build_truck_channel_embed(truck_name, confirmed_crew, dispatch_date)
            try:
                await truck_channel.send(embed=crew_embed)
            except Exception as e:
                channel_errors.append(f"{truck_name}: could not post crew card — {e}")

            confirmed_trainers = [m for m in confirmed_crew if m["role"] == "trainer"]
            confirmed_trainees = [m for m in confirmed_crew if m["role"] == "trainee"]

            for member in confirmed_crew:
                discord_id = member.get("discord_id")
                if not discord_id or not discord_id.isdigit():
                    continue
                try:
                    discord_user = await self.bot.fetch_user(int(discord_id))
                    crew_lines = "\n".join(
                        f"  {ROLE_LABELS.get(m['role'], m['role'])}: **{m['name']}**"
                        for m in confirmed_crew
                        if m["employee_id"] != member["employee_id"]
                    )

                    role = member.get("role", "walker")
                    pairing_note = ""
                    if role == "trainer":
                        if confirmed_trainees:
                            phase_info = await _fetch_trainee_phases(confirmed_trainees)
                            lines = "\n".join(
                                f"  📋 **{name}** — Phase {phase}"
                                for name, phase in phase_info
                            )
                            pairing_note = f"\n\n📋 **Your trainee today:**\n{lines}"
                        else:
                            pairing_note = "\n\n*(No trainee on your truck — one may be reassigned by dispatch.)*"
                    elif role == "trainee":
                        if confirmed_trainers:
                            trainer_names = ", ".join(f"**{m['name']}**" for m in confirmed_trainers)
                            pairing_note = f"\n\n🎓 **Your trainer today:** {trainer_names}"
                        else:
                            pairing_note = "\n\n⚠️ **No confirmed trainer on your truck** — contact dispatch for reassignment."

                    final_embed = discord.Embed(
                        title=f"✅ Final Assignment — {dispatch_date}",
                        description=(
                            f"**Truck:** {truck_name}\n"
                            f"**Your role:** {ROLE_LABELS.get(role, role)}\n\n"
                            f"**Confirmed crew:**\n{crew_lines or 'No other crew members.'}"
                            f"{pairing_note}\n\n"
                            f"You now have access to **#{truck_channel.name}** for today."
                        ),
                        color=discord.Color.green(),
                    )
                    await discord_user.send(embed=final_embed)
                except Exception:
                    pass

        await drivers_channel.send(_build_drivers_chat_message(trucks_summary, dispatch_date))

        if channel_errors:
            error_lines = "\n".join(f"• {e}" for e in channel_errors)
            await drivers_channel.send(
                f"⚠️ **Finalization completed with errors:**\n{error_lines}"
            )

        logger.info("Finalization complete for %s. Channel errors: %s", dispatch_date, channel_errors)

    async def _set_truck_channel_permissions(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        confirmed_crew: list[dict],
        cfg: GuildConfig,
    ) -> None:
        """Replace all member-level overwrites on a truck channel."""
        for target in list(channel.overwrites):
            if isinstance(target, discord.Member):
                await channel.set_permissions(target, overwrite=None)

        await channel.set_permissions(guild.default_role, view_channel=False)

        for role_id in cfg.always_allowed_role_ids():
            role = guild.get_role(role_id)
            if role:
                await channel.set_permissions(role, view_channel=True, send_messages=True)

        for member in confirmed_crew:
            discord_id = member.get("discord_id")
            if not discord_id or not discord_id.isdigit():
                logger.warning(
                    "Skipping channel perm for %s — discord_id '%s' is not a snowflake.",
                    member.get("name"), discord_id,
                )
                continue
            try:
                guild_member = await guild.fetch_member(int(discord_id))
                await channel.set_permissions(
                    guild_member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            except (discord.NotFound, discord.HTTPException):
                logger.warning("Could not find guild member %s for channel perms.", discord_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DispatchCog(bot))
