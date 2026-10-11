"""Promote collected doors into a company's building profiles (ADR-495).

A campaign's rows are grouped into DOORS, each door gets a state, and the
reviewer decides per door: promote or reject. The preview and the promotion use
the same `doors_for`, so the state the reviewer saw is recomputed rather than
trusted when they confirm (D9).

Nothing here commits. The router owns flush, audit and commit.

    state             meaning                                         may
    ---------------   ---------------------------------------------   ---------------
    ready             observations agree                              promote, reject
    conflict          observations disagree on the building type      promote (pick a row), reject
    exists            the company already has a profile at the door   reject (promote = skipped)
    check_address     the address names no street, or the tidy-up     reject
                      dropped it (ADR-496)
    already_reviewed  every row is stamped                            nothing
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.building_profile import BuildingProfile
from app.models.building_profile_verification import BuildingProfileVerification
from app.models.collection import CollectedAddressProfile, CollectionToken
from app.models.employee import Employee
from app.schemas.building_taxonomy import category_for
from app.schemas.location_profile import WORKLOAD_CLASSES, derive_workload_class
from app.services.derive_block_key import ParsedBlock, derive_block_key
from app.services.door_key import address_problem, canonical_address, door_key
from app.services.note_scrub import scrub_note

# Mirrors building_profiles._REVIEW_THRESHOLD (ADR-276); a test pins the two
# together. Two agreeing observations reach `review`, never `verified`.
REVIEW_THRESHOLD = 2

READY, CONFLICT, EXISTS, CHECK_ADDRESS, REVIEWED = (
    "ready", "conflict", "exists", "check_address", "already_reviewed")

PENDING, PROMOTED, REJECTED, SKIPPED = "pending", "promoted", "rejected", "skipped"



@dataclass
class Door:
    key: str                      # door_key of the canonical address: the group
    address: str                  # what the profile would be stored as
    state: str
    rows: list[CollectedAddressProfile]       # every row, newest first
    pending: list[CollectedAddressProfile] = field(default_factory=list)

    @property
    def observers(self) -> list[CollectedAddressProfile]:
        """One row per distinct observer (D4). A device counts once; rows from
        before ADR-426 have no device and are counted each."""
        seen: set[str] = set()
        out = []
        for r in self.pending:
            if r.device_id:
                if r.device_id in seen:
                    continue
                seen.add(r.device_id)
            out.append(r)
        return out


def _company_door_keys(db: Session, company_id) -> set[str]:
    return {
        door_key(a) for (a,) in db.query(BuildingProfile.normalised_address)
        .filter(BuildingProfile.company_id == company_id).all()
    }


def doors_for(db: Session, tok: CollectionToken) -> list[Door]:
    """Every door in a company campaign, with its state."""
    rows = (
        db.query(CollectedAddressProfile)
        .filter(
            CollectedAddressProfile.token_id == tok.id,
            # Stated, not inferred from the token: the rows carry the tenant
            # (ADR-115 D1), and assignment moved both together (D3).
            CollectedAddressProfile.company_id == tok.company_id,
        )
        .order_by(CollectedAddressProfile.submitted_at.desc())
        .all()
    )
    # Grouped by the CANONICAL address's key, not the stored door_key: rows
    # from before ADR-420 kept a unit or floor ("10 E 33 St Floor 3") that
    # door_key does not strip, and storing both would make two profiles that
    # canonicalise to one address and collide on the unique constraint.
    groups: dict[str, list[CollectedAddressProfile]] = {}
    for r in rows:
        groups.setdefault(door_key(canonical_address(r.address)), []).append(r)

    have = _company_door_keys(db, tok.company_id)
    doors = []
    for key, members in groups.items():
        pending = [r for r in members if r.review_status == PENDING]
        address = canonical_address((pending or members)[0].address)
        if not pending:
            state = REVIEWED
        elif key in have:
            state = EXISTS
        # ADR-496 D4. RECOMPUTED with today's canonicaliser rather than read
        # from the stored flag: rows from before the flag existed are caught
        # too, and a damaged address can never key a building profile.
        elif any(address_problem(r.address) for r in pending) or address_problem(address):
            state = CHECK_ADDRESS
        elif len({r.building_type for r in pending}) > 1:
            state = CONFLICT
        else:
            state = READY
        doors.append(Door(key=key, address=address, state=state, rows=members, pending=pending))
    doors.sort(key=lambda d: d.address)
    return doors


@dataclass
class Decision:
    door_key: str
    action: str                 # "promote" | "reject"
    use_row_id: object = None   # UUID; required when the door is in conflict


@dataclass
class Outcome:
    door_key: str
    outcome: str                # promoted | rejected | skipped | already_reviewed |
                                # not_found | needs_choice | invalid_choice | check_address
    profile_id: object = None


def _stamp(rows: Iterable[CollectedAddressProfile], status: str, caller: Employee, now) -> None:
    for r in rows:
        r.review_status = status
        r.reviewed_by = caller.id
        r.reviewed_at = now


def _profile_from(door: Door, chosen: CollectedAddressProfile, observers: list,
                  company_id, caller: Employee, now) -> BuildingProfile:
    parsed = derive_block_key(door.address, tba="")
    btype = chosen.building_type
    wclass = chosen.workload_class if chosen.workload_class in WORKLOAD_CLASSES \
        else derive_workload_class(btype)
    count = min(len(observers), REVIEW_THRESHOLD)
    return BuildingProfile(
        # The CAMPAIGN's company, the same one the rows were read under. The
        # router guarantees the caller belongs to it; this does not rely on that.
        company_id                    = company_id,
        normalised_address            = door.address,
        # isinstance, not truthiness: an UnparseableAddress is a truthy object
        # with no block_key.
        block_key                     = parsed.block_key if isinstance(parsed, ParsedBlock) else "",
        # Typed by a person, so GeoClient canonicalises it where the tenant runs
        # full mode, as for any manual entry (ADR-277 D1).
        address_status                = "pending",
        collection_source             = "campaign",
        building_type                 = btype,
        building_category             = category_for(btype),
        workload_class                = wclass,
        workloads                     = list(chosen.workloads or []),
        workload_other                = chosen.workload_other,
        has_security_desk             = bool(chosen.has_security_desk),
        raw_note                      = scrub_note(chosen.note)[0],
        opens_at                      = chosen.opens_at,
        closes_at                     = chosen.closes_at,
        break_start                   = chosen.break_start,
        break_end                     = chosen.break_end,
        building_type_status          = "review" if count >= REVIEW_THRESHOLD else "pending",
        building_type_agreement_count = count,
        note_verified                 = False,
        submitted_by                  = caller.id,
        submitted_by_name             = (caller.name or "")[:100],
        submitted_at                  = now,
    )


def promote(db: Session, tok: CollectionToken, decisions: list[Decision],
            caller: Employee) -> list[Outcome]:
    """Apply the reviewer's decisions. Does not commit."""
    now = datetime.now(timezone.utc)
    doors = {d.key: d for d in doors_for(db, tok)}
    out: list[Outcome] = []

    for dec in decisions:
        door = doors.get(dec.door_key)
        if door is None:
            out.append(Outcome(dec.door_key, "not_found"))
            continue
        if door.state == REVIEWED:
            out.append(Outcome(dec.door_key, "already_reviewed"))
            continue

        if dec.action == "reject":
            _stamp(door.pending, REJECTED, caller, now)
            out.append(Outcome(dec.door_key, "rejected"))
            continue

        if door.state == EXISTS:
            # D6: the company's record is not touched.
            _stamp(door.pending, SKIPPED, caller, now)
            out.append(Outcome(dec.door_key, "skipped"))
            continue
        if door.state == CHECK_ADDRESS:
            out.append(Outcome(dec.door_key, "check_address"))
            continue

        if dec.use_row_id is not None:
            chosen = next((r for r in door.pending if str(r.id) == str(dec.use_row_id)), None)
            if chosen is None:
                out.append(Outcome(dec.door_key, "invalid_choice"))
                continue
        elif door.state == CONFLICT:
            out.append(Outcome(dec.door_key, "needs_choice"))
            continue
        else:
            chosen = door.pending[0]   # newest

        # D4/D5: a disagreement is one person's reading, as ADR-276 D4 resets a
        # field disagreement to 1. Only rows that AGREE with the chosen type
        # count as observations.
        observers = [r for r in door.observers if r.building_type == chosen.building_type]
        if door.state == CONFLICT:
            observers = [chosen]

        profile = _profile_from(door, chosen, observers, tok.company_id, caller, now)
        db.add(profile)
        db.flush()
        for r in observers[:REVIEW_THRESHOLD]:
            # Anonymous: the reviewer did not observe the door, and a collector
            # has no Employee row. Weight 1 each, as a walker's (ADR-276 D1).
            db.add(BuildingProfileVerification(
                company_id=tok.company_id, profile_id=profile.id,
                employee_id=None, employee_name=None, employee_role=None,
                weight=1, building_type=r.building_type,
            ))
        _stamp(door.pending, PROMOTED, caller, now)
        door.state = REVIEWED          # a repeated decision in one batch is a no-op
        out.append(Outcome(dec.door_key, "promoted", profile.id))
    return out
