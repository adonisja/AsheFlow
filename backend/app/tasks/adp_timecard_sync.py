import logging
import asyncio
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.services.local_date import task_today, fetch_company_timezones
from app.models.adp_integration import ADPIntegration
from app.models.employee import Employee
from app.models.adp_timecard import ADPTimeCard, ADPTimeCardBreak
from app.services.adp import fetch_adp_team_timecards

logger = logging.getLogger(__name__)


def _team_manager_oids(db, company_id) -> list[str]:
    """ADP associateOIDs to use as the {aoid} on team-time-cards.

    The endpoint is team-scoped: it returns the timecards of everyone reporting
    to the given worker, and ADP requires that worker to be both a manager and a
    supervisor in its own hierarchy.

    AsheFlow's roles are not ADP's. `management`/`admin` here is a best-effort
    proxy for "is a manager in ADP" — the authoritative signal is `reportsTo` on
    GET /hr/v2/workers, which adp_sync does not yet capture. Until it does, a
    company whose ADP supervisors differ from its AsheFlow managers will sync
    incompletely; the per-manager warning in the caller is what surfaces that.

    Deduplicated: two AsheFlow managers can map to one ADP supervisor, and
    fetching the same team twice is wasted cost.
    """
    rows = (
        db.query(Employee.hr_system_id_adp)
        .filter(
            Employee.company_id == company_id,
            Employee.is_active == True,
            Employee.hr_system_id_adp_verified == True,
            Employee.role.in_(["management", "admin"]),
        )
        .all()
    )
    return sorted({str(r[0]) for r in rows if r[0]})


def _as_str(value) -> str | None:
    """Coerce an ADP identifier to a string without inventing one.

    ADP ids are opaque and inconsistently typed across examples (ints, strings,
    pipe-suffixed composites like "8672975228284578|1"). They are stored and sent
    verbatim, never parsed.
    """
    return None if value is None else str(value)


def _code_value(node) -> str | None:
    """Unwrap ADP's codeType_v02 ({"codeValue": ...}) to its value.

    breakTypeCode, breakStatus and overrideTypeCode are objects in ADP's schema,
    not bare strings — reading them directly yields a dict, not 'meal'. Tolerates
    a bare string in case ADP flattens it.
    """
    if node is None:
        return None
    if isinstance(node, dict):
        value = node.get("codeValue")
        return None if value is None else str(value)
    return str(node)


