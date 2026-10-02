"""A stored Time is LOCAL; attaching UTC relabels it (ADR-485 D18).

CompanyConfig stores shift_start and friends as naive Time columns, each
documented as "read in the company's own timezone". Four sites attached UTC to
one instead of converting it, and a fifth called .astimezone() on a naive value,
which uses the SERVER's zone.

The driver-survey one is the loudest: a 3-hour gate meant to hold a survey until
10:00 local fired at 06:00. The same arithmetic under ADR-485 D4 would classify
a 30-minute administrative reshuffle as "worked under that driver" -- the
inverse of the decision.
"""
import pathlib
import re
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.local_date import company_datetime, company_midnight

ROOT = pathlib.Path(__file__).resolve().parents[3]
NY = ZoneInfo("America/New_York")


# ── the helper ──────────────────────────────────────────────────────────────

def test_it_converts_rather_than_relabels():
    """THE bug. 07:00 New York is 11:00 UTC in summer, not 07:00 UTC."""
    got = company_datetime(NY, date(2026, 9, 30), time(7, 0))
    assert got == datetime(2026, 9, 30, 11, 0, tzinfo=timezone.utc)
    wrong = datetime.combine(date(2026, 9, 30), time(7, 0)).replace(tzinfo=timezone.utc)
    assert got - wrong == timedelta(hours=4)


def test_it_follows_dst():
    """A fixed offset would be right for half the year. EDT is UTC-4, EST -5."""
    summer = company_datetime(NY, date(2026, 9, 30), time(7, 0))
    winter = company_datetime(NY, date(2026, 1, 15), time(7, 0))
    assert summer.hour == 11 and winter.hour == 12


def test_midnight_is_local_midnight():
    """ADR-129 defined survey expiry as 'midnight UTC', which closes a New York
    survey at 8pm local while the mobile banner counts down to midnight."""
    assert company_midnight(NY, date(2026, 9, 30)) == \
        datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc)


def test_utc_company_is_unchanged():
    """A tenant in UTC must see no behaviour change from this fix."""
    utc = ZoneInfo("UTC")
    assert company_datetime(utc, date(2026, 9, 30), time(7, 0)) == \
        datetime(2026, 9, 30, 7, 0, tzinfo=timezone.utc)


# ── the five converted sites ────────────────────────────────────────────────

# driver_surveys.py was one of these until ADR-485 D17 migrated the driver
# survey into campaigns and deleted the router. Its 3-hour send gate -- the
# loudest instance of the bug this ADR fixed -- now lives in
# campaign_runs._close_at and campaign_scope._transfer_cutoff, both of which
# use the helper and are covered by their own tests.
SITES = {
    "backend/app/routers/analytics.py":      "company_midnight(tz, range_start)",
    "backend/app/routers/walker_routes.py":  "company_midnight(",
    "backend/app/tasks/campaign_runs.py":    "company_datetime(tz,",
}


def test_each_site_uses_the_helper():
    for rel, needle in SITES.items():
        src = (ROOT / rel).read_text()
        assert needle in src, f"{rel} no longer uses the helper"


def test_dispatch_converts_both_of_its_sites():
    src = (ROOT / "backend/app/routers/dispatch.py").read_text()
    assert "company_midnight(_tz, dispatch_date)" in src
    assert "company_datetime(_tz, dispatch_date, cutoff_time)" in src


def test_every_helper_used_is_imported():
    """A missing import is a NameError at REQUEST time -- `import app.main`
    passes and the endpoint 500s on every call (ADR-115 D3)."""
    for rel in list(SITES) + ["backend/app/routers/dispatch.py",
                              "backend/app/services/campaign_scope.py"]:
        src = (ROOT / rel).read_text()
        used = {h for h in ("company_datetime", "company_midnight", "company_tz")
                if re.search(rf"\b{h}\(", src)}
        imported = {x.strip()
                    for grp in re.findall(r"from app\.services\.local_date import ([a-z_, ]+)", src)
                    for x in grp.split(",")}
        assert used <= imported, f"{rel} uses {sorted(used - imported)} without importing"


# ── the gate ────────────────────────────────────────────────────────────────

def test_the_gate_passes_on_the_current_tree():
    r = subprocess.run(["python3", str(ROOT / "scripts/check_no_naive_utc_relabel.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_the_gate_exempts_the_module_that_defines_the_fix():
    """local_date.py shows both WRONG forms in its docstring. A gate that trips
    on its own rationale gets deleted."""
    src = (ROOT / "scripts/check_no_naive_utc_relabel.py").read_text()
    assert "services/local_date.py" in src


def test_the_gate_still_allows_utc_on_a_genuine_utc_value():
    """`.replace(tzinfo=utc)` on a naive timestamp read back from the DB is
    correct and common -- flagging it would make the gate unusable."""
    src = (ROOT / "scripts/check_no_naive_utc_relabel.py").read_text()
    assert "combine" in src, "the pattern must be anchored to combine(), not to replace()"
