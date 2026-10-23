"""Build app/data/street_lexicon.json from NYC AddressPoint (ADR-582 D1).

Usage:  python scripts/build_street_lexicon.py

Every distinct (boroughcode, full_street_name) in the city's AddressPoint
dataset, whitespace collapsed (AddressPoint pads some names: 'E  28 ST'). This
is PUBLIC data and the target vocabulary of the address standard: an address
is canonical when its street is spelled exactly as the city spells it. The
phase-3 PlaceType seed (ADR-583) refreshes it on the same schedule.
"""
import json
import pathlib
import sys
import urllib.parse
import urllib.request

DATASET = "uf93-f8nk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "app" / "data" / "street_lexicon.json"


def main() -> int:
    q = urllib.parse.urlencode({
        "$select": "full_street_name,boroughcode,count(*) as n",
        "$group": "full_street_name,boroughcode",
        "$limit": "50000",
    })
    with urllib.request.urlopen(f"https://data.cityofnewyork.us/resource/{DATASET}.json?{q}", timeout=120) as r:
        rows = json.load(r)
    lex: dict[str, list[str]] = {}
    for row in rows:
        name = " ".join((row.get("full_street_name") or "").split()).upper()
        boro = str(row.get("boroughcode") or "").strip()
        if name and boro in {"1", "2", "3", "4", "5"}:
            lex.setdefault(boro, []).append(name)
    out = {b: sorted(set(v)) for b, v in sorted(lex.items())}
    OUT.write_text(json.dumps({"source": f"NYC Open Data {DATASET} (AddressPoint)",
                               "boroughs": out}, indent=0, sort_keys=True) + "\n")
    print(f"wrote {OUT} — {sum(len(v) for v in out.values())} names across {len(out)} boroughs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