def _parse_adp_datetime(value) -> datetime | None:
    """Parse an ADP timestamp into a tz-aware datetime, or None if unusable.

    breaks[].startTime/endTime are typed timeType_v01 — a bare string — so the
    format is not guaranteed. ADP emits 'Z' for UTC, which fromisoformat rejects
    before Python 3.11, and its own samples contain stray spaces
    ("2024-06-07T09: 00: 00-0700").

    A naive value is assumed UTC: these are compared against Flex timestamps
    stored as tz-aware, and a naive value would raise on comparison.
    """
    if not value:
        return None
    text = str(value).replace(" ", "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        logger.warning("Unparseable ADP timestamp %r — break time dropped", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

@celery_app.task(name="app.tasks.adp_timecard_sync.sync_adp_timecards")
def sync_adp_timecards() -> dict:
    """Fetch and store the previous day's ADP timecards for all verified employees.

    Runs daily at 06:00 AM Eastern. For each company with an enabled ADP
    integration, issues one team-scoped request per manager — ADP's
    team-time-cards endpoint returns every direct report in a single call — then
    indexes the result by associateOID and stores each verified employee's
    entries against their own timecard row.

    Each timecard is upserted: created on first fetch, updated on re-fetch (e.g.
    if the task is re-run after a failure). Breaks are replaced wholesale on each
    sync, so a break deleted in ADP does not survive here and get compared
    against Flex.

    A per-company try/except ensures one company's failure does not block others;
    a per-manager try/except keeps one unreachable team from costing the company
    its whole sync.
    """

    db = SessionLocal()
    try:
        tz_map = fetch_company_timezones(db)

        integrations = db.query(ADPIntegration).filter(
            ADPIntegration.is_enabled == True
        ).all()

        for integration in integrations:
            try:
                work_date = task_today(tz_map.get(integration.company_id)) - timedelta(days=1)
                employees = db.query(Employee).filter(
                    Employee.is_active == True,
                    Employee.hr_system_id_adp_verified == True,
                    Employee.company_id == integration.company_id,
                ).all()

                # One team-scoped request per manager covers every direct report.
                # The endpoint's {aoid} is the manager whose team to return, so
                # fetching per employee would be one call per head — each asking
                # for the team reporting to a walker, which is empty (ADR-233).
                entries_by_oid: dict[str, list[dict]] = {}
                for manager_oid in _team_manager_oids(db, integration.company_id):
                    try:
                        entries_by_oid.update(
                            asyncio.run(fetch_adp_team_timecards(integration, manager_oid, work_date))
                        )
                    except Exception as e:
                        # One manager's failure must not cost the whole company
                        # its sync — their reports simply go unsynced this run.
                        logger.warning(
                            "ADP team timecard fetch failed for manager %s (company %s): %s",
                            manager_oid, integration.company_id, e,
                        )

                for employee in employees:
                    time_entries = entries_by_oid.get(str(employee.hr_system_id_adp), [])

                    existing_timecard = db.query(ADPTimeCard).filter(
                        ADPTimeCard.employee_id == employee.id,
                        ADPTimeCard.work_date == work_date,
                    ).first()

                    is_working_day = bool(time_entries)
                    raw_payload = {"timeEntries": time_entries} if time_entries else None

                    if existing_timecard is None:
                       db.add(ADPTimeCard(
                           company_id = integration.company_id,
                           employee_id = employee.id,
                           adp_associate_oid = employee.hr_system_id_adp,
                           work_date = work_date,
                           is_working_day = is_working_day,
                           raw_payload = raw_payload,
                           fetched_at = datetime.now(timezone.utc)
                        ))
                    else:
                        existing_timecard.is_working_day = is_working_day
                        existing_timecard.raw_payload = raw_payload
                        existing_timecard.fetched_at = datetime.now(timezone.utc)

                    db.commit()

                    timecard_row = existing_timecard or db.query(ADPTimeCard).filter(
                        ADPTimeCard.employee_id == employee.id,
                        ADPTimeCard.work_date == work_date,
                    ).first()

                    # Breaks are replaced wholesale on every sync so the cache
                    # always reflects ADP's current state — a break removed in ADP
                    # must not survive here and be compared against Flex.
                    db.query(ADPTimeCardBreak).filter(
                        ADPTimeCardBreak.company_id == integration.company_id,
                        ADPTimeCardBreak.timecard_id == timecard_row.id,
                    ).delete(synchronize_session=False)
                    db.commit()

                    for entry in time_entries:
                        entry_id = entry.get("entryID")
                        if not entry_id:
                            # Without an entryID a correction cannot be addressed
                            # back to ADP, so the break is not actionable.
                            logger.warning(
                                "ADP timeEntry without entryID for employee %s on %s (company %s) — skipped",
                                employee.id, work_date, integration.company_id,
                            )
                            continue

                        for brk in entry.get("breaks") or []:
                            db.add(ADPTimeCardBreak(
                                company_id = integration.company_id,
                                timecard_id = timecard_row.id,
                                adp_entry_id = str(entry_id),
                                break_item_id = _as_str(brk.get("itemID")),
                                start_at = _parse_adp_datetime(brk.get("startTime")),
                                end_at = _parse_adp_datetime(brk.get("endTime")),
                                break_type_code = _code_value(brk.get("breakTypeCode")),
                                break_status = _code_value(brk.get("breakStatus")),
                                override_type_code = _code_value(brk.get("overrideTypeCode")),
                            ))

                    db.commit()

            except Exception as e:
                logger.warning("ADP timecard sync failed for company %s: %s", integration.company_id, e)
                continue
        
        return {"status": "ok"}
    
    finally:
        db.close()

    