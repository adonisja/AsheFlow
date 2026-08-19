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

import asyncio
import logging

import discord
from discord.ext import commands

from services.api_client import api
from services.guild_config import GuildConfig, get_guild_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role display config
# ---------------------------------------------------------------------------

# ADR-256: captain sits between driver and trainer — the truck's route lead.
ROLE_ORDER = ["driver", "captain", "trainer", "trainee", "walker"]
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
        # Guard against persistent-view mis-dispatch: after a bot restart, Discord
        # routes button clicks to whichever view last registered custom_id="confirm_yes".
        # Verify the clicker's Discord ID maps to this view's employee before recording.
        try:
            clicker = await api.get_employee_by_discord(str(interaction.user.id))
        except Exception:
            clicker = None
        if clicker is None or str(clicker.get("id")) != self.employee_id:
            await interaction.response.send_message(
                "⚠️ This button is not for your assignment. Please check your own DM.",
                ephemeral=True,
            )
            return

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
    captains = by_role.get("captain", [])
    trainers = by_role.get("trainer", [])

    # Each section is guarded, so an unstaffed role is skipped rather than rendered
    # as an empty heading — the same behaviour trainers already had.
    leadership_lines = []
    if drivers:
        leadership_lines.append(f"**Driver:** `{drivers[0]}`")
    if captains:
        leadership_lines.append(f"**Captain:** `{captains[0]}`")
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
# Helper: build the #drivers-chat finalization embed
# ---------------------------------------------------------------------------

def _fit_name(name: str, width: int) -> str:
    """Fit a person's name into a fixed table column.

    Prefers "First L." over a mid-word cut; falls back to a hard truncate.
    """
    if len(name) <= width:
        return name
    parts = name.split()
    if len(parts) >= 2:
        short = f"{parts[0]} {parts[-1][0]}."
        if len(short) <= width:
            return short
    return name[: width - 1] + "…"


def _build_drivers_chat_embed(trucks_data: list[dict], dispatch_date: str) -> discord.Embed:
    """Embed posted to #drivers-chat after finalization.

    Columns: Truck | Driver | Crew | Anchor Point
    Anchor Point is the truck's stored initial_anchor_display_address.
    """
    embed = discord.Embed(
        title=f"Dispatch Finalized — {dispatch_date}",
        color=0x57F287,  # green
    )

    # Pill-cell table: each cell is an inline-code span (the same pill boxes
    # the truck-channel crew post uses), padded to its column width INSIDE the
    # backticks — inline code renders monospace, so equal padding gives equal
    # pill widths and the pills align into columns. On narrow phones a row
    # wraps BETWEEN pills (whole cells drop down), never mid-word.
    TRUCK_COL, NAME_COL, CREW_COL = 7, 15, 4
    anchors = [(e.get("anchor_point") or "—") for e in trucks_data]
    anchor_col = max([len(a) for a in anchors] + [len("Anchor")])

    def _row(truck: str, driver: str, crew: str, anchor: str) -> str:
        return (
            f"`{truck:<{TRUCK_COL}}` `{driver:<{NAME_COL}}` "
            f"`{crew:>{CREW_COL}}` `{anchor:<{anchor_col}}`"
        )

    SEP = "------------------------------------------"
    rows = [_row("Truck", "Driver", "Crew", "Anchor"), SEP]

    for entry, anchor_point in zip(trucks_data, anchors):
        crew   = entry["crew"]
        driver = next((m["name"] for m in crew if m["role"] == "driver"), "TBD")
        rows.append(_row(
            entry["truck_name"][:TRUCK_COL],
            _fit_name(driver, NAME_COL),
            str(len(crew)),
            anchor_point,
        ))

    embed.description = "\n".join(rows)
    embed.set_footer(text="Full crew details in each truck's channel.")
    return embed


# ---------------------------------------------------------------------------
# Helper: build the #trainers-chat pairing embed
# ---------------------------------------------------------------------------

