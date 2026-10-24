"""Resolve typed BuildingProfile addresses against GeoClient (ADR-277 D1).

WHY THIS EXISTS
---------------
`POST /building-profiles/` stores `normalised_address` verbatim. That is correct
on mobile, which passes the enriched manifest's already-canonical string, and
wrong everywhere a human types one.

    '433 West 32nd Street'  -> block_key W_32_St_400
    '433 W 32 St'           -> block_key W_32_St_400   <- the manifest's form
    '433 w 32 st'           -> block_key W_32_St_400

One block_key, but the unique constraint is `(company_id, normalised_address)` —
so those are three rows for one building, and routing (which looks up BY
normalised address) matches none of them.

This task canonicalises the typed string so the constraint can do its job.

WHY IT IS A TASK AND NOT INLINE
-------------------------------
GeoClient is slow enough that manifest enrichment already runs in the
background with a 10-worker pool (ADR-135). A bulk CSV of 40 buildings would
mean 40 sequential calls inside one request. Single entry would be unpleasant;
bulk entry would be unusable.

ONE-SHOT, NOT A RETRY LOOP
--------------------------
A row is claimed and resolved exactly once. On failure it lands in `rejected`
with the Geosupport return code, and the submitter edits the address and
retries from the UI — an explicit human action, not a silent background loop.
A geocoder that failed on an address will fail again on the identical string;
retrying hides the problem from the one person who can fix it.
"""
import logging

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.building_profile import BuildingProfile

logger = logging.getLogger(__name__)

# One batch of work per invocation. Bounded so a bulk upload of a thousand rows
# cannot hold a worker (or a GeoClient rate limit) for an unbounded stretch.
_BATCH = 100


@celery_app.task(name="app.tasks.resolve_building_addresses.resolve_pending_addresses")
def resolve_pending_addresses() -> dict:
    """Resolve `pending` building profiles. Returns a per-outcome count."""
    db = SessionLocal()
    resolved = rejected = skipped = 0
    try:
        # ADR-289: this is the highest-frequency task in the system (every 10 min,
        # 144×/day). In workforce mode a tenant's building profiles are entered
        # manually and already carry an address, so there is no pending queue to
        # resolve — without this filter the task would scan and geocode on behalf of
        # companies that structurally cannot produce that work.
        from app.services.company_config import full_mode_company_ids
        full_mode = full_mode_company_ids(db)
        if not full_mode:
            return {"resolved": 0, "rejected": 0, "skipped": 0}

        pending = (
            db.query(BuildingProfile)
            .filter(
                BuildingProfile.address_status == "pending",
                BuildingProfile.company_id.in_(full_mode),
            )
            .limit(_BATCH)
            .all()
        )
        if not pending:
            return {"resolved": 0, "rejected": 0, "skipped": 0}

        # ADR-584: PlaceType only, never GeoClient. An unreachable PlaceType
        # reads as "no door" through the degrade guard, which here would REJECT
        # addresses that are fine. So check it answers first, and leave every
        # profile pending if it doesn't.
        from app.database import PlaceTypeSession
        from app.services import door_resolver as DR
        pt = PlaceTypeSession()
        try:
            if not DR._zip_map(pt):
                logger.warning("building_address_resolve_skipped: placetype_unavailable")
                return {"resolved": 0, "rejected": 0, "skipped": len(pending)}

            # The company's configured borough, read once per company from the
            # TENANT session. (This was `Company.geoclient_borough`: the column
            # is on CompanyConfig, so the read raised AttributeError.)
            boroughs: dict = {}
            for profile in pending:
                cid = profile.company_id
                if cid not in boroughs:
                    boroughs[cid] = DR.company_borough(db, cid)

                result = DR.resolve_door(pt, profile.normalised_address,
                                         default_borough=boroughs[cid])
                if isinstance(result, DR.Miss):
                    # A building profile says a specific building is a specific
                    # way; an address that is no city door can't be that building.
                    profile.address_status = "rejected"
                    profile.geo_grc = None
                    profile.geo_message = ("No city door matches this address."
                                           if result.reason != "no_borough_match"
                                           else "Add the ZIP code: this address exists in more than one borough.")
                    rejected += 1
                    continue

                # Success. The city's canonical form REPLACES what was typed
                # (ADR-277 D1); raw_note keeps the submitter's own words.
                profile.normalised_address = result.address[:200]
                profile.block_key = result.block_key
                profile.lat = result.lat
                profile.lng = result.lng
                profile.segment_id = result.segment_id
                profile.geo_grc = None
                profile.geo_message = None
                profile.address_status = "resolved"
                resolved += 1
        finally:
            pt.close()

        db.commit()
        logger.info(
            "building_addresses_resolved",
            extra={"resolved": resolved, "rejected": rejected, "skipped": skipped},
        )
        return {"resolved": resolved, "rejected": rejected, "skipped": skipped}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
