"""ADR-354 — the rebalance intervention notification must be tenant-scoped.

Found by simulating dispatch against staging-sized data (12 drivers, 10 captains,
83 walkers, 8 trucks). With every walker banning the same two drivers, the
rebalancer cannot close the crew spread and notifies dispatch — and that path
carried two defects:

  1. `Notification(...)` omitted `company_id`, which is NOT NULL. The insert
     aborted the whole dispatch transaction with a NotNullViolation, so a
     ban-saturated day did not merely rebalance poorly — dispatch FAILED.
  2. The Employee query had no company filter, so it would have notified every
     tenant's dispatchers about one company's trucks (Dimension 1).

Neither was reachable in ordinary test data: it takes enough bans to make the
rebalancer give up.
"""
import ast
import inspect

from app.services import rebalance_crews as RC


def _notify_src() -> str:
    return ast.unparse(ast.parse(inspect.getsource(RC._notify_dispatch)))


def test_the_notification_sets_company_id():
    """NOT NULL — omitting it aborts the dispatch transaction, not just the notify."""
    src = _notify_src()
    assert "company_id=company_id" in src, (
        "Notification(...) must set company_id; it is NOT NULL, so an omission "
        "rolls back the entire dispatch run"
    )


def test_the_dispatch_lookup_is_company_scoped():
    """Dimension 1 — an unscoped query notifies another tenant's dispatchers."""
    src = _notify_src()
    assert "Employee.company_id == company_id" in src, (
        "the dispatch/management/admin lookup must filter by company_id"
    )


def test_it_skips_rather_than_guessing_when_the_tenant_is_unknown():
    """No tenant means nobody correct to notify.

    Inserting anyway re-creates defect 1; querying unscoped re-creates defect 2.
    Returning early is the only safe branch.
    """
    src = _notify_src()
    assert "if company_id is None" in src, "there must be an explicit unknown-tenant branch"
    head = src.split("dispatch_employees")[0]
    assert "return" in head, (
        "the unknown-tenant branch must return BEFORE the query and the insert"
    )


def test_company_id_is_threaded_from_the_caller():
    """Deriving it from the truck is the fallback, not the primary source."""
    assert "company_id" in inspect.signature(RC.rebalance_crews).parameters, (
        "rebalance_crews must accept company_id so run_dispatch can pass the "
        "tenant it already knows"
    )
    assert "company_id" in inspect.signature(RC._notify_dispatch).parameters
