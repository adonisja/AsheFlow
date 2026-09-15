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
    "lockers",             # NEW: parcel lockers are their own delivery flow
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
    "not_applicable",  # an explicit "none of these", not a blank
})

NOT_APPLICABLE = "not_applicable"


def validate_workloads(tags: list[str]) -> None:
    """A profile must SAY something about workload.

    An empty list used to be indistinguishable from "not filled in". Requiring
    an explicit `not_applicable` makes the difference visible in the data, which
    is the whole reason the tag exists.
    """
    if not tags:
        raise ValueError(
            "At least one workload must be selected. "
            "Use 'not_applicable' if none apply."
        )
    unknown = sorted(set(tags) - WORKLOAD_TAGS)
    if unknown:
        raise ValueError(f"Unknown workload tags: {unknown}")
    if NOT_APPLICABLE in tags and len(tags) > 1:
        raise ValueError(
            "'not_applicable' means none apply; it cannot be combined "
            "with another workload."
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
    "storefront_reception":   "Get the receptionist's name.",
    "storefront_front_door":  "Photo at front door or get the receptionist's name.",
    "freight":                "Use the freight entrance. Photo at the door.",
    "loading_dock":           "Photo at the loading dock or get the clerk's name.",
    "loading_dock_mailroom":  "Deliver through the dock to the mail room. Get a name.",
    UNKNOWN_TYPE:             "Not yet observed. Record what you find.",
}

SECURITY_DESK_PROTOCOL = "Bring ID. This door has a security desk."
