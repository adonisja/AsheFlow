"""The five defects held through the D2 migration, now fixed (ADR-487).

Each was found during the design review and deliberately NOT fixed at the time,
because each was a registry or helper decision in disguise — fixing one early
means deciding it twice. They ship with the migration that makes the decision.

WHY THESE ARE SOURCE-LEVEL ASSERTIONS
=====================================

Two of the three are about what a code path CANNOT do (reach a NOT NULL with a
null, format a naive datetime for a human), and the third is about ordering. All
three are cheaper and more honest to assert against the source than to reproduce
through a live ADP sync or a sort commit with a dropped-TBA condition.

The risk of a source-level test is that it pins a SPELLING rather than a
property — this project has hit that three times in one session. So each
assertion below states the property and accepts more than one way of writing it
where that is possible.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re

import pytest

from app.services.notification_spec import SPEC, Severity
from app.services.notify import Audience

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


class TestTheTypelessNotification:
    """walker_routes.py:1040 wrote a Notification with no `type=` at all.

    `Notification.type` is NOT NULL with no default, so the rows could never be
    inserted — AND there was no commit after them, so they were discarded when
    the session closed. Neither failure raised anything. The alert that packages
    went missing was itself missing, on a path that fires whenever a sort commit
    drops a TBA.
    """

    def _commit_sort_src(self) -> str:
        from app.routers import walker_routes

        return inspect.getsource(walker_routes.commit_sort)

    def test_the_dropped_tba_branch_raises_a_declared_type(self):
        src = self._commit_sort_src()
        assert "sort_packages_dropped" in src, (
            "the dropped-TBA branch must name a declared type; it previously "
            "constructed a Notification with no type= at all"
        )
        # And the type must actually be in the registry, not just spelled here.
        assert "sort_packages_dropped" in SPEC

    def test_it_goes_through_the_helper_not_a_bare_construction(self):
        src = self._commit_sort_src()
        assert "fan_out(" in src
        # add_all([Notification(...) for ...]) is the shape a CI grep for
        # `db.add(Notification(` cannot see, which is why the helper matters.
        assert "Notification(" not in src

    def test_the_notifications_are_committed(self):
        """The defect that made the other one invisible.

        db.commit() ran ABOVE this branch and the function returned without
        another, so even a valid row evaporated. An un-flushed invalid row
        raises nothing — that combination is why nothing ever noticed.
        """
        src = self._commit_sort_src()
        at_fan_out = src.index("fan_out(")
        after = src[at_fan_out:]
        assert "db.commit()" in after, (
            "there must be a commit AFTER the dropped-TBA fan_out; the only "
            "other commit in commit_sort happens before this branch"
        )

    def test_the_audience_is_named_not_hand_written(self):
        src = self._commit_sort_src()
        assert "Audience.STATION_RESOLVE" in src
        assert '"dispatch", "management", "admin"' not in src

    def test_station_resolve_is_the_right_set_for_this(self):
        """ADR-256 D12 keeps field_supervisor out of station resolution: "they
        oversee the road". A dropped-package investigation is station work."""
        assert set(Audience.STATION_RESOLVE) == {"dispatch", "management", "admin"}
        assert "field_supervisor" not in Audience.STATION_RESOLVE

    def test_the_type_is_declared_as_action(self):
        """Someone must verify the manifest; this is not an announcement."""
        assert SPEC["sort_packages_dropped"].severity is Severity.ACTION


class TestTheMisspelledRole:
    """adp_sync.py filtered on `["admin", "manager"]` — the role is `management`.

    "management" appears 185 times in the backend, "manager" twice, both in
    filters like this. Employee.role is an unconstrained String(50), so nothing
    rejected it: the query matched admins only and every management user was
    silently excluded from offboarding notices.
    """

    def _sync_src(self) -> str:
        from app.tasks import adp_sync

        return inspect.getsource(adp_sync.sync_adp_employees)

    def test_the_offboarding_notice_uses_a_named_audience(self):
        src = self._sync_src()
        assert "Audience.MANAGEMENT" in src

        # Inspect the CODE, not the text. A first version asserted
        # `'"admin", "manager"' not in src` and failed on the COMMENT above the
        # fix, which quotes the old filter to explain it. Fourth prose-not-code
        # false match in this body of work; the fix is always to look at what
        # the parser sees.
        tree = ast.parse(pathlib.Path(
            __import__("app.tasks.adp_sync", fromlist=["x"]).__file__).read_text())
        bad: list[int] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "in_"):
                continue
            for arg in node.args:
                if not isinstance(arg, (ast.List, ast.Tuple)):
                    continue
                vals = {e.value for e in arg.elts if isinstance(e, ast.Constant)}
                if "manager" in vals:
                    bad.append(node.lineno)
        assert not bad, (
            f"role.in_([... 'manager' ...]) at line(s) {bad} — the role is "
            f"'management'; 'manager' matches nobody and fails silently"
        )

    def test_management_is_the_right_set_and_excludes_dispatch(self):
        """An offboarding notice is payroll-adjacent. Widening it to dispatch
        would be a privacy change, not a tidy-up."""
        assert set(Audience.MANAGEMENT) == {"management", "admin"}
        assert "dispatch" not in Audience.MANAGEMENT

    def test_no_audience_can_express_the_typo(self):
        for name in ("OVERSIGHT", "STATION_RESOLVE", "MANAGEMENT", "ADMIN_ONLY"):
            assert "manager" not in getattr(Audience, name), name


class TestTheNaiveClock:
    """The same block rendered `datetime.now()` — the SERVER's clock — into a
    message read by a tenant who may be hours away.

    A Pacific tenant offboarded at 23:30 local was told "Monday Oct 05" for
    something that happened Sunday. `check_no_naive_utc_relabel` passes on it:
    that gate looks for a naive datetime being RELABELLED as UTC, not one being
    formatted for a human.
    """

    def _sync_src(self) -> str:
        from app.tasks import adp_sync

        return inspect.getsource(adp_sync.sync_adp_employees)

    def test_the_offboarding_date_is_company_local(self):
        src = self._sync_src()
        assert "task_today(tz_map.get(" in src, (
            "the offboarding date must resolve in the company's timezone "
            "(ADR-486); task_today(tz) is already used elsewhere in this task"
        )

    def test_no_naive_now_is_formatted_for_a_human(self):
        """Asserted on the AST, not on the text: `datetime.now()` with no
        argument is the naive call, and `datetime.now(timezone.utc)` is not."""
        from app.tasks import adp_sync

        tree = ast.parse(pathlib.Path(adp_sync.__file__).read_text())
        naive: list[int] = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "now"
                    and not node.args and not node.keywords):
                naive.append(node.lineno)
        assert not naive, (
            f"naive datetime.now() at line(s) {naive} in adp_sync — pass a "
            f"timezone, or use task_today(tz) for a company-local date"
        )


class TestTheMigrationCoveredTheseFiles:
    """Both files are fully migrated — no direct construction left anywhere."""

    @pytest.mark.parametrize("rel", [
        "routers/walker_routes.py",
        "tasks/adp_sync.py",
    ])
    def test_no_direct_notification_construction(self, rel):
        src = (APP / rel).read_text()
        tree = ast.parse(src)
        sites = [
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "Notification"
        ]
        assert not sites, f"{rel} still constructs Notification at {sites}"
