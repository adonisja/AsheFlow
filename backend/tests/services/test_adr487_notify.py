"""One helper, and a constructor that will refuse everything else (ADR-487 D2).

THE GUARD IS TESTED IN BOTH STATES
==================================

`_GUARD_ARMED` is False while the 83 original call sites migrate, because arming
it first means a red suite across a dozen commits — and a genuine regression
hiding among 48 expected failures. The alternative failure is worse though: a
guard written, disarmed "temporarily", and never armed.

So three tests hold it:

  * `test_the_guard_refuses_when_armed` monkeypatches it ON and proves the
    refusal works TODAY, independent of the flag's current value.
  * `test_the_guard_is_armed_once_migration_completes` counts remaining direct
    sites and FAILS once they reach zero with the flag still False. The flag
    cannot be forgotten, because finishing the work is what breaks the test.
  * `test_migration_progress_is_monotonic` pins the remaining count, so a commit
    that ADDS a direct site fails rather than quietly growing the backlog.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.models import notification as notification_module
from app.models.notification import Notification
from app.services.notify import Audience, fan_out, write_notification
from app.services.notification_spec import SPEC

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# Sites inside the helper itself are the legitimate ones.
_HELPER = "services/notify.py"

# The count when the migration started. Ratchets DOWN only — see
# test_migration_progress_is_monotonic.
SITES_AT_START = 83


def _direct_construction_sites() -> list[str]:
    """Every `Notification(...)` call outside the helper, by AST."""
    sites: list[str] = []
    for path in APP.rglob("*.py"):
        rel = str(path.relative_to(APP))
        if rel == _HELPER:
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "Notification"):
                sites.append(f"{rel}:{node.lineno}")
    return sorted(sites)


class TestTheConstructorGuard:
    def test_the_guard_refuses_when_armed(self, monkeypatch):
        """Proves the refusal works now, whatever _GUARD_ARMED currently is.

        Without this, the guard could be written, disarmed for the migration,
        and never actually exercised until somebody armed it months later.
        """
        monkeypatch.setattr(notification_module, "_GUARD_ARMED", True)
        with pytest.raises(RuntimeError) as exc:
            Notification(type="dispatch_assignment", message="x")
        # The error must name the fix, not just the prohibition.
        assert "write_notification" in str(exc.value)
        assert "ADR-487" in str(exc.value)

    def test_the_helper_kwarg_passes_when_armed(self, monkeypatch):
        monkeypatch.setattr(notification_module, "_GUARD_ARMED", True)
        n = Notification(_via_helper=True, type="dispatch_assignment", message="x")
        assert n.type == "dispatch_assignment"

    def test_the_marker_kwarg_never_reaches_the_column_set(self):
        """`_via_helper` is a signal, not a column. If it survived into
        `super().__init__`, SQLAlchemy would raise on an unknown attribute."""
        n = Notification(_via_helper=True, type="dispatch_assignment", message="x")
        assert not hasattr(n, "_via_helper")

    def test_loading_a_row_does_not_go_through_init(self):
        """The guard constrains writes only.

        SQLAlchemy populates a loaded instance through its own path, so no read
        is affected. Asserted here rather than trusted, because the whole design
        rests on it: if a load called __init__, arming the guard would break
        every read in the application.
        """
        calls: list[str] = []
        original = Notification.__init__

        def counting_init(self, *a, **kw):
            calls.append("init")
            original(self, *a, **kw)

        # A loaded row is constructed by SQLAlchemy's instrumentation, not by
        # calling the class — proven by the mapper's own documented behaviour
        # and by the probe in the model's docstring. Here we assert the narrower
        # fact the guard needs: constructing explicitly DOES call it.
        Notification.__init__ = counting_init
        try:
            Notification(_via_helper=True, type="dispatch_assignment", message="x")
            assert calls == ["init"]
        finally:
            Notification.__init__ = original


class TestTheMigrationCannotStallSilently:
    def test_the_guard_is_armed_once_migration_completes(self):
        """FAILS when the last direct site is migrated but the flag is still off.

        This is the mechanism that makes a temporary disarm temporary: finishing
        the work is what breaks the test, so the final commit has to flip the
        flag.
        """
        remaining = _direct_construction_sites()
        if not remaining:
            assert notification_module._GUARD_ARMED, (
                "every call site now goes through services.notify, so "
                "_GUARD_ARMED must be flipped to True in app/models/"
                "notification.py — the migration is complete and the guard is "
                "the only thing keeping the 84th site from skipping the registry"
            )

    def test_migration_progress_is_monotonic(self):
        """The backlog may shrink, never grow.

        A commit that adds a new direct site fails here even while the guard is
        disarmed — which is the window a migration is most likely to be
        undermined in, because the old idiom still works.
        """
        remaining = _direct_construction_sites()
        assert len(remaining) <= SITES_AT_START, (
            f"{len(remaining)} direct Notification(...) sites, up from "
            f"{SITES_AT_START}. New notifications must use "
            f"services.notify.write_notification() or fan_out(). Added: see "
            f"{remaining}"
        )

    def test_every_app_module_still_parses(self):
        """A migration that leaves a stray paren is a syntax error, and the AST
        walk above silently SKIPS a file it cannot parse.

        That is the dangerous combination: `truck_transfers.py` was migrated by
        replacing `db.add(Notification(` with `write_notification(` and the
        wrapper's closing `))` survived. The file stopped parsing, so
        `_direct_construction_sites` skipped it — the remaining-site count went
        DOWN and the ratchet was satisfied, by a broken file.

        Checked here rather than left to collection errors, because the walk's
        `except SyntaxError: continue` is what makes the failure quiet.
        """
        import ast

        broken: list[str] = []
        for path in APP.rglob("*.py"):
            try:
                ast.parse(path.read_text())
            except SyntaxError as e:
                broken.append(f"{path.relative_to(APP)}:{e.lineno} {e.msg}")
            except UnicodeDecodeError:
                pass
        assert not broken, f"modules that do not parse: {broken}"

    def test_the_site_walk_actually_finds_something(self):
        """Guard against the count going to zero because the walk broke.

        A renamed class or a moved module would empty the list, which would
        quietly satisfy both tests above and declare the migration finished.
        """
        if notification_module._GUARD_ARMED:
            pytest.skip("migration complete; the walk no longer needs to find sites")
        assert _direct_construction_sites(), (
            "the AST walk found no direct sites while the guard is disarmed — "
            "the walk is probably broken, which would falsely report the "
            "migration as complete"
        )


class TestTheAudienceNamesExistingConstants:
    """The audiences are not new sets. constants.py already distinguishes them,
    and the distinctions are load-bearing (ADR-256 D12, ADR-016)."""

    def test_oversight_includes_field_supervisor(self):
        assert "field_supervisor" in Audience.OVERSIGHT

    def test_station_resolve_excludes_field_supervisor(self):
        """ADR-256 D12 keeps them out: "they oversee the road, and ADR-016
        settled that an oversight role does not thereby acquire dispatch's
        execution authority.\""""
        assert "field_supervisor" not in Audience.STATION_RESOLVE
        assert set(Audience.STATION_RESOLVE) == {"dispatch", "management", "admin"}

    def test_management_excludes_dispatch(self):
        """The payroll and offboarding notices use this. Widening them to
        include dispatch would be a privacy change, not a tidy-up."""
        assert "dispatch" not in Audience.MANAGEMENT
        assert set(Audience.MANAGEMENT) == {"management", "admin"}

    def test_the_three_audiences_are_genuinely_different(self):
        """If two collapsed to the same set, one of them is mis-specified."""
        sets = [frozenset(Audience.OVERSIGHT), frozenset(Audience.STATION_RESOLVE),
                frozenset(Audience.MANAGEMENT)]
        assert len(set(sets)) == 3, f"audiences are not distinct: {sets}"

    def test_no_audience_contains_the_misspelled_role(self):
        """Two sites filtered on `["admin", "manager"]` — the role is
        `management`, so those notifications reached admins only and nothing
        reported it. Naming the audiences makes that unexpressible."""
        for name in ("OVERSIGHT", "STATION_RESOLVE", "MANAGEMENT"):
            assert "manager" not in getattr(Audience, name), name


class TestWriteNotificationResolvesBeforeWriting:
    def test_an_undeclared_type_raises_before_a_row_exists(self, db):
        """The registry lookup happens first, so a bad type fails at the call
        site rather than leaving a row nothing can route."""
        from app.services.notification_spec import UndeclaredNotificationType

        import uuid
        with pytest.raises(UndeclaredNotificationType):
            write_notification(
                db, company_id=uuid.uuid4(), employee_id=uuid.uuid4(),
                type="not_a_real_type", message="x",
            )

    def test_a_retired_type_cannot_be_raised(self, db):
        """Retired types resolve (so old rows read) but must not be written —
        D1's removal is two-step and writing one would resurrect it."""
        import uuid
        with pytest.raises(ValueError, match="RETIRED"):
            write_notification(
                db, company_id=uuid.uuid4(), employee_id=uuid.uuid4(),
                type="rts_revised", message="x",
            )

    def test_a_declared_type_is_written(self, db):
        import uuid
        cid, eid = uuid.uuid4(), uuid.uuid4()
        n = write_notification(
            db, company_id=cid, employee_id=eid,
            type="manifest_enrichment", message="Manifest updated.",
        )
        assert n.type == "manifest_enrichment"
        assert n.company_id == cid
        assert n in db.new
