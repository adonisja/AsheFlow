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
    # ADR-513: AddressPoint's boroughcode. A block key alone is ambiguous across
    # boroughs ("Broadway_0" is in Manhattan and Brooklyn).
    borough: str = ""

    @property
    def centre(self) -> tuple[float, float] | None:
        pts = [(d["lat"], d["lng"]) for d in self.doors if d.get("lat") is not None and d.get("lng") is not None]
        if not pts:
            return None
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    @property
    def description(self) -> str:
        nums = sorted(int(''.join(c for c in a["address"].split()[0] if c.isdigit()) or 0)
                      for a in self.doors)
        return f"{self.street}, {nums[0]}–{nums[-1]}" if nums else self.street


_SELECT = "house_number,full_street_name,bin,boroughcode,the_geom"


def _get(dataset: str, params: dict, what: str) -> list[dict]:
    url = f"{_SODA_HOST}/{dataset}.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    if settings.socrata_app_token:
        req.add_header("X-App-Token", settings.socrata_app_token)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.load(resp)
    except Exception as exc:
        # The URL carries a location; log the exception type only.
        logger.warning("survey_blocks: %s fetch failed: %s", what, type(exc).__name__)
        raise AddressSourceUnavailable("address source unavailable") from exc


def _fetch(lat: float, lng: float, radius_m: int) -> list[dict]:
    return _get(settings.socrata_addresspoint_dataset, {
        "$select": _SELECT,
        "$where": f"within_circle(the_geom, {lat:.6f}, {lng:.6f}, {int(radius_m)})",
        "$order": "addresspointid",
        "$limit": str(_LIMIT),
    }, "AddressPoint")


def _group(rows: list[dict]) -> list[Block]:
    """AddressPoint rows into blocks, keyed by borough AND block key."""
    from app.services.derive_block_key import ParsedBlock, derive_block_key

    by_key: dict[tuple[str, str], Block] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        house = (row.get("house_number") or "").strip()
        street = _normalise_street(row.get("full_street_name"))
        borough = str(row.get("boroughcode") or "").strip()
        if not house or not street:
            continue
        address = f"{house} {street}"
        if (borough, address) in seen:
            continue
        seen.add((borough, address))
        parsed = derive_block_key(address, tba="")
        if not isinstance(parsed, ParsedBlock):
            continue          # an address the block logic cannot place is not offered
        coords = (row.get("the_geom") or {}).get("coordinates") or [None, None]
        blk = by_key.setdefault((borough, parsed.block_key),
                                Block(parsed.block_key, street, borough=borough))
        blk.doors.append({
            "address": address,
            "bin": row.get("bin") or None,
            "lng": coords[0], "lat": coords[1],
        })
    blocks = list(by_key.values())
    for b in blocks:
        b.doors.sort(key=lambda a: (len(a["address"].split()[0]), a["address"]))
    blocks.sort(key=lambda b: (b.borough, b.street, b.block_key))
    return blocks


def blocks_near(lat: float, lng: float, radius_m: int = 150) -> list[Block]:
    """Every block with at least one address within `radius_m` of the point."""
    radius_m = max(25, min(int(radius_m), MAX_RADIUS_M))
    return _group(_fetch(lat, lng, radius_m))


# ── ADR-513: survey areas from public boundaries ────────────────────────────

NTA_DATASET = "9nt8-h7nd"        # 2020 Neighborhood Tabulation Areas: nta2020, ntaname
CD_DATASET = "5crt-au7u"         # Community Districts: boro_cd
_BORO_NAME = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}
# A boundary that lists more than this is refused: a walkable area is a
# neighbourhood, not a borough. MN0401 (Chelsea-Hudson Yards) is 2,964.
MAX_AREA_ADDRESSES = 20000
_PAGE = 5000
# ~5 m. Applied only to the polygon SENT in the query (a URL has a length
# limit); the result is then filtered against the exact shape, after a buffer
# wide enough that the simplification cannot have dropped a real door.
_SIMPLIFY_DEG = 0.00005
_BUFFER_DEG = 0.0002


class UnknownBoundary(Exception):
    """The city has no boundary with that code."""


class AreaTooLarge(Exception):
    """The boundary holds more addresses than a walkable area should."""


@dataclass
class Boundary:
    kind: str
    code: str
    name: str
    dataset: str
    geometry: dict          # GeoJSON MultiPolygon


def fetch_boundary(kind: str, code: str) -> Boundary:
    """The city's own polygon for an NTA or a Community District."""
    if kind == "nta":
        rows = _get(NTA_DATASET, {"nta2020": code, "$limit": "1"}, "NTA")
        if not rows:
            raise UnknownBoundary(code)
        return Boundary("nta", code, rows[0].get("ntaname") or code, NTA_DATASET, rows[0]["the_geom"])
    rows = _get(CD_DATASET, {"boro_cd": code, "$limit": "1"}, "Community District")
    if not rows:
        raise UnknownBoundary(code)
    return Boundary("cd", code, f"{_BORO_NAME.get(code[:1], 'Borough')} Community District {int(code[1:])}",
                    CD_DATASET, rows[0]["the_geom"])


def _wkt(shape) -> str:
    from shapely import wkt as _w
    return _w.dumps(shape, rounding_precision=6)


def blocks_in_area(boundary: Boundary) -> list[Block]:
    """Every block with an address inside the boundary, from the city's list."""
    from shapely.geometry import Point, shape
    from shapely.prepared import prep

    exact = shape(boundary.geometry)
    query_shape = exact.buffer(_BUFFER_DEG).simplify(_SIMPLIFY_DEG)
    rows: list[dict] = []
    offset = 0
    while True:
        page = _get(settings.socrata_addresspoint_dataset, {
            "$select": _SELECT,
            "$where": f"within_polygon(the_geom, '{_wkt(query_shape)}')",
            "$order": "addresspointid",
            "$limit": str(_PAGE),
            "$offset": str(offset),
        }, "AddressPoint (area)")
        rows.extend(page)
        if len(rows) > MAX_AREA_ADDRESSES:
            raise AreaTooLarge(boundary.code)
        if len(page) < _PAGE:
            break
        offset += _PAGE
    inside = prep(exact)
    kept = [r for r in rows
            if (c := (r.get("the_geom") or {}).get("coordinates")) and inside.contains(Point(c[0], c[1]))]
    return _group(kept)


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
