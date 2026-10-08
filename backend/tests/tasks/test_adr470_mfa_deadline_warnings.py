"""A deadline nobody can see is an ambush (ADR-470 D1/D2/D3).

ADR-377 gives field roles 14 days to enrol and ADR-465 makes the wall
unskippable once the window shuts. The countdown rendered ONLY inside the app --
and field staff are not in the app: their work arrives through Discord, no mobile
app has shipped, and the clock only starts when they first open a client.
Measured while writing ADR-470: ZERO of 16 field employees had a started clock.

So the warning existed and was delivered to an empty room, and the first thing a
walker would learn about the deadline was the wall itself, at 05:00, at a depot.

These pin the warning, the dispatch view, and the decision NOT to soften the
wall. Enforcement is unchanged by this ADR and must stay that way.
"""
import inspect
import pathlib

from app.celery_app import celery_app
from app.routers import employees as E
from app.schemas.employee import EmployeeMfaDeadlineResponse
from app.services import mfa_status
from app.tasks import mfa_deadline_warnings as W

ROOT = pathlib.Path(__file__).resolve().parents[3]


# ── D1: the warning ─────────────────────────────────────────────────────────

def test_there_are_two_bands_not_a_daily_nag():
    """A deadline warned about every day is a deadline nobody reads."""
    assert sorted(W.BANDS) == [1, 3]


def test_each_band_has_its_own_notification_type():
    """Shared type = the 1-day warning is swallowed by the 3-day row, because
    the idempotency check would find the earlier one and skip."""
    assert len(set(W.BANDS.values())) == len(W.BANDS)


def test_the_send_is_idempotent_per_band():
    """A re-run the same day must not re-nag. No new column: the Notification
    row IS the record, which is the integration_alerts pattern."""
    src = inspect.getsource(W.warn_before_mfa_deadline)
    assert "Notification.type == notif_type" in src
    assert "skipped_already_warned" in src


def test_idempotency_does_not_depend_on_unread():
    """A warning they READ is still a warning they were sent. Filtering on
    is_read would re-send to everyone who opened the app."""
    src = inspect.getsource(W.warn_before_mfa_deadline)
    block = src.split("already = (", 1)[1].split(")", 1)[0]
    assert "is_read" not in block


def test_the_query_excludes_clocks_that_never_started():
    """As of ADR-470 that is most of the roster. Excluded in SQL by the NOT NULL
    term rather than evaluated and discarded per row."""
    src = inspect.getsource(W.warn_before_mfa_deadline)
    assert "mfa_grace_started_at.isnot(None)" in src


def test_it_does_not_warn_someone_already_past_the_deadline():
    """They are blocked NOW and looking at the wall. "Act before your next
    shift" would be both late and wrong."""
    src = inspect.getsource(W.warn_before_mfa_deadline)
    assert "deadline_at" in src
    assert "mfa_grace_started_at > deadline_at" in src


def test_privileged_roles_are_never_warned():
    """They have no grace at all (ADR-377) -- their path is ADR-465's wall from
    the first sign-in, so a countdown DM would be nonsense."""
    src = inspect.getsource(W.warn_before_mfa_deadline)
    assert 'tier_for(emp.role, {emp.role}) != "field"' in src


def test_an_enrolled_employee_is_not_nagged():
    src = inspect.getsource(W.warn_before_mfa_deadline)
    assert "skipped_enrolled" in src
    assert "enrolled is True" in src


def test_unknown_enrolment_warns_rather_than_stays_silent():
    """DELIBERATELY the opposite of the gating rule. ADR-377 fails OPEN to
    protect access; here the cost of a needless warning is mild annoyance and
    the cost of a missed one is a walker stopped at 05:00."""
    src = inspect.getsource(W.warn_before_mfa_deadline)
    assert "enrolled is True" in src, (
        "treating None as enrolled would silence the warning on a Cognito hiccup"
    )


def test_the_notification_is_written_even_if_discord_is_down():
    """The row is the durable record; the DM is the delivery. Writing it only on
    a successful send makes a bot outage look like a warning that never
    happened -- and makes the retry re-nag."""
    src = inspect.getsource(W.warn_before_mfa_deadline)
    # The WRITE, however it is spelled. This asserted `db.add(Notification(`
    # until ADR-487 D2 routed the write through services.notify — the ordering
    # property never changed, only the call. An anchor on the spelling makes a
    # refactor look like a regression.
    write = next(
        src.index(tok) for tok in ("write_notification(", "db.add(Notification(")
        if tok in src
    )
    dm = src.index("_send_dm(emp.discord_id")
    assert write < dm, "the notification must be recorded before the DM is tried"


