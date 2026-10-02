"""Rewriting roster names in campaign free text (ADR-485 D14).

The client warns a respondent before they name a colleague, but that is
advisory — a walker may have a legitimate reason, and a hard refusal on 2000
characters they just typed is how a report gets abandoned instead of rewritten.
So names arrive, and this removes them on a schedule.

    "Maria was late"  ->  "[driver] was late"

SEVEN DAYS AFTER THE RUN CLOSES. Long enough for the follow-up that justified
collecting it — including an attribution request, which has a 48-hour window —
short enough that a named complaint is not sitting in the table a year later.

IRREVERSIBLE, IN PLACE. The original is not kept anywhere, or the retention is
theatre. The structured answers (`bool_value`, `int_value`) are untouched, so
every trend survives the redaction intact: redaction removes WHO, and the
separate retention horizon removes WHAT.

WORD BOUNDARIES ARE NOT OPTIONAL
================================

Matching is case-insensitive, because somebody types "maria". Without `\\b`
that turns an employee named Al into:

    "the van was almost empty"  ->  "the van was [role]most empty"
    "samples were short"        ->  "[role]ples were short"
    "we had to restart"         ->  "we had to rest[role]"

Each of those is a redaction that destroys the sentence while removing no name
at all, and it is irreversible.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.campaign import CampaignAnswer, CampaignResponse, CampaignRun
from app.models.employee import Employee
from app.services.audit import write_audit

logger = logging.getLogger(__name__)

# Long enough for the follow-up that justified collecting the text — an
# attribution grant lasts 48 hours (D13), so a manager who asked on the last
# day still has their window.
REDACT_AFTER = timedelta(days=7)

# A name shorter than this cannot be matched safely. "Al", "Jo" and "Ed" appear
# inside ordinary words often enough that even a word-boundary match hits
# legitimate text ("Ed" as a standalone word is rare; "Al" is not), and the
# cost of a wrong redaction is an irreversibly mangled sentence.
#
# Those employees are matched on their FULL name instead, which is both safer
# and what somebody writing about a colleague actually types.
MIN_NAME_PART = 3


def _name_patterns(employees: list[Employee]) -> list[tuple[re.Pattern, str]]:
    """(pattern, replacement) for every roster name, longest first.

    Longest first so "Maria Santos" is replaced whole rather than leaving
    "[walker] Santos" behind — a partial redaction that still names somebody.
    """
    out: list[tuple[re.Pattern, str, int]] = []
    for emp in employees:
        full = (emp.name or "").strip()
        if not full:
            continue
        role = f"[{emp.role}]" if emp.role else "[colleague]"

        # The full name always, whatever its parts look like.
        out.append((re.compile(rf"\b{re.escape(full)}\b", re.I), role, len(full)))

        # Individual parts only when long enough to be matched safely.
        for part in full.split():
            if len(part) >= MIN_NAME_PART:
                out.append(
                    (re.compile(rf"\b{re.escape(part)}\b", re.I), role, len(part)))

    out.sort(key=lambda t: t[2], reverse=True)
    return [(p, r) for p, r, _ in out]


def redact_names(text: str, patterns: list[tuple[re.Pattern, str]]) -> tuple[str, int]:
    """Rewrite every roster name to its role. Returns (text, replacements)."""
    count = 0
    for pattern, replacement in patterns:
        text, n = pattern.subn(replacement, text)
        count += n
    return text, count


@celery_app.task(name="app.tasks.campaign_redaction.redact_old_free_text")
def redact_old_free_text() -> dict:
    """Redact roster names in free text from runs closed over a week ago.

    Idempotent: `names_redacted_at` is the stamp, so an answer is processed
    once however often this runs.
    """
    db = SessionLocal()
    cutoff = datetime.now(timezone.utc) - REDACT_AFTER
    answers_done = names_removed = 0
    try:
        # Runs whose window ended more than a week ago. A run closed early by
        # hand uses closed_at; otherwise its scheduled close.
        runs = (
            db.query(CampaignRun)
            .filter(
                CampaignRun.closes_at <= cutoff,
            )
            .all()
        )
        runs = [r for r in runs
                if (r.closed_at or r.closes_at) <= cutoff]

        for run in runs:
            try:
                done, removed = _redact_run(db, run)
                answers_done += done
                names_removed += removed
            except Exception:
                # One company's bad data must not stop every other company's
                # text from being redacted.
                db.rollback()
                logger.exception("redaction failed for run %s", run.id)

        return {"answers": answers_done, "names": names_removed}
    finally:
        db.close()


def _redact_run(db, run: CampaignRun) -> tuple[int, int]:
    pending = (
        db.query(CampaignAnswer)
        .join(CampaignResponse, CampaignResponse.id == CampaignAnswer.response_id)
        .filter(
            CampaignResponse.run_id == run.id,
            CampaignResponse.company_id == run.company_id,
            CampaignAnswer.company_id == run.company_id,
            CampaignAnswer.text_value.isnot(None),
            CampaignAnswer.names_redacted_at.is_(None),
        )
        .all()
    )
    if not pending:
        return 0, 0

    roster = (
        db.query(Employee)
        .filter(Employee.company_id == run.company_id)
        .all()
    )
    patterns = _name_patterns(roster)

    now = datetime.now(timezone.utc)
    removed = 0
    for answer in pending:
        redacted, n = redact_names(answer.text_value, patterns)
        if n:
            # In place, irreversible. Keeping the original anywhere — a shadow
            # column, an audit payload — would make this retention theatre.
            answer.text_value = redacted
            removed += n
        # Stamped either way, so an answer with no names is not re-scanned
        # against a roster that grows every week.
        answer.names_redacted_at = now

    db.flush()
    if removed:
        write_audit(
            db=db,
            company_id=str(run.company_id),
            action_type="campaign.free_text_redacted",
            target_table="campaign_runs",
            target_id=str(run.id),
            # Counts only. Putting the redacted names in the audit row would
            # move them from one table to another rather than removing them.
            after={"answers": len(pending), "names_removed": removed},
        )
    db.commit()
    return len(pending), removed
