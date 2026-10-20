"""ADR-285 — the onboarding window: a company's first import may set real roles.

THE PROBLEM
-----------
`walker`, `trainer`, `driver` and `captain` are EARNED roles: refused at hire so
a new hire cannot skip the training program that qualifies them. That is correct
for hiring, and wrong for MIGRATION.

A DSP signing up with 40 existing staff has drivers who have driven for years
and captains who have run trucks for longer. Under the hiring rule they would
each enter as a trainee and re-earn a role they already hold — and `trainee ->
walker` is not even a promotion: it happens only by passing the graduation quiz
(`graduate_trainees.py`), so twenty experienced walkers would sit through a
five-phase program before they could work.

That is not friction; it makes the product unusable for its actual customer.

THE WINDOW
----------
While a company has **no active field staff**, role restrictions at hire do not
apply: this is a migration, not a hire. Once anyone is working, the rule
resumes.

Tied to a verifiable company STATE rather than a flag, deliberately:

- it cannot be left switched on — importing staff is what closes it;
- it needs no expiry date to reason about, and no cleanup job;
- "did this company have staff yet?" is answerable from the data at any later
  point, which a consumed one-shot token would not be.

The trade is that a company which offboards its entire field staff reopens the
window. That is the honest reading of the state — a company with nobody working
IS in the same position as a new one — and it requires deactivating every field
employee, which is not something that happens by accident.
"""
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.models.employee import Employee

logger = logging.getLogger(__name__)

# ADR-538. The setup window: a new company may add its EXISTING, already-trained
# staff at their real roles. Owner, 2026-10-18: open while 10 or fewer people
# have a sign-in account AND the company is within 30 days of creation.
SETUP_WINDOW_MAX_ACCOUNTS = 10
SETUP_WINDOW_DAYS = 30


def setup_window(db: Session, company_id: UUID) -> dict:
    """The window's state, for the gate and for the People page banner.

    `registered` counts employees with a sign-in account (cognito_sub set), ANY
    status -- deactivated included -- so the count only rises and the window
    never reopens. Not `is_active`: seed scripts write rows active with no
    account (dsp-test: 132 active, 14 accounts), which would close the window
    before a real person had joined.
    """
    from app.models.company import Company  # local: avoid a models import cycle at module load
    registered = (
        db.query(func.count(Employee.id))
        .filter(Employee.company_id == company_id, Employee.cognito_sub.isnot(None))
        .scalar()
    ) or 0
    created = db.query(Company.created_at).filter(Company.id == company_id).scalar()
    now = datetime.now(timezone.utc)
    if created is None:
        # Fail CLOSED: an unknown company is not in a setup window. (The first
        # draft set closes_at = now and then tested now <= closes_at -- true --
        # so a missing company read as OPEN. Caught by the ADR-537 tests.)
        return {"open": False, "registered": registered, "limit": SETUP_WINDOW_MAX_ACCOUNTS,
                "days_left": 0, "closes_at": None}
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    closes_at = created + timedelta(days=SETUP_WINDOW_DAYS)
    remaining = closes_at - now
    days_left = max(0, remaining.days + (1 if remaining.seconds else 0)) if remaining.total_seconds() > 0 else 0
    open_ = registered <= SETUP_WINDOW_MAX_ACCOUNTS and now <= closes_at
    return {"open": open_, "registered": registered, "limit": SETUP_WINDOW_MAX_ACCOUNTS,
            "days_left": days_left if open_ else 0, "closes_at": closes_at}


def is_onboarding(db: Session, company_id: UUID) -> bool:
    """True while the company is in its setup window (ADR-538).

    Was (ADR-285): "no active field staff". That closed the window on the first
    imported worker to sign in -- a second import batch was refused -- and was
    fooled by seeded rows marked active with no account.
    """
    return setup_window(db, company_id)["open"]


def onboarding_note(db: Session, company_id: UUID) -> str | None:
    """A line for the audit detail when the window let a role through.

    Returned rather than logged at the call site so every consumer records the
    same thing: an employee who entered at an earned role needs a trace saying
    why, or a later reader sees a captain who never earned it.
    """
    if not is_onboarding(db, company_id):
        return None
    return (
        "created during the company setup window (10 or fewer sign-ups, first 30 days; "
        "ADR-538); earned-role restrictions did not apply"
    )