def test_the_dm_is_synchronous_unlike_the_router_helper():
    """A request handler threads-and-forgets because a user is waiting. A task
    has the opposite need: it must know what was delivered."""
    src = inspect.getsource(W._send_dm)
    assert "threading" not in src
    assert "return True" in src and "return False" in src


def test_a_dm_failure_does_not_end_the_sweep():
    src = inspect.getsource(W._send_dm)
    assert "except Exception" in src
    assert "raise" not in src.split("except Exception", 1)[1]


def test_the_dm_failure_log_carries_no_identifiers():
    """Dimension 6/7: the exception body can echo back what was sent."""
    # Take the whole logging STATEMENT, not up to the first ")" -- that splits
    # inside `type(exc)` and made the first version of this test fail against
    # correct code.
    src = inspect.getsource(W._send_dm)
    log = src.split("logger.warning", 1)[1].split("\n", 1)[0]
    assert "type(exc).__name__" in log, f"log line was: {log!r}"
    # `exc)` was a bad probe -- it matches inside the SAFE `type(exc).__name__`.
    # The unsafe forms are the exception rendered as a value, or the payload.
    for leaked in ("discord_id", "resp.text", "%s\", exc", "{exc}", "str(exc)"):
        assert leaked not in log, f"the log line carries {leaked}: {log!r}"


def test_it_still_lands_in_the_afternoon_in_the_tenants_own_zone():
    """The PROPERTY survives; its MECHANISM moved (ADR-488).

    ADR-470's rule is unchanged and still right: not an 04:00 slot with the
    other sweeps, because a warning that lands at 04:00 is read at the depot --
    the exact moment it is too late to install an app.

    What was wrong was the ZONE, not the hour. The beat entry fired at 16:30
    SERVER time, so a Los Angeles employee got their warning at 13:30 local and
    an employee further west got it earlier still. It is now the
    `mfa_deadline_warning` platform notice with anchor FIXED_LOCAL at 16:30,
    resolved per tenant.

    So this asserts the seed rather than the beat entry. A test pinning
    `beat_schedule["warn-before-mfa-deadline"]` would now fail on a change that
    PRESERVED everything it was protecting -- which is the mechanism-vs-property
    trap, met for the third time in this body of work.
    """
    from datetime import time

    from app.models.notice import Anchor
    from app.services.notice_seeds import PLATFORM_NOTICES

    seed = next(s for s in PLATFORM_NOTICES if s.seed_key == "mfa_deadline_warning")
    assert seed.anchor == Anchor.FIXED_LOCAL, (
        "the warning must fire on a wall-clock hour, not relative to a shift: "
        "the deadline is days away, so the hour is what matters"
    )
    assert seed.at_local == time(16, 30), "ADR-470's afternoon hour changed"


def test_the_server_hour_entry_is_gone():
    """The half ADR-488 removed. A scheduled caller would reintroduce the bug:
    one server hour for every timezone."""
    assert "warn-before-mfa-deadline" not in celery_app.conf.beat_schedule, (
        "the fixed-server-hour entry is back; retime the notice row instead"
    )


# ── D2: the dispatch view ───────────────────────────────────────────────────

def test_the_deadline_view_is_company_scoped():
    """Dimension 1."""
    src = inspect.getsource(E.get_mfa_deadline)
    assert "Employee.company_id == caller.company_id" in src


def test_dispatch_can_open_it():
    """ADR-458 D2's reasoning: dispatch is who is on shift at 04:00 when
    somebody cannot start, and a list they cannot open is useless then."""
    src = inspect.getsource(E.get_mfa_deadline)
    assert 'RoleChecker(["dispatch", "management", "admin"])' in src


def test_it_makes_no_cognito_call():
    """THE reason the gate can be broader than ADR-467's. days_remaining comes
    entirely from a DB column."""
    src = inspect.getsource(E.get_mfa_deadline)
    for call in ("admin_get_user", "is_enrolled", "boto3"):
        assert call not in src, f"{call} would drag Cognito cost onto this query"


def test_it_lists_only_field_staff():
    src = inspect.getsource(E.get_mfa_deadline)
    assert 'tier_for(emp.role, {emp.role}) != "field"' in src


def test_it_excludes_people_already_blocked():
    src = inspect.getsource(E.get_mfa_deadline)
    assert "mfa_grace_started_at > deadline_at" in src


def test_it_is_sorted_soonest_first():
    """A worklist: the person with one day left is the one to call."""
    src = inspect.getsource(E.get_mfa_deadline)
    assert "out.sort(key=lambda r: (r.days_remaining" in src


def test_the_response_carries_no_enrolment_state():
    """An enrolled employee is never in this list, so the field would be a
    constant -- and it is the one piece that is admin-only (ADR-467)."""
    assert "enrolled" not in EmployeeMfaDeadlineResponse.model_fields
    assert "days_remaining" in EmployeeMfaDeadlineResponse.model_fields


