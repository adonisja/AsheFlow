"""The city's own address list for the blocks around a point (ADR-504 D3).

The survey register's doors are CHOSEN FROM PUBLIC DATA, never from deliveries.
This asks NYC Open Data's AddressPoint for every address within a small radius
and groups them into blocks with `derive_block_key`. A walk then snapshots one
block's list, and every observation must name an address on that snapshot.

The server always fetches. A client never supplies the list, because a list the
client supplied could have come from anywhere, including a manifest.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from app.core.config import settings
from app.services.address_inventory import AddressSourceUnavailable, _normalise_street

logger = logging.getLogger(__name__)

_SODA_HOST = "https://data.cityofnewyork.us/resource"
MAX_RADIUS_M = 300      # a few blocks; a walk is one block
_LIMIT = 2000
_TIMEOUT = 30


@dataclass
class Block:
    block_key: str
    street: str
    doors: list[dict] = field(default_factory=list)   # {"address","bin","lat","lng"}

    @property
    def description(self) -> str:
        nums = sorted(int(''.join(c for c in a["address"].split()[0] if c.isdigit()) or 0)
                      for a in self.doors)
        return f"{self.street}, {nums[0]}–{nums[-1]}" if nums else self.street


def _fetch(lat: float, lng: float, radius_m: int) -> list[dict]:
    params = {
        "$select": "house_number,full_street_name,bin,the_geom",
        "$where": f"within_circle(the_geom, {lat:.6f}, {lng:.6f}, {int(radius_m)})",
        "$order": "addresspointid",
        "$limit": str(_LIMIT),
    }
    url = f"{_SODA_HOST}/{settings.socrata_addresspoint_dataset}.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    if settings.socrata_app_token:
        req.add_header("X-App-Token", settings.socrata_app_token)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.load(resp)
    except Exception as exc:
        # The URL carries a location; log the exception type only.
        logger.warning("survey_blocks: AddressPoint fetch failed: %s", type(exc).__name__)
        raise AddressSourceUnavailable("address source unavailable") from exc


def blocks_near(lat: float, lng: float, radius_m: int = 150) -> list[Block]:
    """Every block with at least one address within `radius_m` of the point."""
    from app.services.derive_block_key import ParsedBlock, derive_block_key

    radius_m = max(25, min(int(radius_m), MAX_RADIUS_M))
    by_key: dict[str, Block] = {}
    seen: set[str] = set()
    for row in _fetch(lat, lng, radius_m):
        house = (row.get("house_number") or "").strip()
        street = _normalise_street(row.get("full_street_name"))
        if not house or not street:
            continue
        address = f"{house} {street}"
        if address in seen:
            continue
        seen.add(address)
        parsed = derive_block_key(address, tba="")
        if not isinstance(parsed, ParsedBlock):
            continue          # an address the block logic cannot place is not offered
        coords = (row.get("the_geom") or {}).get("coordinates") or [None, None]
        blk = by_key.setdefault(parsed.block_key, Block(parsed.block_key, street))
        blk.doors.append({
            "address": address,
            "bin": row.get("bin") or None,
            "lng": coords[0], "lat": coords[1],
        })
    blocks = list(by_key.values())
    for b in blocks:
        b.doors.sort(key=lambda a: (len(a["address"].split()[0]), a["address"]))
    blocks.sort(key=lambda b: (b.street, b.block_key))
    return blocks

