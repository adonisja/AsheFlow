"""Door, block and area progress for the survey register (ADR-513 D6).

Nothing here is stored. Every level is derived from observations and unlocks,
so there is no count that can drift from the rows it counts.

The block is the unit that completes and re-opens:

  * a door is DONE when it has an observation (or was marked not-a-door) in the
    block's current cycle, and no owner unlock came after that observation;
  * a block is DONE when every door on its list is done; the moment that
    happens is `completed_at`;
  * REVISIT_DAYS after `completed_at` the whole block re-opens at once: a new
    cycle starts and earlier observations stop counting. Doors never expire one
    by one, so a block is never half-stale (D6).

Doors are matched by ADDRESS, never by BIN. A BIN is a building, and one
building can carry addresses on three different blocks (BIN 1083605: 314 9 Ave,
365 W 28 St, 372 W 29 St). Both the area's snapshot and every walk's snapshot
take their addresses from the same normaliser, so the address is the stable key.

A block key carries no borough, so everything is keyed on (borough, block_key).
Walks made before ADR-513 have no borough; they match any borough. That can only
over-lock (a door counted done that was done in another borough with the same
block key and address), never lose work, and those walks predate areas entirely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Literal, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.survey_register import (
    REVISIT_DAYS, SurveyDoorUnlock, SurveyObservation, SurveyWalk,
)

BlockState = Literal["open", "in_progress", "done"]


@dataclass
class BlockProgress:
    state: BlockState
    done: set[str] = field(default_factory=set)        # addresses done this cycle
    total: int = 0
    completed_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None


def block_progress(doors: Iterable[str], observed: Iterable[tuple[str, datetime]],
                   unlocks: Iterable[tuple[str, datetime]], now: datetime,
                   revisit_days: int = REVISIT_DAYS) -> BlockProgress:
    """The state of one block, replayed from its events in time order.

    `doors` is the block's list; `observed` and `unlocks` are (address, when).
    Observations of addresses no longer on the list are ignored for completion.
    """
    door_set = set(doors)
    gap = timedelta(days=revisit_days)
    events = sorted([(t, 0, a) for a, t in observed] + [(t, 1, a) for a, t in unlocks])

    done: set[str] = set()
    completed_at: Optional[datetime] = None
    last: Optional[datetime] = None
    for when, kind, address in events:
        last = when if last is None or when > last else last
        if completed_at is not None and when >= completed_at + gap:
            # The done block's window has passed: a new cycle begins.
            done, completed_at = set(), None
        if kind == 1:                       # owner unlock: the door is open again
            done.discard(address)
            if address in door_set:
                completed_at = None
            continue
        if address in door_set:
            done.add(address)
            if completed_at is None and door_set and door_set <= done:
                completed_at = when

    if completed_at is not None and now >= completed_at + gap:
        done, completed_at = set(), None

    if door_set and completed_at is not None:
        state: BlockState = "done"
    elif done & door_set:
        state = "in_progress"
    else:
        state = "open"
    return BlockProgress(state=state, done=done & door_set, total=len(door_set),
                         completed_at=completed_at, last_activity=last)


def _walks_of(db: Session, borough: str, block_key: str):
    return (db.query(SurveyWalk)
            .filter(SurveyWalk.block_key == block_key,
                    or_(SurveyWalk.borough == borough, SurveyWalk.borough.is_(None))))


def block_events(db: Session, borough: str, block_key: str
                 ) -> tuple[list[tuple[str, datetime]], list[tuple[str, datetime]]]:
    """Every observation and unlock of one block, across every walk and writer."""
    observed = (db.query(SurveyObservation.address, SurveyObservation.observed_at)
                .join(SurveyWalk, SurveyWalk.id == SurveyObservation.walk_id)
                .filter(SurveyWalk.block_key == block_key,
                        or_(SurveyWalk.borough == borough, SurveyWalk.borough.is_(None)))
                .all())
    unlocks = (db.query(SurveyDoorUnlock.address, SurveyDoorUnlock.unlocked_at)
               .filter(SurveyDoorUnlock.borough == borough, SurveyDoorUnlock.block_key == block_key)
               .all())
    return [(a, _aware(t)) for a, t in observed], [(a, _aware(t)) for a, t in unlocks]


def current_doors(db: Session, borough: str, block_key: str, fallback: Iterable[str]) -> list[str]:
    """The block's list: the newest walk's snapshot if one exists, otherwise the
    area's snapshot. The newest fetch is the city's most current answer."""
    latest = _walks_of(db, borough, block_key).order_by(SurveyWalk.started_at.desc()).first()
    if latest is not None and latest.addresses:
        return [d["address"] for d in latest.addresses]
    return list(fallback)


def progress_for(db: Session, borough: str, block_key: str, fallback_doors: Iterable[str],
                 now: datetime) -> BlockProgress:
    observed, unlocks = block_events(db, borough, block_key)
    return block_progress(current_doors(db, borough, block_key, fallback_doors), observed, unlocks, now)


def area_progress(db: Session, blocks: list, now: datetime) -> dict:
    """Progress for many blocks in a fixed number of queries.

    `blocks` are SurveyAreaBlock rows; the result is keyed by their id. Three
    queries for the whole area rather than three per block: an NTA has hundreds.
    """
    if not blocks:
        return {}
    keys = {b.block_key for b in blocks}
    walks = (db.query(SurveyWalk.id, SurveyWalk.block_key, SurveyWalk.borough,
                      SurveyWalk.started_at, SurveyWalk.addresses)
             .filter(SurveyWalk.block_key.in_(keys)).all())
    obs = (db.query(SurveyObservation.walk_id, SurveyObservation.address, SurveyObservation.observed_at)
           .join(SurveyWalk, SurveyWalk.id == SurveyObservation.walk_id)
           .filter(SurveyWalk.block_key.in_(keys)).all())
    unl = (db.query(SurveyDoorUnlock.borough, SurveyDoorUnlock.block_key,
                    SurveyDoorUnlock.address, SurveyDoorUnlock.unlocked_at)
           .filter(SurveyDoorUnlock.block_key.in_(keys)).all())

    from collections import defaultdict
    walks_by_key = defaultdict(list)
    for w in walks:
        walks_by_key[w.block_key].append(w)
    obs_by_walk = defaultdict(list)
    for o in obs:
        obs_by_walk[o.walk_id].append((o.address, _aware(o.observed_at)))
    unl_by_block = defaultdict(list)
    for u in unl:
        unl_by_block[(u.borough, u.block_key)].append((u.address, _aware(u.unlocked_at)))

    out = {}
    for b in blocks:
        mine = [w for w in walks_by_key[b.block_key] if w.borough in (b.borough, None)]
        latest = max(mine, key=lambda w: _aware(w.started_at), default=None)
        doors = ([d["address"] for d in latest.addresses] if latest is not None and latest.addresses
                 else [d["address"] for d in (b.door_snapshot or [])])
        observed = [e for w in mine for e in obs_by_walk[w.id]]
        out[b.id] = block_progress(doors, observed, unl_by_block[(b.borough, b.block_key)], now)
    return out


def _aware(t: datetime) -> datetime:
    """SQLite returns naive datetimes; every comparison here is in UTC."""
    from datetime import timezone
    return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)
