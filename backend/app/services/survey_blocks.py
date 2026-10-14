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
import re
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



# ── ADR-504 D8: the city block a door is on ────────────────────────────────

ENRICH_RADIUS_M = 250     # enough to reach every face of a Manhattan block
_NUMBERED = re.compile(r"^([NSEW]) (\d+) (ST|STREET)$")
_AVENUE = re.compile(r"\b(AVE|AVENUE|BROADWAY|BLVD)\b")


def _house_number(address: str) -> int | None:
    m = re.match(r"^(\d+)", address)
    return int(m.group(1)) if m else None


def _street_of(address: str) -> str:
    return address.split(" ", 1)[1] if " " in address else address


def order_sides(address: str, faces: set[str]) -> list[str]:
    """The streets a door's block faces, in the owner's order (D8 [B]).

    Own street first (it is the default). Then:
      * on a numbered street: one street DOWN if the house number is even, one
        street UP if odd (the back of the block), then the end avenues;
      * on an avenue: the cross streets, then the other avenues;
    then anything else the block faces (a named plaza). Only streets the block
    actually faces are offered; the rule only sets their order.
    """
    own = _street_of(address)
    rest = sorted(faces - {own})
    house = _house_number(address)
    m = _NUMBERED.match(own)

    def rank(street: str) -> tuple:
        n = _NUMBERED.match(street)
        if m and n and house is not None:
            target = int(m.group(2)) + (-1 if house % 2 == 0 else 1)
            if n.group(1) == m.group(1) and int(n.group(2)) == target:
                return (0, street)
            return (2, street)
        if m:                                   # own is a street: avenues next
            return (1 if _AVENUE.search(street) else 3, street)
        # own is an avenue (or named): cross streets, then avenues, then the rest
        if n:
            return (0, int(n.group(2)), street)
        return (1 if _AVENUE.search(street) else 3, street)

    return [own] + sorted(rest, key=rank)


def _city_blocks(bins: list[str]) -> dict[str, str]:
    """BIN -> borough+block (the first six digits of the footprint's base BBL)."""
    out: dict[str, str] = {}
    for i in range(0, len(bins), 150):
        chunk = ",".join(f"'{b}'" for b in bins[i:i + 150] if b.isdigit())
        if not chunk:
            continue
        params = {"$select": "bin,base_bbl", "$where": f"bin in ({chunk})", "$limit": "5000"}
        url = (f"{_SODA_HOST}/{settings.socrata_footprints_dataset}.json?"
               + urllib.parse.urlencode(params))
        req = urllib.request.Request(url)
        if settings.socrata_app_token:
            req.add_header("X-App-Token", settings.socrata_app_token)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            for r in json.load(resp):
                if r.get("bin") and r.get("base_bbl"):
                    out[r["bin"]] = r["base_bbl"][:6]
    return out


def _fallback(doors: list[dict]) -> list[dict]:
    """No footprints: own street only, and neighbours on the same street, side
    (parity) and hundred among this walk's doors."""
    out = []
    for d in doors:
        h = _house_number(d["address"])
        same = [o for o in doors if o["address"] != d["address"]
                and _street_of(o["address"]) == _street_of(d["address"])
                and h is not None and _house_number(o["address"]) is not None
                and _house_number(o["address"]) % 2 == h % 2
                and _house_number(o["address"]) // 100 == h // 100]
        out.append({**d, "city_block": None, "sides": [_street_of(d["address"])],
                    "neighbours": [{"address": o["address"], "bin": o.get("bin")} for o in same]})
    return out


def enrich_doors(doors: list[dict]) -> list[dict]:
    """Add each door's city block, side choices and same-block neighbours.

    Best effort: any failure of the city's services falls back to `_fallback`,
    because a walk must still be able to start.
    """
    pts = [(d["lat"], d["lng"]) for d in doors if d.get("lat") is not None and d.get("lng") is not None]
    if not pts:
        return _fallback(doors)
    lat = sum(p[0] for p in pts) / len(pts)
    lng = sum(p[1] for p in pts) / len(pts)
    try:
        near = []
        for row in _fetch(lat, lng, ENRICH_RADIUS_M):
            house = (row.get("house_number") or "").strip()
            street = _normalise_street(row.get("full_street_name"))
            if house and street:
                near.append({"address": f"{house} {street}", "bin": row.get("bin") or None})
        blocks = _city_blocks(sorted({r["bin"] for r in near + doors if r.get("bin")}))
    except Exception as exc:
        logger.warning("survey_blocks: enrichment failed, using fallback: %s", type(exc).__name__)
        return _fallback(doors)

    by_block: dict[str, dict[str, dict]] = {}
    for r in near + [{"address": d["address"], "bin": d.get("bin")} for d in doors]:
        cb = blocks.get(r.get("bin") or "")
        if cb:
            by_block.setdefault(cb, {})[r["address"]] = r

    out = []
    for d in doors:
        cb = blocks.get(d.get("bin") or "")
        if not cb:
            out.extend(_fallback([d]))
            continue
        members = by_block.get(cb, {})
        faces = {_street_of(a) for a in members}
        neighbours = sorted(
            ({"address": a, "bin": r.get("bin")} for a, r in members.items() if a != d["address"]),
            key=lambda n: (_street_of(n["address"]), _house_number(n["address"]) or 0))
        out.append({**d, "city_block": cb, "sides": order_sides(d["address"], faces),
                    "neighbours": neighbours})
    return out
