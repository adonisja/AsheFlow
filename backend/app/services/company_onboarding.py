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

from app.models.employee import Employee

logger = logging.getLogger(__name__)

# Roles that mean "this company is operating". Deliberately NOT
# constants.FIELD_ROLES: that tuple has no importers and is shadowed by a
# different set in employees.py, so depending on it would tie this rule to a
# constant nobody maintains. Listed here with the reason instead.
#
# `driver_trainee` and `trainee` COUNT. A company that has started training
# someone is operating — its next hire is a hire, not a migration.
OPERATING_ROLES: frozenset[str] = frozenset({
    "driver", "walker", "trainer", "trainee", "captain", "driver_trainee",
    "field_supervisor",
})


def is_onboarding(db: Session, company_id: UUID) -> bool:
    """True when this company has no active field staff yet.

    `is_active` is the test, not row existence: employees are created
    `is_active=False` and pending_verification, so a company mid-import — rows
    written, nobody registered — is still onboarding. Otherwise the first
    imported row would close the window on the second.
    """
    exists = (
        db.query(Employee.id)
        .filter(
            Employee.company_id == company_id,
            Employee.is_active == True,
            Employee.role.in_(tuple(OPERATING_ROLES)),
        )
        .first()
    )
    return exists is None


def onboarding_note(db: Session, company_id: UUID) -> str | None:
    """A line for the audit detail when the window let a role through.

    Returned rather than logged at the call site so every consumer records the
    same thing: an employee who entered at an earned role needs a trace saying
    why, or a later reader sees a captain who never earned it.
    """
    if not is_onboarding(db, company_id):
        return None
    return (
        "created during the company onboarding window (no active field staff); "
        "earned-role restrictions did not apply"
    )
