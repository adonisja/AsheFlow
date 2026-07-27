"""Probe: can GeoClient give us the CONNECTOR segment between two intersections?

ADR-236 D2 needs the segment ids of the connecting streets (the avenues) so the LION
segment graph stops being fragmented into 47 components. Today segment ids come only
from /address.json (`segmentIdentifier`, `fromLionNodeId`, `toLionNodeId`);
`_geoclient_intersection` returns just (lat, lng) and never looks for identifiers.

This script answers, against the LIVE api, in cheapest-first order:

  Q1  Does /intersection ALREADY return segment/node identifiers we simply discard?
      -> cheapest fix: extract them, no new endpoint.
  Q2  Is there a /blockface or /segment endpoint keyed by street + cross streets?
      -> a real connector lookup.
  Q3  Does /address.json on the CONNECTING street yield its segment?
      -> fallback: synthesise via a house number.

Run:  docker compose exec -T backend python scripts/probe_geoclient_connector.py
Needs GEOCLIENT_APP_KEY set (see app/core/config.py: geoclient_app_key).

Read-only: issues GETs against a public NYC API, writes nothing.
"""
import sys

import requests

sys.path.insert(0, "/app")

from app.core.config import settings  # noqa: E402
from app.tasks.enrich_manifest import _GEOCLIENT_BASE  # noqa: E402

# A real Midtown-West intersection pair from the 07-27 manifest's zone, plus the
# avenue that connects consecutive cross streets (the connector we actually want).
BOROUGH = "manhattan"
CROSS_A, CROSS_B = "W 42 St", "9 Ave"
CONNECTOR_STREET = "9 Ave"          # the avenue running between W 42 St and W 43 St
CONNECTOR_HOUSE = "600"             # plausible house number on that avenue

# Identifier keys worth hunting for anywhere in a response.
WANTED = (
    "segmentidentifier", "segmentid", "fromlionnodeid", "tolionnodeid",
    "lionnodeid", "nodeid", "physicalid", "segmentcount", "fromnode", "tonode",
)


def _headers():
    return {"Ocp-Apim-Subscription-Key": settings.geoclient_app_key}


def _get(path, params):
    try:
        r = requests.get(f"{_GEOCLIENT_BASE}{path}", params=params,
                         headers=_headers(), timeout=8)
        return r.status_code, (r.json() if r.ok else r.text[:200])
    except Exception as exc:  # noqa: BLE001 - probe script, surface anything
        return None, f"{type(exc).__name__}: {exc}"


def _find_ids(obj, prefix=""):
    """Recursively collect keys that look like segment/node identifiers."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if k.lower() in WANTED and v not in (None, ""):
                hits.append((p, v))
            hits += _find_ids(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            hits += _find_ids(v, f"{prefix}[{i}]")
    return hits


def q1_intersection():
    print("=" * 70)
    print("Q1  /intersection — does it already carry segment/node ids?")
    print("=" * 70)
    params = {"crossStreetOne": CROSS_A, "crossStreetTwo": CROSS_B, "borough": BOROUGH}
    for path in ("/intersection.json", "/intersection"):
        code, data = _get(path, params)
        print(f"  {path}: HTTP {code}")
        if code != 200 or not isinstance(data, dict):
            print(f"    {str(data)[:160]}")
            continue
        inner = data.get("intersection") or data
        print(f"    inner keys ({len(inner)}): {sorted(inner)[:18]}")
        ids = _find_ids(data)
        if ids:
            print("    >>> IDENTIFIERS FOUND (Q1 answered YES — just extract these):")
            for k, v in ids:
                print(f"          {k} = {v}")
        else:
            print("    no segment/node identifiers in the response (Q1 = NO)")
        return bool(ids)
    return False


def q2_segment_endpoints():
    print()
    print("=" * 70)
    print("Q2  is there a segment/blockface endpoint?")
    print("=" * 70)
    attempts = [
        ("/blockface.json", {"onStreet": CONNECTOR_STREET, "crossStreetOne": CROSS_A,
                             "crossStreetTwo": "W 43 St", "borough": BOROUGH}),
        ("/segment.json", {"onStreet": CONNECTOR_STREET, "crossStreetOne": CROSS_A,
                           "crossStreetTwo": "W 43 St", "borough": BOROUGH}),
        ("/street.json", {"onStreet": CONNECTOR_STREET, "borough": BOROUGH}),
    ]
    found = False
    for path, params in attempts:
        code, data = _get(path, params)
        print(f"  {path}: HTTP {code}")
        if code == 200 and isinstance(data, dict):
            ids = _find_ids(data)
            print(f"    keys: {sorted(data)[:14]}")
            if ids:
                found = True
                print("    >>> IDENTIFIERS FOUND:")
                for k, v in ids:
                    print(f"          {k} = {v}")
        elif code is not None:
            print(f"    {str(data)[:120]}")
    return found


def q3_address_on_connector():
    print()
    print("=" * 70)
    print("Q3  /address.json on the CONNECTING street (fallback synthesis)")
    print("=" * 70)
    code, data = _get("/address.json", {
        "houseNumber": CONNECTOR_HOUSE, "street": CONNECTOR_STREET, "borough": BOROUGH})
    print(f"  HTTP {code}")
    if code == 200 and isinstance(data, dict):
        addr = data.get("address") or data
        ids = _find_ids(addr)
        print(f"    normalised: {addr.get('firstStreetNameNormalized')!r}")
        for k, v in ids:
            print(f"          {k} = {v}")
        return bool(ids)
    print(f"    {str(data)[:160]}")
    return False


if __name__ == "__main__":
    if not settings.geoclient_app_key:
        print("GEOCLIENT_APP_KEY is not set — cannot probe the live API.")
        print("Set it in backend/.env (config field: geoclient_app_key) and re-run.")
        sys.exit(2)

    print(f"base: {_GEOCLIENT_BASE}\n")
    a = q1_intersection()
    b = q2_segment_endpoints() if not a else False
    c = q3_address_on_connector() if not (a or b) else False

    print()
    print("=" * 70)
    print("VERDICT for ADR-236 D2")
    print("=" * 70)
    if a:
        print("  Q1 YES -> extract ids from /intersection. Cheapest path; no new endpoint.")
    elif b:
        print("  Q2 YES -> a segment/blockface endpoint exists. Use it for connector walks.")
    elif c:
        print("  Q3 YES -> synthesise connectors via /address.json on the connecting street.")
        print("            Workable but needs a plausible house number per connector.")
    else:
        print("  ALL NO -> connector segments are not reachable via these calls.")
        print("            ADR-236 D2 needs rethinking (e.g. import LION data directly:")
        print("            NYC publishes the LION street file, which would give the full")
        print("            topology without per-segment API calls).")
