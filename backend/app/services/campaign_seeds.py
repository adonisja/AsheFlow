"""The built-in campaigns a company starts with (ADR-485 D8).

Driver and captain campaigns ship as ORDINARY `Campaign` rows differing only in
`subject_role`. Nothing in the engine knows their names: there is no
`if campaign.label == "Driver Survey"` anywhere, and a tenant that deletes both
and designs their own loses no functionality.

A special-cased built-in is a second code path that drifts from the one admins
use — and the one admins use is the one that gets tested.

WHY THE QUESTION SETS DIFFER
============================

The captain set is designed from the role, not reworded from the driver set.
ADR-256 defines a captain as the route lead, on foot, and names the duties the
role gate guards: wave distribution, route reassign/split, rts/reattempts,
misroute resolution, handoff confirm. Those are wave work and reallocation; a
driver has no equivalent, so "were the routes organised" asked about a captain
is a question about somebody else's job.

The captain set asks about CORRECTNESS as well as fairness, which the driver
set does not need to. ADR-291: *"In workforce mode there is no manifest"* — a
captain enters delivery addresses per tote by hand and the sort builds routes
from that, so there is no Amazon feed to check the result against and the
system holds no independent ground truth. `operating_mode` defaults to
`workforce` (ADR-289 D1), so that is the ordinary case. The crew walking the
route is the only instrument there is.
"""
from __future__ import annotations

import uuid
from typing import NamedTuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.campaign import Campaign, CampaignQuestion


class SeedQuestion(NamedTuple):
    prompt: str
    kind: str
    required: bool = True


class SeedCampaign(NamedTuple):
    label: str
    subject_role: str
    questions: tuple[SeedQuestion, ...]


# The driver set is the LIVE wording, carried across from driver_surveys with
# two corrections the operator made (ADR-485 D16):
#
#   Q2 was "where it SHOULD be". A driver now posts their exact anchor point
#   through the app (anchor_points.py, with /confirm), so there is a STATED
#   point to check against. "Should" asked the walker to judge against a
#   standard nobody named; "said it would be" asks them to compare two facts.
#
#   Q3 was "Were supplies ready?". Widened to "ready and available" -- it
#   covers the cart, covers, rabbits (company phones) and the rest of the
#   issued equipment, and the common failure is not that a thing was unprepared
#   but that it was not there.
DRIVER_CAMPAIGN = SeedCampaign(
    label="Driver Survey",
    subject_role="driver",
    questions=(
        SeedQuestion("Were the routes organised?", "bool"),
        SeedQuestion("Was the anchor point where it said it would be?", "bool"),
        SeedQuestion("Were supplies ready and available?", "bool"),
        SeedQuestion("Did the driver support the crew?", "bool"),
        SeedQuestion("Anything else? (optional)", "text", required=False),
    ),
)

# Four wording decisions, each load-bearing:
#
#   Q1 says "routes available", not "wave". Wave vocabulary is retired -- it
#   named a truck-wide re-issue counter rather than a wave, and a walker's
#   first re-issue could read as wave 3.
#
#   Q2 asks in BLOCKS and names the failure. "Tightly bound" and "held
#   together" are both accurate and both unusable -- nobody says them on the
#   ground. "Block" is already the word walkers see in MyRoute, and it is the
#   system's own measure of a good route (ADR-238 tunes on mean blocks per
#   route). Pairing it with "sent back and forth" names the symptom a walker
#   actually notices.
#
#   Q3 is about DISTRIBUTION, not reassignment. Splitting a route between
#   walkers is rare, so asking about moved work is "not applicable" most days.
#   The thing that happens every day is the hand-out at the truck.
#
#   Q5 says "a captain", not "the captain". The subject is one person, but a
#   walker may legitimately have reached a different one. Asking about
#   availability of the ROLE keeps it a question about cover, not personality.
CAPTAIN_CAMPAIGN = SeedCampaign(
    label="Captain Survey",
    subject_role="captain",
    questions=(
        SeedQuestion("Were the routes available on time?", "bool"),
        SeedQuestion(
            "Were your blocks next to each other, or were you sent back and forth?",
            "bool"),
        SeedQuestion("Was the work distributed fairly?", "bool"),
        SeedQuestion(
            "Were misroutes and RTS handled quickly, without holding you up?",
            "bool"),
        SeedQuestion("Could you reach a captain when you needed them?", "bool"),
        SeedQuestion("Anything else? (optional)", "text", required=False),
    ),
)

BUILT_IN_CAMPAIGNS = (DRIVER_CAMPAIGN, CAPTAIN_CAMPAIGN)


def seed_campaigns_for(db: Session, company_id: UUID,
                       created_by: UUID | None = None) -> list[Campaign]:
    """Create the built-in campaigns for a company, if absent.

    IDEMPOTENT by (company_id, subject_role) rather than by label: a tenant who
    renames "Driver Survey" to "Daily Driver Check" has one driver campaign,
    not two, and re-running this must not give them a second.

    Does NOT commit. The caller owns the transaction -- company creation seeds
    this alongside CompanyConfig, and a half-created company with campaigns but
    no config would be worse than one with neither.
    """
    created: list[Campaign] = []

    for spec in BUILT_IN_CAMPAIGNS:
        existing = (
            db.query(Campaign.id)
            .filter(Campaign.company_id == company_id,
                    Campaign.subject_role == spec.subject_role)
            .first()
        )
        if existing is not None:
            continue

        campaign = Campaign(
            id=uuid.uuid4(),
            company_id=company_id,
            label=spec.label,
            subject_role=spec.subject_role,
            created_by=created_by,
        )
        db.add(campaign)
        db.flush()

        for position, q in enumerate(spec.questions, start=1):
            db.add(CampaignQuestion(
                id=uuid.uuid4(),
                company_id=company_id,
                campaign_id=campaign.id,
                position=position,
                prompt=q.prompt,
                kind=q.kind,
                required=q.required,
            ))
        created.append(campaign)

    db.flush()
    return created