async def _build_trainers_chat_embed(trucks_data: list[dict], dispatch_date: str) -> discord.Embed:
    """One embed listing every truck with trainers and/or trainees for the day."""
    embed = discord.Embed(
        title=f"Trainer Pairings — {dispatch_date}",
        color=0x57F287,  # green
    )

    # Bulk-fetch phases for all trainees across all trucks in parallel.
    all_trainees = [
        m for entry in trucks_data
        for m in entry["crew"] if m["role"] == "trainee"
    ]
    phase_results = await asyncio.gather(
        *[api.get_trainee_current_phase(t["employee_id"]) for t in all_trainees],
        return_exceptions=True,
    )
    phase_map: dict[str, int | None] = {
        t["employee_id"]: (r if not isinstance(r, Exception) else None)
        for t, r in zip(all_trainees, phase_results)
    }

    # Pill-cell table — same inline-code pill boxes as the truck-channel crew
    # post, padded inside the backticks so pills align into columns. Unpaired
    # trainees keep the row shape with an em-dash Trainer pill.
    TRUCK_COL, TRAINER_COL, TRAINEE_COL = 7, 13, 13

    def _row(truck: str, trainer: str, trainee: str, day: str) -> str:
        return (
            f"`{truck:<{TRUCK_COL}}` `{trainer:<{TRAINER_COL}}` "
            f"`{trainee:<{TRAINEE_COL}}` `{day:>3}`"
        )

    SEP = "------------------------------------------"
    rows = [_row("Truck", "Trainer", "Trainee", "Day"), SEP]
    unpaired_count = 0

    for entry in trucks_data:
        truck_name = entry["truck_name"][:TRUCK_COL]
        crew = entry["crew"]
        trainers = [m for m in crew if m["role"] == "trainer"]
        trainees = [m for m in crew if m["role"] == "trainee"]
        if not trainees:
            continue

        def _day(trainee: dict) -> str:
            phase = phase_map.get(trainee["employee_id"])
            return str(phase) if phase is not None else "?"

        claimed_trainee_ids: set[str] = set()
        for trainer in trainers:
            for trainee in trainees:
                if trainee.get("paired_trainer_id") == trainer["employee_id"]:
                    rows.append(_row(
                        truck_name,
                        _fit_name(trainer["name"], TRAINER_COL),
                        _fit_name(trainee["name"], TRAINEE_COL),
                        _day(trainee),
                    ))
                    claimed_trainee_ids.add(trainee["employee_id"])

        for trainee in trainees:
            if trainee["employee_id"] not in claimed_trainee_ids:
                unpaired_count += 1
                rows.append(_row(
                    truck_name,
                    "—",
                    _fit_name(trainee["name"], TRAINEE_COL),
                    _day(trainee),
                ))

    if len(rows) > 2:
        embed.description = "\n".join(rows)
        if unpaired_count:
            embed.set_footer(text=f"{unpaired_count} trainee(s) without a trainer — fix in Dispatch.")
    else:
        embed.description = "No trainer–trainee pairings on today's dispatch."

    return embed


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
        # ADR-274 D17: dock zones travel on the dispatch payload (the bot
        # fetches its own data), keyed by truck for the driver DM below.
        dock_by_truck = {
            str(ts["truck_id"]): ts.get("dock_zone")
            for ts in dispatch.get("truck_assignments", [])
        }
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
                    dm_embed = self._build_driver_dm(
                        truck_name, dispatch_date, dock_by_truck.get(str(truck_id)),
                    )
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

    def _build_driver_dm(
        self, truck_name: str, dispatch_date: str, dock_zone: str | None = None,
    ) -> discord.Embed:
        # ADR-274 D17: the bay dispatch set, so the driver knows where to collect
        # the truck without asking. Omitted entirely when unset — a "Dock: —"
        # line is worse than no line.
        dock_line = f"**Dock:** {dock_zone}\n" if dock_zone else ""
        return discord.Embed(
            title=f"🚛 Your Assignment — {dispatch_date}",
            description=(
                f"**Truck:** {truck_name}\n"
                f"{dock_line}"
                f"**Your role:** {ROLE_LABELS.get('driver', 'Driver')}\n\n"
                "Please **confirm** your assignment by **08:20 AM**.\n"
                "After confirming, proceed to sign in on Amazon Flex and head to the offsite."
            ),
            color=discord.Color.blurple(),
        )

    async def _build_crew_dm(self, member: dict, crew: list[dict], dispatch_date: str) -> discord.Embed:
        role = member.get("role", "walker")
        member_id = member.get("employee_id")

        pairing_note = ""
        if role == "trainer":
            # Only trainees whose paired_trainer_id matches this trainer
            paired_trainees = [
                m for m in crew
                if m["role"] == "trainee" and m.get("paired_trainer_id") == member_id
            ]
            if paired_trainees:
                phase_info = await _fetch_trainee_phases(paired_trainees)
                lines = "\n".join(f"  📋 **{name}** — Day {phase}" for name, phase in phase_info)
                pairing_note = f"\n\n📋 **Your trainee today:**\n{lines}"
            else:
                pairing_note = "\n\n*(No trainee paired with you today.)*"
        elif role == "trainee":
            paired_trainer_id = member.get("paired_trainer_id")
            paired_trainer = next(
                (m for m in crew if m["role"] == "trainer" and m.get("employee_id") == paired_trainer_id),
                None,
            )
            if paired_trainer:
                pairing_note = f"\n\n🎓 **Your trainer today:** **{paired_trainer['name']}**"
            else:
                pairing_note = "\n\n⚠️ No trainer assigned to you — contact dispatch."

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
        ap_by_truck: dict[str, int] = dispatch.get("ap_by_truck", {})
        zones_by_truck: dict[str, list[str]] = dispatch.get("zones_by_truck", {})

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

            trucks_summary.append({
                "truck_name": truck_name,
                "crew": confirmed_crew,
                "ap": ap_by_truck.get(truck_id, 0),
                "zones": zones_by_truck.get(truck_id, []),
                "anchor_point": truck_info.get("initial_anchor_display_address"),
            })

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

            confirmed_trainers = {m["employee_id"]: m for m in confirmed_crew if m["role"] == "trainer"}
            confirmed_trainees = [m for m in confirmed_crew if m["role"] == "trainee"]

            for member in confirmed_crew:
                discord_id = member.get("discord_id")
                if not discord_id or not discord_id.isdigit():
                    continue
                try:
                    discord_user = await self.bot.fetch_user(int(discord_id))
                    role = member.get("role", "walker")

                    extra = ""
                    if role == "trainee":
                        # paired_trainer_id is kept live — updated when a trainer
                        # is swapped out, so this always reflects the current pairing.
                        paired = confirmed_trainers.get(member.get("paired_trainer_id"))
                        if paired:
                            extra = f"\n**Your trainer:** {paired['name']}"
                    elif role == "trainer":
                        my_trainees = [
                            m for m in confirmed_trainees
                            if m.get("paired_trainer_id") == member["employee_id"]
                        ]
                        if my_trainees:
                            names = ", ".join(m["name"] for m in my_trainees)
                            extra = f"\n**Your trainee:** {names}"

                    final_embed = discord.Embed(
                        title=f"✅ Final Assignment Confirmed — {dispatch_date}",
                        description=(
                            f"**Truck:** {truck_name}\n"
                            f"**Your role:** {ROLE_LABELS.get(role, role)}"
                            f"{extra}\n\n"
                            f"You now have access to **#{truck_channel.name}**."
                        ),
                        color=discord.Color.green(),
                    )
                    await discord_user.send(embed=final_embed)
                except Exception:
                    pass

        await drivers_channel.send(embed=_build_drivers_chat_embed(trucks_summary, dispatch_date))

        # Post trainer↔trainee pairings to #trainers-chat if configured
        trainers_channel = guild.get_channel(cfg.trainers_channel_id) if cfg.trainers_channel_id else None
        logger.info(
            "finalize_assignments: trainers_channel_id=%s resolved=%s",
            cfg.trainers_channel_id,
            trainers_channel,
        )
        if trainers_channel:
            try:
                embed = await _build_trainers_chat_embed(trucks_summary, dispatch_date)
                logger.info("finalize_assignments: trainer embed built, has_fields=%d", len(embed.fields))
                await trainers_channel.send(embed=embed)
                logger.info("finalize_assignments: trainer pairings posted to #trainers-chat")
            except Exception as e:
                logger.error("finalize_assignments: failed to post trainer pairings: %s", e, exc_info=True)
                await drivers_channel.send(f"⚠️ Failed to post trainer pairings to #trainers-chat: {e}")
        else:
            logger.warning(
                "finalize_assignments: trainers_channel not found — trainers_channel_id=%s guild=%s",
                cfg.trainers_channel_id, cfg.guild_id,
            )

        # ADR-256: post the day's captain roster to #captains. Guarded on the id, so
        # a company that has not created the channel simply gets no post — the same
        # shape as #trainers-chat above.
        captains_channel = guild.get_channel(cfg.captains_channel_id) if cfg.captains_channel_id else None
        if captains_channel:
            captain_lines = []
            for truck in trucks_summary:
                caps = [m["name"] for m in truck.get("crew", []) if m.get("role") == "captain"]
                if caps:
                    captain_lines.append(f"**{truck.get('truck_name', 'Truck')}:** `{caps[0]}`")
            if captain_lines:
                try:
                    embed = discord.Embed(
                        title=f"Captains — {dispatch_date}",
                        description="\n".join(captain_lines),
                        color=0x5865F2,
                    )
                    await captains_channel.send(embed=embed)
                except Exception as e:
                    logger.error("finalize_assignments: failed to post captains: %s", e, exc_info=True)
            else:
                # Loud rather than silent: every truck rolled without a route lead.
                logger.warning(
                    "finalize_assignments: no captains on any truck for %s — nothing posted to #captains",
                    dispatch_date,
                )
            await drivers_channel.send(
                f"⚠️ #trainers-chat (ID `{cfg.trainers_channel_id}`) not found in guild — "
                "trainer pairings not posted."
            )

        if channel_errors:
            error_lines = "\n".join(f"• {e}" for e in channel_errors)
            await drivers_channel.send(
                f"⚠️ **Finalization completed with errors:**\n{error_lines}"
            )

        logger.info("Finalization complete for %s. Channel errors: %s", dispatch_date, channel_errors)

    # ------------------------------------------------------------------
    # HUB FINALIZE — post crew embed to a single hub truck channel
    # ------------------------------------------------------------------

    async def revoke_member_from_channel(self, discord_id: str, channel_id: int) -> None:
        """Remove a member's permission overwrite from a truck channel.

        Called when a trainee declines their assignment or is marked NCNS after
        finalization has already granted channel access.
        """
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.warning("revoke_member_from_channel: channel %s not found", channel_id)
            return

        guild = channel.guild
        try:
            member = await guild.fetch_member(int(discord_id))
        except (discord.NotFound, discord.HTTPException):
            logger.warning("revoke_member_from_channel: member %s not found in guild", discord_id)
            return

        try:
            await channel.set_permissions(member, overwrite=None)
            logger.info("revoke_member_from_channel: removed %s from channel %s", discord_id, channel_id)
        except discord.Forbidden:
            logger.warning("revoke_member_from_channel: missing Manage Channel permission for %s", channel_id)
        except Exception as e:
            logger.warning("revoke_member_from_channel: error removing %s from %s: %s", discord_id, channel_id, e)

    async def sync_role(self, discord_id: str, company_id: str, action: str) -> None:
        """Grant or revoke a field-role Discord role.

        action: "grant_trainer" | "revoke_trainer" | "grant_captain" | "revoke_captain"

        ADR-256 split these. `role_captain` used to hold the TRAINER role — Discord
        called trainers "Captain" — and migration ff90779895f6 moved that value to
        `role_trainer`, leaving `role_captain` null until an admin creates the new
        guild role. A null is treated as "not configured": logged and skipped, never
        substituted, because falling back to the other role would hand a trainer
        route-lead channel access.
        """
        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            return

        guild = self.bot.get_guild(cfg.guild_id)
        if guild is None:
            logger.warning("sync_role: guild %s not found", cfg.guild_id)
            return

        verb, _, which = action.partition("_")
        role_id = cfg.role_captain if which == "captain" else cfg.role_trainer
        if not role_id:
            logger.warning(
                "sync_role: role_%s not configured for company %s — %s skipped",
                which, company_id, action,
            )
            return

        role = guild.get_role(role_id)
        if role is None:
            logger.warning("sync_role: role_%s (%s) not found in guild", which, role_id)
            return

        try:
            member = await guild.fetch_member(int(discord_id))
        except (discord.NotFound, discord.HTTPException):
            logger.warning("sync_role: member %s not found in guild", discord_id)
            return

        try:
            if verb == "grant":
                await member.add_roles(role, reason=f"Promoted to {which}")
            else:
                await member.remove_roles(role, reason=f"No longer a {which}")
        except discord.Forbidden:
            logger.error("sync_role: missing Manage Roles permission for guild %s", cfg.guild_id)
        except discord.HTTPException as exc:
            logger.error("sync_role: %s failed for discord_id=%s: %s", action, discord_id, exc)

    # Kept so a call from an older backend build still resolves.
    async def sync_trainer_role(self, discord_id: str, company_id: str, action: str) -> None:
        await self.sync_role(discord_id, company_id, action)

    async def hub_finalize_truck(self, payload: dict) -> None:
        """Post a hub crew embed to the hub truck's Discord channel and send DMs.

        Called when dispatch publishes a hub truck (POST /dispatch/hubs/{id}/publish).
        Unlike finalize_assignments, this targets only one truck and does not
        post to #drivers-chat.
        """
        company_id    = payload.get("company_id")
        dispatch_date = payload.get("date")
        truck_name    = payload.get("truck_name", "Hub")
        channel_id_str = payload.get("discord_channel_id")
        crew: list[dict] = payload.get("crew", [])

        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            logger.info("hub_finalize_truck: Discord not configured for company %s — skipping.", company_id)
            return

        guild = self.bot.get_guild(cfg.guild_id)
        if not guild:
            logger.error("hub_finalize_truck: guild %s not found.", cfg.guild_id)
            return

        if not channel_id_str:
            logger.warning("hub_finalize_truck: no discord_channel_id for truck %s — skipping embed.", truck_name)
        else:
            truck_channel = guild.get_channel(int(channel_id_str))
            if truck_channel:
                try:
                    await self._set_truck_channel_permissions(guild, truck_channel, crew, cfg)
                except Exception as e:
                    logger.warning("hub_finalize_truck: permission error on %s: %s", truck_name, e)

                crew_embed = _build_truck_channel_embed(truck_name, crew, dispatch_date)
                try:
                    await truck_channel.send(embed=crew_embed)
                except Exception as e:
                    logger.warning("hub_finalize_truck: could not post embed to %s: %s", truck_name, e)
            else:
                logger.warning("hub_finalize_truck: channel %s not found for truck %s.", channel_id_str, truck_name)

        for member in crew:
            discord_id = member.get("discord_id")
            if not discord_id or not discord_id.isdigit():
                continue
            try:
                discord_user = await self.bot.fetch_user(int(discord_id))
                role = member.get("role", "walker")
                final_embed = discord.Embed(
                    title=f"✅ Final Assignment Confirmed — {dispatch_date}",
                    description=(
                        f"**Truck:** {truck_name}\n"
                        f"**Your role:** {ROLE_LABELS.get(role, role)}\n\n"
                        + (f"You now have access to **#{guild.get_channel(int(channel_id_str)).name}**." if channel_id_str and guild.get_channel(int(channel_id_str)) else "You have been assigned to the hub for today.")
                    ),
                    color=discord.Color.green(),
                )
                await discord_user.send(embed=final_embed)
            except Exception:
                pass

        logger.info("hub_finalize_truck complete: truck=%s date=%s crew=%d", truck_name, dispatch_date, len(crew))

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


    # ------------------------------------------------------------------
    # POST-FINALIZE SWAP — move an employee between truck channels
    # ------------------------------------------------------------------

    async def swap_truck_channel(
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
        """Adjust Discord channel permissions for a post-finalize truck swap, transfer, or add.

        - Removes member overwrite from old truck channel (if provided and found).
        - Grants view/send/history on new truck channel (if provided and found).
        - Posts a @mention announcement in the new truck channel only when announce=True.
          transfer_context present  → transfer path: "You've been transferred here for today."
          transfer_context absent   → assignment path: "You've been assigned to this truck today."
        """
        cfg = await get_guild_config(company_id)
        if cfg is None or not cfg.is_configured:
            logger.info("swap_truck_channel: Discord not configured for company %s — skipping.", company_id)
            return

        guild = self.bot.get_guild(cfg.guild_id)
        if not guild:
            logger.warning("swap_truck_channel: guild %s not found.", cfg.guild_id)
            return

        guild_member = None
        if discord_id and discord_id.isdigit():
            try:
                guild_member = await guild.fetch_member(int(discord_id))
            except (discord.NotFound, discord.HTTPException):
                logger.warning("swap_truck_channel: could not fetch member discord_id=%s.", discord_id)

        # Remove from old channel
        if old_channel_id:
            old_channel = guild.get_channel(old_channel_id)
            if old_channel and guild_member:
                try:
                    await old_channel.set_permissions(guild_member, overwrite=None)
                    logger.info("Removed %s from channel %s.", employee_name, old_channel.name)
                except discord.Forbidden:
                    logger.warning("swap_truck_channel: missing Manage Channel on old channel %s.", old_channel_id)
                except Exception as exc:
                    logger.warning("swap_truck_channel: error removing from old channel: %s", exc)

        # Grant access to new channel and post announcement
        if new_channel_id:
            new_channel = guild.get_channel(new_channel_id)
            if new_channel:
                if guild_member:
                    try:
                        await new_channel.set_permissions(
                            guild_member,
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True,
                        )
                    except discord.Forbidden:
                        logger.warning("swap_truck_channel: missing Manage Channel on new channel %s.", new_channel_id)
                    except Exception as exc:
                        logger.warning("swap_truck_channel: error granting new channel perm: %s", exc)

                if announce:
                    mention = guild_member.mention if guild_member else f"**{employee_name}**"
                    if transfer_context:
                        announcement = f"🔀 {mention} You've been transferred here for today."
                    else:
                        announcement = f"📋 {mention} You've been assigned to this truck today."
                    try:
                        await new_channel.send(announcement)
                    except Exception as exc:
                        logger.warning("swap_truck_channel: could not post announcement: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DispatchCog(bot))