def test_the_literal_route_precedes_the_id_route():
    from app.main import app
    paths = [p for p in app.openapi()["paths"] if "/employees" in p]
    d = next(i for i, p in enumerate(paths) if "mfa-deadline" in p)
    e = next(i for i, p in enumerate(paths) if p.endswith("/employees/{employee_id}"))
    assert d < e, "/{employee_id} would swallow this and 422 on the UUID parse"


def test_mfa_status_resolves_at_request_time():
    """D3's AttributeError shape: `import app.main` passes and the endpoint 500s
    on every call."""
    assert hasattr(E, "mfa_status")
    assert hasattr(E.mfa_status, "DEFAULT_MFA_GRACE_DAYS")
    assert hasattr(E.mfa_status, "tier_for")


# ── D3: enforcement is unchanged ────────────────────────────────────────────

def test_the_window_is_still_fourteen_days():
    """ADR-470 D3: the window does not grow. 14 already matches Microsoft's
    security default and survives a part-time roster."""
    assert mfa_status.DEFAULT_MFA_GRACE_DAYS == 14


def test_field_staff_are_still_blocked_once_the_window_shuts():
    """This ADR warns; it does not forgive. A walker who ignores both DMs still
    meets the wall."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    s = mfa_status.evaluate(
        role="walker", enrolled=False,
        grace_started_at=now - timedelta(days=15), groups={"walker"},
    )
    assert s.blocked is True


def test_the_wall_is_not_skippable():
    """ADR-465 replaced a dismissable nudge for exactly this reason."""
    wall = (ROOT / "frontend/src/pages/MfaRequired.tsx").read_text()
    assert "Signing out will not skip this step" in wall
    for escape in ("Skip", "Remind me later", "Dismiss", "Not now"):
        assert escape not in wall, f"the wall grew an escape hatch: {escape}"


# ── the client surface (ADR-381: an endpoint with no caller is not shipped) ──

ASSETS = ROOT / "frontend/src/pages/Assets.tsx"
TYPES = ROOT / "frontend/src/api/types.ts"


def test_the_endpoint_has_a_caller():
    """ADR-381's failure, three times in one week: a live endpoint, a clean
    build, and nothing calling it."""
    src = ASSETS.read_text()
    assert "'/employees/mfa-deadline'" in src, (
        "the deadline endpoint has no client caller"
    )


def test_the_strip_renders_the_fetched_rows():
    """A fetch that sets state nothing reads is the same failure one layer in."""
    src = ASSETS.read_text()
    assert "deadlines.map(" in src


def test_it_loads_without_being_asked():
    """The enrolment panel waits to be opened because it costs a Cognito call
    per row. This one is free, and answers a question nobody thinks to ask --
    which is exactly the problem it exists for. Behind a button it would be the
    in-app countdown again: present, and unread."""
    src = ASSETS.read_text()
    block = src.split("'/employees/mfa-deadline'", 1)[0]
    assert "useEffect" in block.rsplit("const [deadlines", 1)[-1]


def test_the_strip_is_hidden_when_nobody_is_near_the_deadline():
    """A permanent "0 people" row is noise on a page used daily."""
    src = ASSETS.read_text()
    assert "deadlines && deadlines.length > 0 &&" in src


def test_zero_days_reads_as_today_not_as_expired():
    """A bare "0 days left" reads as already-gone, which would send dispatch
    chasing someone who still has hours."""
    src = ASSETS.read_text()
    assert "d.days_remaining === 0" in src
    assert "'Today'" in src


def test_a_failed_fetch_does_not_error_the_roster():
    """Supplementary warning strip: the roster loaded fine, and an error banner
    would say otherwise."""
    src = ASSETS.read_text()
    block = src.split("'/employees/mfa-deadline'", 1)[1].split("}, []);", 1)[0]
    assert ".catch(" in block
    assert "setDeadlines(null)" in block


def test_the_ts_type_mirrors_the_backend_schema():
    """types.ts is hand-maintained -- there is no codegen."""
    ts = TYPES.read_text()
    assert "export interface MfaDeadlineRow" in ts
    block = ts.split("export interface MfaDeadlineRow", 1)[1].split("}", 1)[0]
    for field in EmployeeMfaDeadlineResponse.model_fields:
        assert field in block, f"{field} missing from MfaDeadlineRow"


def test_the_two_panels_stay_separate_in_the_client_too():
    """Different gate, different cost, different question. Merging them in the
    UI would imply one fetch and re-create the coupling the schemas avoid."""
    ts = TYPES.read_text()
    assert "export interface MfaEnrolmentRow" in ts
    assert "export interface MfaDeadlineRow" in ts
