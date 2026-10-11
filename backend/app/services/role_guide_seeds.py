"""Platform-seeded role guide content (ADR-494 D4).

Every role, in every operating mode, has a page that answers one question: *what
is my job on this app, and what just changed?* It is the destination for the two
notifications that announce a change of standing -- `graduation` and
`operating_mode_change` -- and the reason both could stop being GATEs (D1).

## Why the content is seeded rather than hardcoded

A tenant's rules differ in ways the platform cannot know: who signs off a
timecard, whether trainees ride solo at phase 4, what "captain" means on their
lot. So these rows are a STARTING POINT, not the content. ADR-485 D8's pattern:
the platform seeds, the tenant edits, and `seed_key` makes the seed idempotent
so a later platform revision can reach rows nobody has touched.

`seed_version` is what makes that safe. On re-seed:

  - row absent              -> insert
  - row present, unedited   -> update IF our version is newer
  - row present, EDITED     -> never touched (`edited_at IS NOT NULL`)

A tenant's rewrite is theirs permanently. That is the whole point of the
`edited_at`/`edited_by` pair being NOT NULL together (the model's CHECK): an
edited row is identifiable without consulting an audit log.

## Why the role list is derived, not typed

`Employee.role` is a free `String(50)` with no enum and no CHECK, so there is no
schema-level list of roles to iterate. The nearest thing to a canonical list is
`registration.ROLE_TO_COGNITO_GROUP`, and its own comment says why it is the one
worth binding to:

    "A role missing here resolves to None via .get() and the Cognito group
     silently never syncs."

Deriving from it means a new role cannot acquire a Cognito group but no guide --
`test_every_role_has_a_guide_in_both_modes` fails on the ADD. The alternative,
retyping ten strings here, produces a list that is correct on the day it is
written and silently stale afterward; the repo has that failure recorded twice
over in the "mirrored, keep in sync" comments on this very dict.
"""
from __future__ import annotations

from app.routers.registration import ROLE_TO_COGNITO_GROUP

#: Bump when the BODY text below changes materially. Unedited rows follow;
#: edited rows never do. Do NOT bump for a typo fix -- a version bump is a
#: promise that the new text is worth overwriting an old seed with.
#:
#: A STRING, because the column is String(16) -- the two must agree or the
#: comparison in seed_role_guides raises TypeError on the second run, when the
#: first has nothing to compare against. (That is how this was found: the
#: insert path never compares, so a dry run and a first --commit both passed.)
#:
#: Compared with _version_at_least, NOT with `>`: string ordering would make
#: "10" < "9" and silently stop following seeds at the tenth revision.
SEED_VERSION = "1"

#: Derived, not typed -- see the module docstring.
SEEDED_ROLES: tuple[str, ...] = tuple(sorted(ROLE_TO_COGNITO_GROUP))

MODES: tuple[str, ...] = ("full", "workforce")


def seed_key(role: str, mode: str) -> str:
    """Stable identity for one seeded row, independent of its primary key.

    Format is `role_guide:<role>:<mode>` -- the triple the unique index already
    covers, minus company_id, because the key identifies the SEED and the index
    identifies the ROW.
    """
    return f"role_guide:{role}:{mode}"


# ── the content ──────────────────────────────────────────────────────────────
#
# Written in the second person, for the person holding the phone. Each body
# answers: what you do, what you can see, what you cannot, and who to go to.
#
# Two rules these bodies follow, both learned from ADR-305's mode divergence:
#
#   1. Never describe a feature the mode does not have. A workforce-mode walker
#      reading about scanning a manifest package is being told to look for a
#      button that is not rendered -- which reads as a broken app, not a
#      different plan.
#
#      NOT machine-checked, deliberately. A phrase-matching check against the
#      capability lists was written and thrown away: it flagged 12 lines, all
#      of them correct, because nine were the "this company runs WITHOUT an
#      Amazon package feed" sentence -- a negation the matcher cannot read --
#      and two were legitimate ("clearing dispatch wipes the sort outputs" is
#      true in both modes; `clear_daily_dispatch` carries no RequireMode).
#      A gate with a 100% false-positive rate is the sanitiser-against-an-
#      absent-threat that Dimension 10 warns about: maintained forever,
#      protecting nothing. The structural guard that DOES hold is the KeyError
#      in iter_seeds, which fails on a role with no text at all.
#   2. Never say "manager" without "admin" -- admins have full access
#      everywhere, and a guide that implies otherwise teaches the org chart
#      wrong.

