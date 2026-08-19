"""A hub crew gets a dock zone (ADR-274 D16).

THE GAP
-------
ADR-180 auto-seeds `DockAssignment` from the sort proposal inside
`persist_zones`, so a driver's home card shows where to collect their truck.

A hub is excluded from `run_sort` by design (D2), so that path can never reach
it — and on a hub-only day `persist_zones` does not run at all. A hub driver's
card therefore read "not assigned yet" permanently.

The parity report called this "manual — dispatch can place them by hand". That
was wrong: `POST /field-ops/dock-assignment` exists but **no frontend or mobile
screen calls it** (both surfaces only GET). That is precisely the orphaned-feature
state ADR-180 was written to end, so the hub had inherited the original bug.

THE FIX
-------
`publish_hub` is the hub's analogue of sort persistence: the crew is known there
(a publish 422s without it) and the day becomes real. Same upsert shape as
persist_zones, keyed on (driver, date) for the unique constraint.
"""
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]
DISPATCH = BACKEND / "app" / "routers" / "dispatch.py"
PERSIST = BACKEND / "app" / "services" / "persist_zones.py"
MODEL = BACKEND / "app" / "models" / "dock_assignment.py"
FRONTEND = BACKEND.parent / "frontend" / "src"
MOBILE = BACKEND.parent / "mobile" / "src"


def _publish_hub() -> str:
    text = DISPATCH.read_text(encoding="utf-8")
    start = text.index("async def publish_hub(")
    end = text.index("\n@router.", start)
    body = text[start:end]
    out = []
    for raw in body.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return "\n".join(out)


@pytest.fixture(scope="module")
def src() -> str:
    return _publish_hub()


class TestStrippingWorks:
    def test_comments_gone_code_kept(self, src: str):
        assert "async def publish_hub(" in src
        assert "ADR-274 D16" not in src, (
            "comments survived stripping — assertions could match prose"
        )


class TestHubDockIsSeeded:
    def test_publish_writes_a_dock_assignment(self, src: str):
        assert "DockAssignment(" in src, (
            "a hub crew still gets no dock zone, so the driver's home card "
            "reads 'not assigned yet' with no UI able to fix it"
        )

    def test_only_drivers_get_one(self, src: str):
        # One row per DRIVER per date (the model's unique constraint is on
        # driver_id+date). Seeding walkers would be wrong data, not just noise.
        assert 'if am.role != "driver":' in src, (
            "every crew member would get a dock row, not just the driver"
        )

    def test_it_upserts_rather_than_inserting_blindly(self, src: str):
        # uq_dock_assignments_driver_date — a re-publish must refresh, not raise.
        assert "if existing_dock:" in src, (
            "a second publish would violate the (driver_id, date) unique "
            "constraint instead of refreshing the row"
        )

    def test_lookup_is_company_and_date_scoped(self, src: str):
        assert "DockAssignment.company_id == caller.company_id" in src
        assert "DockAssignment.driver_id == emp.id" in src
        assert "DockAssignment.date == target_date" in src, (
            "an unscoped lookup would refresh another day's dock row"
        )

    def test_label_fits_the_column(self, src: str):
        # dock_zone is String(50); a long truck name would raise on insert.
        assert '(truck.name or "Hub")[:50]' in src, (
            "dock label is not truncated to the column width"
        )

    def test_actor_name_fits_the_column(self, src: str):
        # assigned_by_name is String(100) while Employee.name is String(255).
        assert '(caller.name or "")[:100]' in src, (
            "assigned_by_name is not truncated — a long name raises on insert"
        )


class TestColumnWidthsHaveNotMoved:
    """The truncation constants above are only right for these widths."""

    def test_dock_zone_is_still_50(self):
        assert 'dock_zone   = Column(String(50)' in MODEL.read_text(encoding="utf-8")

    def test_assigned_by_name_is_still_100(self):
        assert "assigned_by_name = Column(String(100)" in MODEL.read_text(encoding="utf-8")


class TestTheGapWasReal:
    """Pins why this needed fixing, so the reasoning is not re-litigated."""

    def test_persist_zones_cannot_reach_a_hub(self):
        # It seeds from the sort proposal, and run_sort excludes hubs (D2).
        run_sort = (BACKEND / "app" / "services" / "run_sort.py").read_text(encoding="utf-8")
        assert "Truck.is_hub.is_(False)" in run_sort, (
            "run_sort no longer excludes hubs — if a hub now reaches the sort, "
            "persist_zones would seed its dock and this duplicate can go"
        )

    def test_no_ui_writes_a_dock_assignment(self):
        # The "dispatch can do it manually" workaround does not exist: both
        # surfaces only read. If a write UI is ever built, this test should be
        # revisited rather than silently left as a stale claim.
        writers = []
        for root in (FRONTEND, MOBILE):
            if not root.exists():
                continue
            for path in root.rglob("*.ts*"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                for verb in (".post(", ".patch("):
                    for line in text.splitlines():
                        if verb in line and "dock-assignment" in line:
                            writers.append(f"{path.name}: {line.strip()[:70]}")
        assert not writers, (
            "a UI now writes dock assignments — the auto-seed may be redundant "
            f"or need to defer to it: {writers}"
        )
