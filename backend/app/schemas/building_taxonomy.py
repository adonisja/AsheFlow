"""The building taxonomy: category, type, and workload tags (ADR-418).

REPLACES the flat nine-value `BUILDING_TYPES` enum. Three things changed, and
each was a thing the flat list could not say:

1. **Category and type are separate fields.** "Residential" and "Commercial"
   are real distinctions a walker makes before anything else, and the old list
   encoded them only in a `biz_` prefix convention that nothing enforced.

2. **Security desk is a flag, not a type.** `biz_security` forced a choice: a
   loading dock WITH a security desk had to be filed as one or the other. It is
   an attribute of the door, so it is a boolean.

3. **Workload is a SET, not one value.** A doorman building that is also 20+
   floors is genuinely both `bulk_drop` and `high_rise`; the old single value
   made that unrepresentable. It is also no longer derived — see below.

## Why workload is no longer derived from type

`derive_workload_class()` mapped each type to exactly one workload, which is a
guess dressed as data: it is right often enough to be believed and wrong often
enough to mislead. A walk-up is usually high-touch, but a three-unit walk-up
where everything goes to one vestibule is a bulk drop.

So workload is collected, not computed. `NOT_APPLICABLE` exists so that "none
of these apply" is a statement the collector made, distinguishable from an
empty list meaning they never got to it — and an empty list is now a validation
error rather than a silently-accepted blank.
"""
from __future__ import annotations

# ── Categories ───────────────────────────────────────────────────────────────

BUILDING_CATEGORIES = frozenset({"residential", "commercial", "unknown"})

# ── Types, by category ───────────────────────────────────────────────────────
#
# The LEAF is what gets stored in `building_type`. Nesting in the UI
# (Store front -> Receptionist) is presentation; a leaf is globally unique so a
# type never needs its parent to be interpreted.

_RESIDENTIAL_TYPES = {
    "walkup",
    "elevator",
    "doorman_reception",   # doorman and receptionist do the same job at the door
    "mailroom",
    "lockers",             # parcel lockers are their own delivery flow
    # Public housing is its own delivery reality, not a walk-up or an elevator
    # building that happens to be public: multiple buildings behind one address,
    # numbered entrances, and access rules that differ from private stock.
    "public_housing",
}

_COMMERCIAL_TYPES = {
    "storefront_reception",
    "storefront_front_door",
    "freight",
    "loading_dock",
    "loading_dock_mailroom",   # a dock that routes through a mail room
}

# The sentinel for a building nothing has observed yet. NOT a real
# classification: address_inventory.py and place_geometry.py write it when they
# bootstrap a row from an address with no visit behind it. It must survive any
# taxonomy change untouched, or every un-observed building silently becomes a
# real type nobody ever saw.
UNKNOWN_TYPE = "unknown"

BUILDING_TYPES = frozenset(_RESIDENTIAL_TYPES | _COMMERCIAL_TYPES | {UNKNOWN_TYPE})

TYPE_TO_CATEGORY: dict[str, str] = {
    **{t: "residential" for t in _RESIDENTIAL_TYPES},
    **{t: "commercial" for t in _COMMERCIAL_TYPES},
    UNKNOWN_TYPE: "unknown",
}


def category_for(building_type: str) -> str:
    """The category a type belongs to. Derived, never stored twice.

    The category IS a stored column (the answer to "show me all residential"
    should not need a lookup table in SQL), but it is always written from here
    rather than accepted from a client — two independently-supplied fields drift,
    and a row claiming residential/loading_dock is worse than no row.
    """
    return TYPE_TO_CATEGORY.get(building_type, "unknown")


# ── Workload tags (multi-select) ─────────────────────────────────────────────

WORKLOAD_TAGS = frozenset({
    "bulk_drop",       # hand off many packages at once
    "door_to_door",    # each package to the customer's own door
    "high_rise",       # 20+ floors
    "high_wait",       # queues, sign-in, dock waits
    "other",           # something the four above do not describe; needs text
})

OTHER = "other"

# Combinations that cannot both be true of one door.
#
# A walk-up is defined by the absence of an elevator, which caps it at a handful
# of floors and forces every package up the stairs individually. It is therefore
# neither a high-rise nor a bulk drop, and a row claiming otherwise is a
# mis-click rather than an observation.
#
# Enforced on BOTH sides. The client disables the boxes, which is the good
# experience; the server rejects the pair, which is the actual guarantee —
# /collection/submit is public, so anything holding a token can post whatever
# it likes.
INCOMPATIBLE_WITH_TYPE: dict[str, frozenset[str]] = {
    "walkup": frozenset({"high_rise", "bulk_drop"}),
}


def validate_workloads(tags: list[str], building_type: str | None = None) -> None:
    """A profile must SAY something about workload, and not contradict itself.

    An empty list is indistinguishable from "not filled in", so it is rejected:
    `other` (with text) is how a collector says the four tags do not fit.

    `building_type` is optional so the function is still usable where the type
    is not to hand, but the caller that has it SHOULD pass it — that is the only
    place the walk-up rules can be checked.
    """
    if not tags:
        raise ValueError(
            "At least one workload must be selected. "
            "Use 'other' if none of them fit."
        )
    unknown = sorted(set(tags) - WORKLOAD_TAGS)
    if unknown:
        raise ValueError(f"Unknown workload tags: {unknown}")

    if building_type:
        clash = sorted(INCOMPATIBLE_WITH_TYPE.get(building_type, frozenset()) & set(tags))
        if clash:
            raise ValueError(
                f"{building_type!r} cannot also be {', '.join(clash)}."
            )


# ── Migration mapping ────────────────────────────────────────────────────────
#
# Old flat value -> new leaf type. Used by the migration and kept afterwards so
# an old export or a stale client payload can still be read.
#
# `biz_security` is the one that loses information in the type and gains it in
# the flag: it becomes a front-door storefront WITH has_security_desk=True.
LEGACY_TYPE_MAP: dict[str, str] = {
    "walkup":            "walkup",
    "elevator":          "elevator",
    "doorman":           "doorman_reception",
    "receptionist":      "doorman_reception",
    "mailroom":          "mailroom",
    "biz_front":         "storefront_front_door",
    "biz_freight":       "freight",
    "biz_security":      "storefront_front_door",   # + has_security_desk
    "biz_loading_dock":  "loading_dock",
    UNKNOWN_TYPE:        UNKNOWN_TYPE,
}

LEGACY_SECURITY_DESK = frozenset({"biz_security"})


# ── Protocol ─────────────────────────────────────────────────────────────────

BUILDING_TYPE_PROTOCOL: dict[str, str] = {
    "walkup":                 "Photo at front door.",
    "elevator":               "Photo at front door.",
    "doorman_reception":      "Hand to doorman or receptionist. Get a name if required.",
    "mailroom":               "Photo of packages in the mail room.",
    "lockers":                "Scan into the locker bank. Photo of the locker number.",
    "public_housing":         "Check the building and entrance number. Photo at the door.",
    "storefront_reception":   "Get the receptionist's name.",
    "storefront_front_door":  "Photo at front door or get the receptionist's name.",
    "freight":                "Use the freight entrance. Photo at the door.",
    "loading_dock":           "Photo at the loading dock or get the clerk's name.",
    "loading_dock_mailroom":  "Deliver through the dock to the mail room. Get a name.",
    UNKNOWN_TYPE:             "Not yet observed. Record what you find.",
}

SECURITY_DESK_PROTOCOL = "Requires photo ID."
