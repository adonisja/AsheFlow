"""Remove every trace of one tenant (ADR-450).

WHY THIS IS NOT A LIST. Measured against the live production schema:

    tables carrying company_id .......... 94
    foreign keys pointing at companies .. 35

Fifty-nine tables have NO referential link to the company they belong to, so a
cascade never reaches them and a hand-written list is wrong the day a
gitignored module adds a table. The ORM sees 63 models; the database sees 94
tables. Only `information_schema` sees all of them.

Irreversible by design (ADR-431): no tombstone, no archive. Export first.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

# `companies` is deleted last, by name, after everything referencing it.
_PARENT = "companies"


@dataclass
class PurgeReport:
    """What the purge found and removed. The counts ARE the evidence.

    A purge that reports only "done" tells an operator nothing about whether it
    found 233 employees or zero (ADR-450 D2).
    """
    company_id: str
    company_name: str
    rows_by_table: dict[str, int] = field(default_factory=dict)
    cognito_users_deleted: int = 0
    cognito_client_deleted: bool = False
    cognito_errors: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(self.rows_by_table.values())


def _tenant_tables(db: Session) -> list[str]:
    """Every table carrying a company_id column, read from the database.

    Not a constant and not a model walk: proprietary modules ship their own
    tables, and a list that must be maintained to stay correct will not be.
    """
    rows = db.execute(text("""
        SELECT table_name
        FROM information_schema.columns
        WHERE column_name = 'company_id'
          AND table_schema = 'public'
        ORDER BY table_name
    """)).fetchall()
    return [r[0] for r in rows]


def _delete_order(db: Session, tables: list[str]) -> list[str]:
    """Children before parents, so the 35 FK-constrained tables do not fail.

    Depth = how many hops a table sits above another in the FK graph. Deleting
    deepest-first means a row's dependents are always gone before it is.

    Tables with no FK at all get depth 0, so they sort alongside root parents.
    Their position is arbitrary and that is correct: nothing references them,
    so a late delete breaks nothing, and they reference nothing, so an early
    one breaks nothing either. They are also the 59 a cascade would never have
    reached, which is why they must be deleted explicitly at all.
    """
    edges = db.execute(text("""
        SELECT tc.table_name AS child, ccu.table_name AS parent
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
         AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
    """)).fetchall()

    parents: dict[str, set[str]] = {}
    for child, parent in edges:
        if child != parent:                 # self-reference is not a hierarchy
            parents.setdefault(child, set()).add(parent)

    def depth(tbl: str, seen: frozenset[str] = frozenset()) -> int:
        # `seen` breaks FK cycles, which exist and would otherwise recurse
        # forever on a schema nobody expected to be cyclic.
        if tbl in seen:
            return 0
        ups = parents.get(tbl, set())
        return 1 + max((depth(p, seen | {tbl}) for p in ups), default=-1)

    return sorted(tables, key=lambda t: -depth(t))


def purge_company(db: Session, company_id: UUID, company_name: str) -> PurgeReport:
    """Delete every row for one tenant. Caller owns the transaction.

    Counts before deleting so the report reflects what was actually there, and
    runs inside the caller's transaction so a failure part-way leaves the
    tenant intact rather than half-removed.
    """
    report = PurgeReport(company_id=str(company_id), company_name=company_name)
    tables = _tenant_tables(db)

    for table in _delete_order(db, tables):
        # Table names come from information_schema, never from user input, so
        # they cannot be attacker-controlled. The VALUE is still bound.
        count = db.execute(
            text(f'SELECT count(*) FROM "{table}" WHERE company_id = :cid'),
            {"cid": str(company_id)},
        ).scalar() or 0
        if count:
            db.execute(
                text(f'DELETE FROM "{table}" WHERE company_id = :cid'),
                {"cid": str(company_id)},
            )
            report.rows_by_table[table] = count

    # The company row itself, last: everything referencing it is now gone.
    deleted = db.execute(
        text(f'DELETE FROM "{_PARENT}" WHERE id = :cid'),
        {"cid": str(company_id)},
    ).rowcount or 0
    report.rows_by_table[_PARENT] = deleted

    return report


def purge_cognito(db: Session, company_id: UUID, report: PurgeReport) -> None:
    """Delete the tenant's Cognito users and app client (ADR-450 D3).

    MUST RUN BEFORE the database purge: it reads employees to learn which
    Cognito usernames exist, and after the purge those rows are gone. Getting
    this order wrong leaves users who can still authenticate against a tenant
    that no longer exists.

    Every failure is collected rather than raised. A half-purged tenant must be
    visible to the operator, because the remedy is manual -- and a Cognito
    error must not roll back a database purge that is otherwise correct.
    """
    from app.models.company import Company
    from app.models.employee import Employee
    from app.routers.employees import cognito_username_for

    try:
        client = boto3.client("cognito-idp", region_name=settings.aws_region)
    except (BotoCoreError, ClientError) as exc:
        report.cognito_errors.append(f"could not create a Cognito client: {type(exc).__name__}")
        return

    pool = settings.aws_cognito_user_pool_id

    for employee in db.query(Employee).filter(Employee.company_id == company_id).all():
        # `username or email` -- which identifier is correct depends on how far
        # through onboarding they got (ADR-380 F7). Guessing the email deletes
        # nothing for anyone who completed registration.
        username = cognito_username_for(employee)
        if not username:
            continue
        try:
            client.admin_delete_user(UserPoolId=pool, Username=username)
            report.cognito_users_deleted += 1
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "UserNotFoundException":
                continue        # already gone; the desired end state holds
            # No email or name in the message (Dimension 7) -- the employee id
            # is enough for an operator to find the row.
            report.cognito_errors.append(f"user {employee.id}: {code}")

    company = db.query(Company).filter(Company.id == company_id).first()
    client_id = getattr(company, "machine_client_id", None) if company else None
    if not client_id:
        return

    try:
        client.delete_user_pool_client(UserPoolId=pool, ClientId=client_id)
        report.cognito_client_deleted = True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            report.cognito_client_deleted = True    # already absent
        else:
            report.cognito_errors.append(f"app client: {code}")
