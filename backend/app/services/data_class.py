"""Tenant data-class filtering for cross-tenant queries (ADR-280 D5).

SCOPE — read this before using it
---------------------------------
Almost every read in this codebase is already scoped to `caller.company_id`,
and those queries must NOT use these helpers. A user inside a seed tenant
seeing seeded numbers is correct behaviour; filtering their dashboard on
`data_class = 'live'` would return an empty page and "fix" nothing.

These exist for the queries that span tenants:

  * super-admin surfaces (`companies.py`) — where the answer is "show the
    class", not "hide the rows"
  * ad-hoc analysis and reporting run against the whole database
  * fault-injection / chaos harnesses choosing a target

That last category is where the real damage happened. The ADR-279 measurement
read `segment_ids` coverage as 44/46,889 (0.09%) — apparently a broken feature.
580 of those rows were backdated seed data that structurally cannot carry the
field. The true figure was 44/44. The query had no way to exclude them, so the
analysis fell back to eyeballing a shared `created_at` timestamp.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.models.company import Company

LIVE = "live"
SEED = "seed"
DEMO = "demo"


def live_company_ids(db: Session) -> list:
    """Ids of tenants holding real operational data.

    The building block for an ad-hoc query: filter any tenant-scoped table with
    `Model.company_id.in_(live_company_ids(db))` and the result describes
    production rather than a mixture.
    """
    return [
        row.id
        for row in db.query(Company.id).filter(Company.data_class == LIVE).all()
    ]


def only_live(q: Query, model) -> Query:
    """Restrict a tenant-scoped query to live tenants.

    Takes the model explicitly rather than inferring it from the query: an
    inferred entity is wrong the moment the query joins, and silently wrong —
    it would filter on the joined table's company_id instead, which is the
    exact class of error this module exists to prevent.
    """
    return q.join(Company, Company.id == model.company_id).filter(
        Company.data_class == LIVE
    )


def class_breakdown(db: Session, model) -> dict[str, int]:
    """Row counts per data class for one model.

    Reporting the split is usually better than filtering it away: it answers
    "is this number real?" AND "how much of the table is synthetic?" in one
    query, which is what the ADR-279 analysis actually needed.
    """
    # GROUP BY in the database, not a Python loop over every row. The table
    # this was written for holds 1,194,365 delivery stops; materialising that
    # to count it would be a self-inflicted outage on a diagnostic helper.
    rows = (
        db.query(Company.data_class, func.count(model.company_id))
        .join(model, model.company_id == Company.id)
        .group_by(Company.data_class)
        .all()
    )
    return {data_class: count for data_class, count in rows}
