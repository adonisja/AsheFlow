"""Personal Information erasure by what Amazon names (ADR-493).

DSP Agreement §7(b) obliges the DSP to delete Personal Information on Amazon's
request. A request names a customer ADDRESS or a PACKAGE (TBA) — never a row —
so this module answers "where does that value live?" from one registry and
erases it everywhere for one tenant, in one transaction.

THE REGISTRY GUARDS ITSELF (the ADR-464 pattern). `tests/services/
test_pi_erasure_drift.py` walks every mapped column whose name looks like an
address, a TBA or a note, and fails unless it is in REGISTRY or EXEMPT (with a
reason). A new address column therefore fails CI until someone decides how it is
erased — it cannot be silently forgotten.

How each kind of column is erased:

  delete_row   the row's identity IS the address (a building profile keyed on
               it); nulling the key would leave an orphan that means nothing.
  null         a nullable scalar; the row's other facts survive.
  placeholder  a NOT NULL scalar TBA, or an element of a TBA list. Replaced by
               "erased:<random>", unique per value. NOT removed: package counts
               are read as len(tba_numbers) everywhere (sort.py, walker_routes,
               rts), so a shorter list would silently change history.
  scrub        free text. Case-insensitive occurrences of the value (and of
               every stored spelling it matched) become "[erased]".

Addresses match on the door_key fold (ADR-417 D7), so "433 West 32nd Street"
erases "433 W 32 ST". The fold is deliberately lossy; the dry run lists every
stored spelling it matched so the person erasing confirms before anything goes.

Matching runs in Python over tenant-scoped rows, not in SQL: ARRAY and JSONB
membership differ between Postgres and the SQLite the tests run on, and an
erasure is a rare, manual, per-tenant action where a full scan is affordable.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.services.door_key import door_key

ERASED_TEXT = "[erased]"
PLACEHOLDER_PREFIX = "erased:"


def placeholder() -> str:
    return f"{PLACEHOLDER_PREFIX}{uuid.uuid4().hex[:12]}"


def is_placeholder(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(PLACEHOLDER_PREFIX)


def normalise_tba(value: str) -> str:
    return value.strip().upper()


def value_hash(kind: str, value: str, key: str) -> str:
    """HMAC of the normalised value. Addresses hash their door_key fold, so a
    restored row stored in any spelling of the same door still matches."""
    canon = door_key(value) if kind == "address" else normalise_tba(value)
    return hmac.new(key.encode(), f"{kind}:{canon}".encode(), hashlib.sha256).hexdigest()


# ── Registry ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Target:
    model: str            # "module:Class" under app.models
    column: str
    kind: str             # "address" | "tba" | "text"
    action: str           # "delete_row" | "null" | "placeholder" | "scrub"
    shape: str = "scalar" # "scalar" | "list" (ARRAY or JSONB list)
    tenant: bool = True   # filter by company_id; False = platform-only table


REGISTRY: tuple[Target, ...] = (
    # Address scalars — nulled within 48h by ADR-219; erasure covers the window.
    Target("delivery_stop:DeliveryStop",          "normalised_address", "address", "null"),
    Target("walker_route:MisroutedPackageFlag",   "normalised_address", "address", "null"),
    Target("rts:RTSPackage",                      "normalised_address", "address", "null"),
    Target("rts:MissingPackage",                  "normalised_address", "address", "null"),
    Target("rts:DamagedPackage",                  "normalised_address", "address", "null"),
    Target("tote_address:ToteAddress",            "normalised_address", "address", "null"),
    Target("tote_address:ToteAddress",            "raw_address",        "address", "null"),
    # Rows whose identity is the address.
    Target("building_profile:BuildingProfile",    "normalised_address", "address", "delete_row"),
    Target("collection:CollectedAddressProfile",  "address",            "address", "delete_row"),
    Target("building_profile_library:BuildingProfileLibrary", "normalised_address", "address",
           "delete_row", tenant=False),
    # Address lists (Route.stops JSONB is handled alongside normalised_addresses).
    Target("walker_route:Route",                  "normalised_addresses", "address", "placeholder", "list"),
    # TBAs.
    Target("walker_route:Route",                  "tba_numbers",        "tba", "placeholder", "list"),
    Target("delivery_stop:DeliveryStop",          "tba_numbers",        "tba", "placeholder", "list"),
    Target("tote_ops:PackageRemoval",             "tba_numbers",        "tba", "placeholder", "list"),
    Target("truck_zone:TruckZone",                "package_tbas",       "tba", "placeholder", "list"),
    Target("rts:RTSPackage",                      "tba_number",         "tba", "placeholder"),
    Target("rts:MissingPackage",                  "tba_number",         "tba", "placeholder"),
    Target("rts:DamagedPackage",                  "tba_number",         "tba", "placeholder"),
    Target("walker_route:MisroutedPackageFlag",   "tba_number",         "tba", "placeholder"),
    Target("tote_ops:PackageRemoval",             "tba",                "tba", "null"),
    # Free text that may name a door or a package.
    *(Target(m, c, "text", "scrub") for m, c in (
        ("anchor_point:AnchorPoint",              "notes"),
        ("building_profile:BuildingProfile",      "raw_note"),
        ("building_profile:BuildingProfile",      "operational_note"),
        ("building_profile:BuildingProfile",      "initial_anchor_note"),
        ("collection:CollectedAddressProfile",    "note"),
        ("rts:DamagedPackage",                    "damage_notes"),
        ("rts:DamagedPackage",                    "resolution_notes"),
        ("rts:MissingPackage",                    "resolution_notes"),
        ("rts:ReattemptAssignment",               "outcome_notes"),
        ("rts:RouteHandoff",                      "discrepancy_notes"),
        ("rts_clearance:RTSReport",               "dispatch_notes"),
        ("rts_clearance:StationHandoff",          "notes"),
        ("walker_route:LocationDifficultyFlag",   "notes"),
        ("package_manifest:PackageManifest",      "notes"),
        ("field_ops:FuelMileageLog",              "notes"),
        ("field_ops:VehicleInspection",           "notes"),
        ("gear_request:GearOrderItem",            "notes"),
        ("shift_roll_call:ShiftRollCall",         "notes"),
        ("training:TrainingRecord",               "observation_notes"),
        ("truck_transfer:TruckTransfer",          "note"),
        ("scorecard_appeal:ScorecardAppeal",      "outcome_notes"),
        ("scorecard_appeal:ScorecardAppealItem",  "outcome_notes"),
        ("scorecard_import:ScorecardImportPending", "note"),
        ("graduation_quiz:GraduationQuizResponse", "override_note"),   # found by the drift test
    )),
    Target("building_profile_library:BuildingProfileLibrary", "operational_note", "text", "scrub",
           tenant=False),
)

# Columns the drift test finds that are deliberately NOT erased. Every entry
# needs a reason; an unexplained exemption is how an allow-list becomes a leak.
EXEMPT: dict[tuple[str, str], str] = {
    ("building_profiles", "address_status"):
        "a resolution state ('pending'/'resolved'), not an address",
    ("collected_address_profiles", "address_flag"):
        "ADR-496 check result ('street_lost'/'no_street'), not an address",
    # ADR-504: the survey register. City addresses from public data (NYC
    # AddressPoint), observed outside any carrier's services by the owner and
    # named contributors. Not Personal Information concerning a carrier's
    # customers, and not Collected Data, by construction (D2, D3). The note is
    # scrubbed at write and refuses codes (D4).
    ("survey_observations", "address"):
        "ADR-504 register: a public city address observed outside the Services, not customer PI",
    ("survey_observations", "note"):
        "ADR-504 register: building facts only, scrubbed at write, codes refused (D4)",
    ("survey_walks", "addresses"):
        "ADR-504 register: a snapshot of NYC AddressPoint for one block (public data)",
    ("survey_receives_for", "address"):
        "ADR-504 D8: a same-block door from the walk's AddressPoint snapshot (public data)",
    ("incidents", "packages_tba"):
        "an INTEGER count of packages involved, not a package id",
    ("street_segments", "x_low_address_end"):  "public NYC street topology (house-number ranges)",
    ("street_segments", "x_high_address_end"): "public NYC street topology (house-number ranges)",
    ("street_segments", "y_low_address_end"):  "public NYC street topology (house-number ranges)",
    ("street_segments", "y_high_address_end"): "public NYC street topology (house-number ranges)",
    ("trucks", "initial_anchor_address"):
        "the DSP's own truck staging point on a public street, not a customer",
    ("trucks", "initial_anchor_display_address"):
        "the DSP's own truck staging point on a public street, not a customer",
    ("trucks", "initial_anchor2_address"):
        "the DSP's own truck staging point on a public street, not a customer",
    ("trucks", "initial_anchor2_display_address"):
        "the DSP's own truck staging point on a public street, not a customer",
}

# Audit snapshot keys that carry an address or a TBA (ADR-493 D8). Snapshots
# whose target is a truck are excluded: there "address" is the DSP's staging
# point (trucks.py), the same exemption as above.
AUDIT_ADDRESS_KEYS = frozenset({"normalised_address", "address", "raw_address"})
AUDIT_TBA_KEYS = frozenset({"tba", "tba_number", "tba_numbers", "package_tbas"})
AUDIT_EXEMPT_TARGETS = frozenset({"trucks"})


def resolve(target: Target):
    import importlib
    module, cls = target.model.split(":")
    return getattr(importlib.import_module(f"app.models.{module}"), cls)


# ── Matching ────────────────────────────────────────────────────────────────

@dataclass
class Request:
    kind: str                    # "address" | "tba"
    value: str
    company_id: Optional[uuid.UUID]   # None = platform scope (tenant-less rows only)

    @property
    def key(self) -> str:
        return door_key(self.value) if self.kind == "address" else normalise_tba(self.value)

    def matches(self, stored: Any) -> bool:
        if not isinstance(stored, str) or not stored or is_placeholder(stored):
            return False
        if self.kind == "address":
            return door_key(stored) == self.key
        return normalise_tba(stored) == self.key


@dataclass
class Result:
    counts: dict[str, int] = field(default_factory=dict)
    matched_spellings: set[str] = field(default_factory=set)

    def add(self, label: str, n: int = 1) -> None:
        if n:
            self.counts[label] = self.counts.get(label, 0) + n


# ADR-503. Rows are read in pages of this many, ordered by primary key, so no
# scan holds a table in memory. The first build used `.all()` and was killed by
# the kernel at 2.9 GB on staging's 1.19M delivery stops for one tenant.
PAGE_SIZE = 2000


def _like(token: str) -> str:
    return "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def candidate_tokens(req: "Request") -> list[str]:
    """Substrings EVERY matching stored value must contain (ADR-503).

    A necessary condition, so filtering on it in SQL can never lose a match:

    - address: each token of door_key(value) that the fold does NOT produce
      by rewriting. Numbers survive ("32nd" -> "32", and "32" is in "32nd");
      names survive ("penn"). Directions ("w" from "West") and street types
      ("st" from "Street") are excluded: the stored text may spell them
      differently, and "ave" is not in "av".
    - tba: the normalised id itself.

    An empty list means no safe pre-filter exists; the scan is then paged but
    unfiltered.
    """
    if req.kind == "tba":
        return [req.key] if req.key else []
    from app.services import door_key as dk
    folded = set(_DIRECTIONS) | {canon for _, canon in dk._STREET_TYPES}
    return [t for t in door_key(req.value).split() if t not in folded]


def _prefilter(columns, req: "Request"):
    """SQL clause: every candidate token appears in at least one of `columns`
    (cast to text, so ARRAY and JSONB columns are searched too)."""
    from sqlalchemy import Text, and_, cast, or_
    toks = candidate_tokens(req)
    if not toks:
        return None
    per_col = [and_(*[cast(c, Text).ilike(_like(t), escape="\\") for t in toks]) for c in columns]
    return per_col[0] if len(per_col) == 1 else or_(*per_col)


def _rows(db: Session, model, req: Request, tenant: bool, where=None):
    """Tenant scope sees that tenant's rows. Platform scope (company_id None)
    sees only rows that belong to NO tenant — open-campaign collected rows,
    tenant-less audit rows — and the tenant-less tables (the Library).

    A generator, paged by primary key (ADR-503). `where` is the candidate
    pre-filter from `_prefilter`."""
    q = db.query(model)
    if tenant:
        if req.company_id is None:
            q = q.filter(model.company_id.is_(None))
        else:
            q = q.filter(model.company_id == req.company_id)
    elif req.company_id is not None:
        return         # tenant-less tables are platform scope only
    if where is not None:
        q = q.filter(where)
    pk = model.__mapper__.primary_key[0]
    last = None
    while True:
        page_q = q.order_by(pk)
        if last is not None:
            page_q = page_q.filter(pk > last)
        page = page_q.limit(PAGE_SIZE).all()
        if not page:
            return
        last = getattr(page[-1], pk.key)
        yield from page
        if len(page) < PAGE_SIZE:
            return


_DIRECTIONS = {"n": "north", "s": "south", "e": "east", "w": "west"}


def address_text_pattern(value: str) -> Optional[re.Pattern]:
    """A pattern for free text that matches ANY spelling door_key folds to the
    same key: "433 W 32 ST" also finds "433 w. 32nd street".

    Built from the fold's own tables (door_key._STREET_TYPES), so the inverse
    cannot drift from the forward rule. Substring matching alone missed
    natural spellings in notes — the case the erasure test caught.
    """
    from app.services import door_key as dk
    tokens = door_key(value).split()
    if not tokens:
        return None
    parts = []
    for tok in tokens:
        if tok.isdigit():
            parts.append(rf"{tok}(?:st|nd|rd|th)?")
        elif tok in _DIRECTIONS:
            parts.append(rf"(?:{tok}|{_DIRECTIONS[tok]})\.?")
        else:
            alts = next((pat.pattern for pat, canon in dk._STREET_TYPES if canon == tok), None)
            # pat.pattern is r"\b(street|st)\b" — reuse its alternation group.
            parts.append(rf"(?:{alts[2:-2]})\.?" if alts else re.escape(tok))
    return re.compile(r"\b" + r"[\s.,#]+".join(parts) + r"\b", re.IGNORECASE)


def _scrub_text(text: str, needles: set[str], patterns: list[re.Pattern] = ()) -> str:
    out = text
    for pat in patterns:
        out = pat.sub(ERASED_TEXT, out)
    for n in sorted(needles, key=len, reverse=True):
        if n:
            out = re.sub(re.escape(n), ERASED_TEXT, out, flags=re.IGNORECASE)
    return out


def _scrub_json(obj: Any, req: Request, keys: frozenset[str]) -> tuple[Any, int]:
    """Replace matching values under `keys`, at any depth. Returns (obj, hits)."""
    hits = 0
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in keys:
                if isinstance(v, list):
                    new = [ERASED_TEXT if req.matches(x) else x for x in v]
                    hits += sum(1 for a, b in zip(v, new) if a != b)
                    out[k] = new
                elif req.matches(v):
                    out[k] = ERASED_TEXT
                    hits += 1
                else:
                    out[k] = v
            else:
                out[k], h = _scrub_json(v, req, keys)
                hits += h
        return out, hits
    if isinstance(obj, list):
        out = []
        for v in obj:
            nv, h = _scrub_json(v, req, keys)
            out.append(nv)
            hits += h
        return out, hits
    return obj, 0


def blank_keys(obj: Any, keys: frozenset[str]) -> tuple[Any, int]:
    """Retention variant of `_scrub_json`: blank EVERY value under `keys`, not
    just one requested value. Placeholders and nulls are left alone, so a
    second run over the same row reports 0 — the counts mean something."""
    hits = 0
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in keys:
                if isinstance(v, list):
                    new = [ERASED_TEXT if isinstance(x, str) and x and x != ERASED_TEXT
                           and not is_placeholder(x) else x for x in v]
                    hits += sum(1 for a, b in zip(v, new) if a != b)
                    out[k] = new
                elif isinstance(v, str) and v and v != ERASED_TEXT and not is_placeholder(v):
                    out[k] = ERASED_TEXT
                    hits += 1
                else:
                    out[k] = v
            else:
                out[k], h = blank_keys(v, keys)
                hits += h
        return out, hits
    if isinstance(obj, list):
        out = []
        for v in obj:
            nv, h = blank_keys(v, keys)
            out.append(nv)
            hits += h
        return out, hits
    return obj, 0


def placeholder_all(items) -> tuple[list, int]:
    """Replace every real TBA in a list with a placeholder, keeping the length."""
    items = list(items or [])
    n = 0
    for i, x in enumerate(items):
        if isinstance(x, str) and x and not is_placeholder(x):
            items[i] = placeholder()
            n += 1
    return items, n


# ── Erasure ─────────────────────────────────────────────────────────────────

def erase(db: Session, req: Request, *, dry_run: bool) -> Result:
    """Erase `req.value` everywhere in scope. Does NOT commit.

    Ordering: address/TBA targets first (they discover the stored spellings),
    then free text and audit snapshots, which scrub every spelling found.
    """
    res = Result()
    kind_targets = [t for t in REGISTRY if t.kind == req.kind]
    text_targets = [t for t in REGISTRY if t.kind == "text"]

    for t in kind_targets:
        model = resolve(t)
        label = f"{model.__tablename__}.{t.column}"
        for row in _rows(db, model, req, t.tenant,
                         _prefilter([getattr(model, t.column)], req)):
            val = getattr(row, t.column)
            if t.shape == "list":
                items = list(val or [])
                hit = [i for i, x in enumerate(items) if req.matches(x)]
                if not hit:
                    continue
                res.matched_spellings.update(items[i] for i in hit)
                res.add(label, len(hit))
                if not dry_run:
                    for i in hit:
                        items[i] = placeholder()
                    setattr(row, t.column, items)
                    flag_modified(row, t.column)
                continue
            if not req.matches(val):
                continue
            res.matched_spellings.add(val)
            res.add(label)
            if dry_run:
                continue
            if t.action == "delete_row":
                _delete_with_children(db, row)
            elif t.action == "null":
                setattr(row, t.column, None)
            elif t.action == "placeholder":
                setattr(row, t.column, placeholder())

    # Route.stops JSONB repeats what the flat lists hold (ADR-194 double
    # storage), and can still hold it after the lists were scrubbed — one pass.
    from app.models.walker_route import Route
    for row in _rows(db, Route, req, True, _prefilter([Route.stops], req)):
        _erase_route_stops(row, req, res, dry_run)

    needles = {req.value} | res.matched_spellings
    patterns = []
    if req.kind == "address":
        patterns = [p for p in {address_text_pattern(v) for v in needles} if p is not None]
    for t in text_targets:
        model = resolve(t)
        label = f"{model.__tablename__}.{t.column}"
        # Every needle (the value and each matched spelling) folds to the
        # same key, so each contains the request's candidate tokens: the same
        # pre-filter is safe for free text.
        for row in _rows(db, model, req, t.tenant,
                         _prefilter([getattr(model, t.column)], req)):
            val = getattr(row, t.column)
            if not isinstance(val, str) or not val:
                continue
            new = _scrub_text(val, needles, patterns)
            if new != val:
                res.add(label)
                if not dry_run:
                    setattr(row, t.column, new)

    _erase_audit(db, req, res, dry_run)
    if not dry_run:
        db.flush()
    return res


def _erase_route_stops(route, req: Request, res: Result, dry_run: bool) -> None:
    """Route.stops JSONB (ADR-194 double storage): per stop, 'address' and a
    'tba_numbers' list. Address → key dropped (as the 48h job does); TBA →
    placeholder, length kept."""
    stops = route.stops or []
    changed = False
    hits = 0
    new_stops = []
    for s in stops:
        s = dict(s or {})
        if req.kind == "address" and req.matches(s.get("address")):
            res.matched_spellings.add(s["address"])
            hits += 1
            if not dry_run:
                s.pop("address", None)
                changed = True
        if req.kind == "tba" and isinstance(s.get("tba_numbers"), list):
            items = list(s["tba_numbers"])
            idx = [i for i, x in enumerate(items) if req.matches(x)]
            if idx:
                hits += len(idx)
                if not dry_run:
                    for i in idx:
                        items[i] = placeholder()
                    s["tba_numbers"] = items
                    changed = True
        new_stops.append(s)
    res.add("routes.stops", hits)
    if changed:
        route.stops = new_stops
        flag_modified(route, "stops")


def _delete_with_children(db: Session, row) -> None:
    """Delete a row keyed on the address. Children first, explicitly (ADR-231):
    an unverified ON DELETE CASCADE is a delete nobody wrote."""
    from app.models.building_profile import BuildingProfile
    if isinstance(row, BuildingProfile):
        from app.models.building_profile_verification import BuildingProfileVerification
        db.query(BuildingProfileVerification).filter(
            BuildingProfileVerification.company_id == row.company_id,
            BuildingProfileVerification.profile_id == row.id,
        ).delete(synchronize_session=False)
    db.delete(row)


def _erase_audit(db: Session, req: Request, res: Result, dry_run: bool) -> None:
    """ADR-493 D8 — audit snapshots copy addresses and TBAs (rts, package
    intake, collection). Values are replaced in place; keys stay, so the row
    still says what kind of thing happened."""
    from app.models.audit_log import AuditLog
    keys = AUDIT_ADDRESS_KEYS if req.kind == "address" else AUDIT_TBA_KEYS
    where = AuditLog.target_table.notin_(AUDIT_EXEMPT_TARGETS)
    pre = _prefilter([AuditLog.before_snapshot, AuditLog.after_snapshot], req)
    if pre is not None:
        from sqlalchemy import and_
        where = and_(where, pre)
    for a in _rows(db, AuditLog, req, True, where):
        total = 0
        for col in ("before_snapshot", "after_snapshot"):
            snap = getattr(a, col)
            if not snap:
                continue
            new, hits = _scrub_json(snap, req, keys)
            if hits:
                total += hits
                if not dry_run:
                    setattr(a, col, new)
                    flag_modified(a, col)
        res.add("audit_logs.snapshots", total)


# ── Ledger replay (ADR-493 D3) ──────────────────────────────────────────────

def replay_ledger(db: Session, key: str, since) -> dict:
    """Re-apply every ledger entry recorded since `since` after a backup restore.

    The ledger holds only HMACs, so replay works backwards: hash every distinct
    value currently stored in a registered column, and erase the ones whose hash
    is in the ledger. Does NOT commit.
    """
    from app.models.pi_erasure_ledger import PiErasureLedger
    entries = db.query(PiErasureLedger).filter(PiErasureLedger.erased_at >= since).all()
    wanted = {(e.company_id, e.kind, e.value_hash) for e in entries}
    if not wanted:
        return {"entries": 0, "erased": 0}

    erased = 0
    for company_id, kind, h in sorted(wanted, key=str):
        req_probe = Request(kind=kind, value="", company_id=company_id)
        for value in _distinct_values(db, req_probe):
            if value_hash(kind, value, key) == h:
                erase(db, Request(kind=kind, value=value, company_id=company_id), dry_run=False)
                erased += 1
    return {"entries": len(wanted), "erased": erased}


def _distinct_values(db: Session, probe: Request) -> set[str]:
    out: set[str] = set()
    for t in REGISTRY:
        if t.kind != probe.kind:
            continue
        model = resolve(t)
        # Replay must see EVERY value (it hashes them), so no pre-filter, but
        # still paged (ADR-503).
        for row in _rows(db, model, probe, t.tenant):
            val = getattr(row, t.column)
            vals = val if t.shape == "list" else [val]
            out.update(v for v in (vals or []) if isinstance(v, str) and v and not is_placeholder(v))
    return out
