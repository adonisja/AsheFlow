"""Shared guard for seed scripts (ADR-280 D3).

WHAT THIS PREVENTS
------------------
Before this, four seed scripts resolved their target like:

    company = db.query(Company).first()      # no filter, unordered

and seed_training_curriculum.py defaulted to *every* company. On any database
containing a live tenant, either writes fabricated operational history into
real customer data — and because every row is well-formed and correctly
company-scoped, nothing downstream would flag it.

USAGE
-----
    from _seed_guard import seed_target

    company = seed_target(db)                  # the seedable tenant
    company = seed_target(db, slug="dsp-test") # a specific one, still guarded

Both forms refuse a `live` tenant. There is deliberately no --force override:
the single scenario it would serve — "I really do want to seed production" —
is the one that must never be one flag away.
"""
from __future__ import annotations

from app.models.company import Company

LIVE = "live"


def seed_target(db, slug: str | None = None) -> Company:
    """Resolve the company a seed script may write to.

    Raises SystemExit rather than returning None: a seed that cannot find a
    safe target must stop, not continue with something arbitrary.
    """
    q = db.query(Company)

    if slug:
        company = q.filter(Company.slug == slug).first()
        if company is None:
            # Distinct from "nothing seedable exists". A typo'd slug reported
            # as an empty database sends the operator off to create a company
            # they already have.
            raise SystemExit(f"No company with slug {slug!r}.")
    else:
        # order_by(slug), not a bare .first(): an unordered .first() is not
        # deterministic, so the scripts this replaces were not reproducible
        # across runs even when they happened to pick a safe tenant.
        company = (
            q.filter(Company.data_class != LIVE).order_by(Company.slug).first()
        )
        if company is None:
            raise SystemExit(
                "No seedable company. Create one with data_class='seed'."
            )

    if company.data_class == LIVE:
        raise SystemExit(
            f"Refusing to seed {company.slug!r}: data_class='live'. "
            "Seeding a live tenant would write fabricated operational history "
            "into real customer data. If this tenant really is disposable, set "
            "its data_class to 'seed' deliberately."
        )
    return company


def assert_seedable(db, company_id: str) -> Company:
    """Guard an explicitly-supplied company id (ADR-280 D3).

    A script that accepts `sys.argv[1]` must still check it. Otherwise the one
    path a human types by hand — and therefore the one most likely to carry a
    copy-pasted production id — is the only path with no protection.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise SystemExit(f"No company with id {company_id!r}.")
    if company.data_class == LIVE:
        raise SystemExit(
            f"Refusing to seed {company.slug!r}: data_class='live'."
        )
    return company


def seed_targets(db) -> list[Company]:
    """Every company a seed script may write to, for scripts that fan out.

    seed_training_curriculum.py defaulted to `db.query(Company).all()`, i.e.
    every tenant including live ones. This is that query with the guarantee.
    """
    return (
        db.query(Company)
        .filter(Company.data_class != LIVE)
        .order_by(Company.slug)
        .all()
    )


def assert_not_live(company: Company) -> None:
    """Precondition for destructive work (fault injection, wipes) — ADR-280 D4.

    Checked at the point of damage, so the guarantee is a property of the
    target rather than a fact about which slug someone typed.
    """
    if company.data_class == LIVE:
        raise SystemExit(
            f"Refusing destructive operation on {company.slug!r}: "
            "data_class='live'."
        )
