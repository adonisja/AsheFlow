"""Bag color — the physical Amazon tote color, parsed from the manifest's
"Bag Labels" column and threaded through the sort to the clients (ADR-230).

The manifest lists each bag as ``<Color> <number>`` (e.g. ``Orange 6218``), with
the cell shaded the bag's physical color. The color is REAL data, not
system-assigned: we parse the leading color word here, normalise it to a known
enum, and map it to a dark-mode-safe hex. This module is the SINGLE source of
truth for bag color — clients receive the resolved hex and do no color logic.
An unknown / missing color resolves to ``None`` (clients render a neutral pill).
"""
from __future__ import annotations

# Known physical bag colors → dark-mode-safe hex (fill/text tint on the client).
# Navy is intentionally a lighter blue than true navy so it stays legible on a
# dark surface (true navy on dark is invisible). Keys are the normalised enum.
BAG_COLOR_HEX: dict[str, str] = {
    "black":  "#94A3B8",   # slate — true black is invisible on dark; use a neutral slate
    "green":  "#10B981",
    "yellow": "#EAB308",
    "orange": "#F97316",
    "navy":   "#3B82F6",   # lighter blue for dark-mode legibility
}

# Label words we accept, normalised to the enum above. "blue" is an alias for navy
# (the physical bags are navy; drivers may say "blue").
_COLOR_ALIASES: dict[str, str] = {
    "black":  "black",
    "green":  "green",
    "yellow": "yellow",
    "orange": "orange",
    "navy":   "navy",
    "blue":   "navy",
}


def parse_bag_label(label: str | None) -> tuple[str | None, str | None]:
    """Split a manifest bag label into (bag_id, bag_color_hex).

    Label format is ``<Color> <number>`` (e.g. "Orange 6218"). Returns the
    numeric id and the resolved hex. Tolerant:
      - "Orange 6218"  -> ("6218", "#F97316")
      - "6218"         -> ("6218", None)      # no color word
      - "Purple 9"     -> ("9",    None)      # unknown color -> neutral pill
      - None / ""      -> (None,   None)
    The id is whatever follows the (optional) leading color word, stripped.
    """
    if not label:
        return None, None
    parts = label.strip().split(None, 1)   # split on first run of whitespace
    if len(parts) == 2:
        color_word, rest = parts[0], parts[1].strip()
        enum = _COLOR_ALIASES.get(color_word.lower())
        if enum is not None:
            return (rest or None), BAG_COLOR_HEX[enum]
        # First token isn't a known color — treat the whole thing as the id.
        return label.strip(), None
    # Single token — no color word; it's just the id.
    return parts[0], None


def color_hex(color: str | None) -> str | None:
    """Resolve a color enum/alias name to its hex, or None if unknown."""
    if not color:
        return None
    enum = _COLOR_ALIASES.get(color.strip().lower())
    return BAG_COLOR_HEX[enum] if enum else None
