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
from app.models.company import Company
from app.services.derive_block_key import derive_block_key, ParsedBlock
from app.tasks.enrich_manifest import _geoclient_normalise

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
        pending = (
            db.query(BuildingProfile)
            .filter(BuildingProfile.address_status == "pending")
            .limit(_BATCH)
            .all()
        )
        if not pending:
            return {"resolved": 0, "rejected": 0, "skipped": 0}

        # Borough is per-company (Company.geoclient_borough), so cache the
        # lookup rather than querying once per profile in the loop.
        boroughs: dict = {}

        for profile in pending:
            cid = profile.company_id
            if cid not in boroughs:
                company = db.query(Company).filter(Company.id == cid).first()
                boroughs[cid] = (company.geoclient_borough if company else None) or "manhattan"

            try:
                geo = _geoclient_normalise(profile.normalised_address, borough=boroughs[cid])
            except Exception:
                # Network/transport failure is NOT the address's fault, so it
                # must not be recorded as `rejected` — that would tell the
                # captain to fix an address that is fine. Leave it `pending`
                # for the next run and log without the address (PII, dim 7).
                logger.warning(
                    "building_address_resolve_error",
                    extra={"profile_id": str(profile.id), "company_id": str(cid)},
                    exc_info=True,
                )
                skipped += 1
                continue

            # No key configured: _geoclient_normalise returns None rather than
            # raising. Same reasoning as above — leave it pending.
            if geo is None:
                skipped += 1
                continue

            # GeoClient can answer 200 with the street matched but no segment
            # topology (grc 42, "ADDRESS NUMBER OUT OF RANGE"). For a package
            # that is a warning, because the package still gets delivered. For
            # a BUILDING PROFILE it is a rejection: the row exists to say a
            # specific building is a specific way, and a house number that does
            # not exist on that street cannot be that building.
            if not geo.segment_id:
                profile.address_status = "rejected"
                profile.geo_grc = geo.geo_grc
                profile.geo_message = (geo.geo_message or "no segment topology")[:200]
                rejected += 1
                continue

            # Success. The canonical form REPLACES what was typed — the typed
            # string is not kept alongside it, because the canonical form IS
            # the address (ADR-277 D1). raw_note already carries anything the
            # submitter wanted to say in their own words.
            if geo.normalised_address:
                profile.normalised_address = geo.normalised_address[:200]
                # block_key is denormalised FROM the address, so a rewritten
                # address with a stale block_key would group the building under
                # its old spelling. Re-derive, and keep the old one if the new
                # address does not parse.
                parsed = derive_block_key(profile.normalised_address, tba="")
                if isinstance(parsed, ParsedBlock):
                    profile.block_key = parsed.block_key

            profile.lat = geo.lat
            profile.lng = geo.lng
            profile.segment_id = geo.segment_id
            profile.geo_grc = None
            profile.geo_message = None
            profile.address_status = "resolved"
            resolved += 1

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