_SHARED_FULL = (
    "This company runs with an Amazon package feed, so the app knows the "
    "packages and the addresses before the day starts."
)
_SHARED_WORKFORCE = (
    "This company runs without an Amazon package feed. The day is built from "
    "what the crew enters on the lot, so what you type is the record -- there "
    "is no manifest behind it to correct a mistake."
)

_BODIES: dict[tuple[str, str], tuple[str, str]] = {
    # ── field ────────────────────────────────────────────────────────────────
    ("walker", "full"): (
        "Your day as a walker",
        "You deliver a route on foot and the app is your record of it.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What you do**\n"
        "- Check in when you arrive at the access point. Your clock starts there, not at the station.\n"
        "- Open **My Route** when dispatch releases it. Stops come in delivery order.\n"
        "- Scan each package as you deliver it. A scan is what marks a stop done.\n"
        "- Report a package you cannot deliver as a return, with the reason, before you leave the building.\n\n"
        "**What you can see**\n"
        "Your own route, your own stops, your own scorecard and the company's standing. "
        "You cannot see another walker's route -- that is deliberate, not a permission bug.\n\n"
        "**When something is wrong**\n"
        "Use the help request on your route screen. It reaches dispatch immediately and is "
        "logged, so you do not have to find a phone number. For anything about pay or your "
        "schedule, go to your manager or an admin.",
    ),
    ("walker", "workforce"): (
        "Your day as a walker",
        "You deliver a route on foot and the app is your record of it.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**What you do**\n"
        "- Check in when you arrive at the access point. Your clock starts there, not at the station.\n"
        "- Open **My Route** when dispatch releases it. Your captain built it from the totes on your truck.\n"
        "- Mark each stop as you deliver it.\n"
        "- Type a return by hand -- the address and the reason -- before you leave the building. "
        "Nothing else records it.\n\n"
        "**What you can see**\n"
        "Your own route, your own stops, your own scorecard and the company's standing. "
        "You cannot see another walker's route -- that is deliberate, not a permission bug.\n\n"
        "**When something is wrong**\n"
        "Use the help request on your route screen. It reaches dispatch immediately and is "
        "logged, so you do not have to find a phone number. For anything about pay or your "
        "schedule, go to your manager or an admin.",
    ),
    ("driver", "full"): (
        "Your day as a driver",
        "You run the truck. The walkers on it are your crew for the day.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What you do**\n"
        "- Confirm your load at the dock before you leave. The confirmation locks the check-off, "
        "so confirm once you have actually looked.\n"
        "- Run a vehicle inspection at the start and end of the day.\n"
        "- Log fuel when you fill up.\n"
        "- Mark your departure and your return.\n\n"
        "**What you can see**\n"
        "Your own truck, your own crew, your own inspections and fuel. Not the whole fleet -- "
        "dispatch, management and admins see that.\n\n"
        "**If something is missing from the load**\n"
        "Say so before you confirm. After confirmation the check-off is closed and reopening it "
        "takes dispatch.",
    ),
    ("driver", "workforce"): (
        "Your day as a driver",
        "You run the truck. The walkers on it are your crew for the day.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**What you do**\n"
        "- Confirm your load at the dock before you leave. The confirmation locks the check-off, "
        "so confirm once you have actually looked.\n"
        "- Run a vehicle inspection at the start and end of the day.\n"
        "- Log fuel when you fill up.\n"
        "- Mark your departure and your return.\n\n"
        "**What you can see**\n"
        "Your own truck, your own crew, your own inspections and fuel. Not the whole fleet -- "
        "dispatch, management and admins see that.\n\n"
        "**If something is missing from the load**\n"
        "Say so before you confirm. After confirmation the check-off is closed and reopening it "
        "takes dispatch.",
    ),
    ("captain", "full"): (
        "Your day as a captain",
        "You are a driver with the lot's institutional knowledge, and the app leans on it.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What you do, beyond a driver's day**\n"
        "- Everything in the driver guide -- load confirmation, inspections, fuel, departure.\n"
        "- Answer dispatch when they ask you to take or give up a truck. Declining is a real "
        "answer and it is recorded; it is not held against you.\n"
        "- Flag a building that behaves differently from how the app describes it. Your note "
        "becomes part of the building's profile and outlives your shift.\n\n"
        "**Why you get asked more**\n"
        "Captains rotate trucks on a fixed cycle so the knowledge spreads instead of pooling. "
        "If the rotation lands badly for you, tell dispatch -- it is a setting, not a rule.",
    ),
    ("captain", "workforce"): (
        "Your day as a captain",
        "You are a driver with the lot's institutional knowledge, and in this mode the app "
        "depends on it directly.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**The part only you do**\n"
        "You enter the addresses off the totes on your truck. That entry IS the route -- the "
        "app has no other source for it. A tote typed wrong sends a walker to the wrong "
        "building, so take the extra few seconds.\n\n"
        "**The rest of your day**\n"
        "- Everything in the driver guide -- load confirmation, inspections, fuel, departure.\n"
        "- Answer dispatch when they ask you to take or give up a truck. Declining is a real "
        "answer and it is recorded.\n"
        "- Flag a building that behaves differently from how the app describes it. Your note "
        "becomes part of the building's profile and outlives your shift.",
    ),
    # ── training ─────────────────────────────────────────────────────────────
    ("trainee", "full"): (
        "Your day as a trainee",
        "You are learning the route work with a trainer alongside you.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**How the phases work**\n"
        "- **Phases 1 to 3** -- you are supervised. Your trainer submits the day's work on your "
        "behalf, so if something you did is not showing up, it is with them, not lost.\n"
        "- **Phase 4** -- once you opt in to solo, you submit your own route yourself. That opt-in "
        "is yours to make and you can hold off.\n\n"
        "**What you can see**\n"
        "Your own route and your own progress through the phases. Your trainer and the trainers' "
        "dashboard see the same progress.\n\n"
        "**If you need help mid-route**\n"
        "Use the help request. It goes to your trainer and to dispatch at once -- it is the one "
        "thing in the app that interrupts people on purpose, so use it when you need it.",
    ),
    ("trainee", "workforce"): (
        "Your day as a trainee",
        "You are learning the route work with a trainer alongside you.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**How the phases work**\n"
        "- **Phases 1 to 3** -- you are supervised. Your trainer submits the day's work on your "
        "behalf, so if something you did is not showing up, it is with them, not lost.\n"
        "- **Phase 4** -- once you opt in to solo, you submit your own route yourself. That opt-in "
        "is yours to make and you can hold off.\n\n"
        "**What you can see**\n"
        "Your own route and your own progress through the phases. Your trainer and the trainers' "
        "dashboard see the same progress.\n\n"
        "**If you need help mid-route**\n"
        "Use the help request. It goes to your trainer and to dispatch at once -- it is the one "
        "thing in the app that interrupts people on purpose, so use it when you need it.",
    ),
    ("driver_trainee", "full"): (
        "Your day as a driver trainee",
        "You are learning the truck with a trainer alongside you.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What you do**\n"
        "- Ride with your trainer and work through the phases the same way a walking trainee does.\n"
        "- Learn the dock flow: load check-off, confirmation, inspection, departure. You will be "
        "doing it unsupervised soon enough.\n"
        "- Run the vehicle inspection yourself, with your trainer watching, before you are signed "
        "off to do it alone.\n\n"
        "**What you can see**\n"
        "Your own progress and the truck you are assigned to. The fleet view belongs to dispatch, "
        "management and admins.\n\n"
        "**When you graduate**\n"
        "You become a driver and the driver guide replaces this page. The app will tell you when "
        "that happens.",
    ),
    ("driver_trainee", "workforce"): (
        "Your day as a driver trainee",
        "You are learning the truck with a trainer alongside you.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**What you do**\n"
        "- Ride with your trainer and work through the phases the same way a walking trainee does.\n"
        "- Learn the dock flow: load check-off, confirmation, inspection, departure.\n"
        "- Watch how your captain enters the tote addresses. In this mode that entry is the route, "
        "and you will be relied on for it.\n"
        "- Run the vehicle inspection yourself, with your trainer watching, before you are signed "
        "off to do it alone.\n\n"
        "**What you can see**\n"
        "Your own progress and the truck you are assigned to. The fleet view belongs to dispatch, "
        "management and admins.\n\n"
        "**When you graduate**\n"
        "You become a driver and the driver guide replaces this page.",
    ),
    ("trainer", "full"): (
        "Your day as a trainer",
        "You are responsible for the trainees assigned to you, and for what the app records "
        "about them.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What you do**\n"
        "- Submit the day's work for any trainee in phases 1 to 3. They cannot do it themselves, "
        "so an unsubmitted day is a gap in their record.\n"
        "- Answer continuation requests -- whether a trainee carries on to the next phase.\n"
        "- Respond to a trainee's help request. It reaches you and dispatch at the same time.\n"
        "- Sign off phase 4 solo opt-in when they are genuinely ready.\n\n"
        "**What you can see**\n"
        "Your trainees' routes and progress, and the trainer dashboard across all of them.\n\n"
        "**If you are going to be out**\n"
        "Tell dispatch. They reassign your trainees for the day -- a trainee whose trainer does "
        "not arrive cannot submit anything.",
    ),
    ("trainer", "workforce"): (
        "Your day as a trainer",
        "You are responsible for the trainees assigned to you, and for what the app records "
        "about them.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**What you do**\n"
        "- Submit the day's work for any trainee in phases 1 to 3. They cannot do it themselves, "
        "so an unsubmitted day is a gap in their record.\n"
        "- Answer continuation requests -- whether a trainee carries on to the next phase.\n"
        "- Respond to a trainee's help request. It reaches you and dispatch at the same time.\n"
        "- Sign off phase 4 solo opt-in when they are genuinely ready.\n"
        "- Teach the address entry carefully. What the crew types is the whole record here.\n\n"
        "**What you can see**\n"
        "Your trainees' routes and progress, and the trainer dashboard across all of them.\n\n"
        "**If you are going to be out**\n"
        "Tell dispatch. They reassign your trainees for the day.",
    ),
    # ── oversight ────────────────────────────────────────────────────────────
    ("dispatch", "full"): (
        "Your day in dispatch",
        "You build the day and you are the first call when it goes sideways.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What you do**\n"
        "- Upload the manifest and run the sort, then the dispatch pairing.\n"
        "- Release routes to the crews.\n"
        "- Handle declines, absences and reassignments -- including covering a trainer who "
        "did not arrive.\n"
        "- Answer help requests from the field. These are the only notifications in the app that "
        "are allowed to interrupt you.\n"
        "- Reopen a load check-off when a driver confirmed too early.\n\n"
        "**What you can see**\n"
        "The whole fleet, every route, every crew, fleet-wide. Not pay and not employment "
        "records -- those are management and admin.\n\n"
        "**Clearing a day**\n"
        "Clearing dispatch wipes the sort outputs for that date -- zones, rosters, check-offs, "
        "confirmations, dock. It is not a soft reset, so read the confirmation.",
    ),
    ("dispatch", "workforce"): (
        "Your day in dispatch",
        "You build the day and you are the first call when it goes sideways.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**What you do**\n"
        "- Run the dispatch pairing once the crews are in. There is no manifest to upload here -- "
        "the routes come from what the captains enter.\n"
        "- Release routes to the crews.\n"
        "- Handle declines, absences and reassignments -- including covering a trainer who "
        "did not arrive.\n"
        "- Answer help requests from the field. These are the only notifications in the app that "
        "are allowed to interrupt you.\n"
        "- Reopen a load check-off when a driver confirmed too early.\n"
        "- Enter returns by hand when a crew could not.\n\n"
        "**What you can see**\n"
        "The whole fleet, every route, every crew, fleet-wide. Not pay and not employment "
        "records -- those are management and admin.\n\n"
        "**Clearing a day**\n"
        "Clearing dispatch wipes the sort outputs for that date. It is not a soft reset, so "
        "read the confirmation.",
    ),
    ("field_supervisor", "full"): (
        "Your day as a field supervisor",
        "You are dispatch's eyes on the lot, with the same fleet-wide view and a narrower "
        "write surface.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What you do**\n"
        "- Watch every truck and every route, unscoped -- the same view dispatch has.\n"
        "- Step in on the lot when a crew is stuck, rather than relaying it through dispatch.\n"
        "- Handle returns and misroutes across any truck, not just one.\n\n"
        "**What you can see**\n"
        "Everything operational, fleet-wide. Not pay and not employment records.\n\n"
        "**Where you differ from dispatch**\n"
        "You are not the one building the day -- the sort and the pairing are dispatch's. If a "
        "route needs rebuilding rather than fixing, that is a call to them.",
    ),
    ("field_supervisor", "workforce"): (
        "Your day as a field supervisor",
        "You are dispatch's eyes on the lot, with the same fleet-wide view and a narrower "
        "write surface.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**What you do**\n"
        "- Watch every truck and every route, unscoped -- the same view dispatch has.\n"
        "- Step in on the lot when a crew is stuck, rather than relaying it through dispatch.\n"
        "- Handle returns and misroutes across any truck, not just one. In this mode they are "
        "typed by hand, so you are often the one with time to do it properly.\n"
        "- Check a captain's address entry when a route looks wrong. That entry is the only "
        "source the route has.\n\n"
        "**What you can see**\n"
        "Everything operational, fleet-wide. Not pay and not employment records.\n\n"
        "**Where you differ from dispatch**\n"
        "You are not the one building the day. If a route needs rebuilding rather than fixing, "
        "that is a call to them.",
    ),
    ("management", "full"): (
        "Your day in management",
        "You own the people side: employment, pay periods, compliance and the numbers.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What you do**\n"
        "- Approve schedule changes and time off.\n"
        "- Resolve timecard mismatches before the pay period closes. The app will start asking "
        "you about these as the deadline approaches, and on the last day it will insist.\n"
        "- Review incidents, appeals and scorecards.\n"
        "- Keep vehicle compliance current.\n\n"
        "**What you can see**\n"
        "Employment records, pay periods, scorecards, the audit log and the full operational "
        "picture. Admins see all of this too.\n\n"
        "**The one deadline the app enforces**\n"
        "A timecard mismatch left unresolved one day before the pay period closes becomes a "
        "block, not a reminder. That is the only place the app stops you from working, and it "
        "exists because the deadline is external to us.",
    ),
    ("management", "workforce"): (
        "Your day in management",
        "You own the people side: employment, pay periods, compliance and the numbers.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**What you do**\n"
        "- Approve schedule changes and time off.\n"
        "- Resolve timecard mismatches before the pay period closes. The app will start asking "
        "you about these as the deadline approaches, and on the last day it will insist.\n"
        "- Review incidents, appeals and scorecards.\n"
        "- Keep vehicle compliance current.\n\n"
        "**What you can see**\n"
        "Employment records, pay periods, scorecards, the audit log and the full operational "
        "picture. Admins see all of this too.\n\n"
        "**What the numbers do and do not cover**\n"
        "Package-level metrics need an Amazon feed, which this company does not have. Crew, "
        "training, attendance, compliance and incident figures are complete; delivery counts "
        "are only as good as what the crews entered.\n\n"
        "**The one deadline the app enforces**\n"
        "A timecard mismatch left unresolved one day before the pay period closes becomes a "
        "block, not a reminder.",
    ),
    ("admin", "full"): (
        "Your day as an admin",
        "You have full access to everything in this company's account -- every page, every "
        "record, every setting.\n\n"
        f"{_SHARED_FULL}\n\n"
        "**What only you and management do**\n"
        "- Invite, change and remove employees, and change their roles.\n"
        "- Read the audit log. Every write in the app lands there with who did it.\n"
        "- Change company settings, including the integrations.\n\n"
        "**What to watch**\n"
        "- Integration failures. If Discord, email or identity provisioning breaks, the app "
        "tells you rather than failing quietly -- a new hire who never got credentials is "
        "the thing that goes unnoticed otherwise.\n"
        "- Timecard mismatches as a pay period closes.\n\n"
        "**This page**\n"
        "You can edit every role's guide, including this one, under company settings. The text "
        "the platform ships is a starting point -- if your lot runs differently, say so here "
        "and your version is kept.",
    ),
    ("admin", "workforce"): (
        "Your day as an admin",
        "You have full access to everything in this company's account -- every page, every "
        "record, every setting.\n\n"
        f"{_SHARED_WORKFORCE}\n\n"
        "**What only you and management do**\n"
        "- Invite, change and remove employees, and change their roles.\n"
        "- Read the audit log. Every write in the app lands there with who did it.\n"
        "- Change company settings, including the integrations and the operating mode itself.\n\n"
        "**What to watch**\n"
        "- Integration failures. If Discord, email or identity provisioning breaks, the app "
        "tells you rather than failing quietly.\n"
        "- Timecard mismatches as a pay period closes.\n\n"
        "**If you get an Amazon feed later**\n"
        "Switching to full mode turns on the manifest, the sort and the package-level metrics, "
        "and turns off hand-entry of addresses and returns. Everyone gets told what changed "
        "from their own side -- this page is what they are sent to.\n\n"
        "**This page**\n"
        "You can edit every role's guide, including this one, under company settings.",
    ),
}


def iter_seeds():
    """Yield `(role, mode, title, body, seed_key)` for every seeded guide.

    Raises `KeyError` on a role/mode pair with no body, which is the point: a
    role added to ROLE_TO_COGNITO_GROUP without guide text fails here, loudly,
    rather than leaving that role's notification pointing at an empty page.
    """
    for role in SEEDED_ROLES:
        for mode in MODES:
            try:
                title, body = _BODIES[(role, mode)]
            except KeyError:
                raise KeyError(
                    f"no role guide text for role={role!r} mode={mode!r}. A role in "
                    f"ROLE_TO_COGNITO_GROUP needs a body in both modes -- otherwise "
                    f"role_change and operating_mode_change send that role to a blank page."
                ) from None
            yield role, mode, title, body, seed_key(role, mode)
