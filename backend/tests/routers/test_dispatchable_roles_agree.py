"""Every surface that lists dispatchable roles must list the same ones.

THIS BUG HAS NOW HAPPENED TWICE
-------------------------------
ADR-256 added `captain`. It was missing from /schedule/available's pool dict,
and the `if role in pool` guard discarded every captain SILENTLY — no error, no
log. The visible symptom was that removing a captain from a truck deleted them
from the dispatch page, because nothing put them back in the unassigned list.

ADR-264 added `driver_trainee`, and the identical omission appeared in THREE
places: this endpoint, get_available_pool's SQL role filter, and the frontend's
role list. A held-out driver trainee could not be dragged onto a truck — the
drop handler's `emp?.role || 'walker'` fallback would have assigned them as a
walker, and curriculum injection keys on the driver_trainee slot, so nobody
would have been trained.

The failure is silent in every instance, which is why it needs a test rather
than care.
"""
import inspect
import re
from pathlib import Path

from app.routers import schedule
from app.services import available_pool

# Roles that occupy a seat on a truck. NOT the same as Employee.VALID_ROLES:
# dispatch/management/admin are not crew, and field_supervisor oversees the road
# rather than filling a seat (ADR-256).
DISPATCHABLE = {"driver", "captain", "trainer", "walker", "trainee", "driver_trainee"}


def test_schedule_available_lists_every_dispatchable_role():
    src = inspect.getsource(schedule.get_available_employees)
    i = src.index("pool: dict = {")
    block = src[i : src.index("}", i)]
    for role in DISPATCHABLE:
        assert f'"{role}"' in block, (
            f"/schedule/available drops {role!r} silently via `if role in pool`"
        )


def test_the_available_pool_sql_filter_matches():
    src = inspect.getsource(available_pool.get_available_pool)
    i = src.index("Employee.role.in_(")
    block = src[i : i + 320]
    for role in DISPATCHABLE:
        assert f'"{role}"' in block, (
            f"get_available_pool excludes {role!r} from the query, so they never "
            "reach the pool at all"
        )


def test_the_frontend_role_list_matches():
    """types.ts and this list are hand-maintained; there is no codegen."""
    page = (
        Path(__file__).resolve().parents[3]
        / "frontend" / "src" / "pages" / "DispatchDashboard.tsx"
    )
    if not page.exists():          # backend-only checkouts
        return
    text = page.read_text()
    m = re.search(r"\[((?:\s*'[a-z_]+',?)+)\]\.forEach\(role", text)
    assert m, "could not find the dispatchable-role list in DispatchDashboard"
    listed = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert listed == DISPATCHABLE, (
        f"frontend role list disagrees: missing {DISPATCHABLE - listed}, "
        f"extra {listed - DISPATCHABLE}"
    )
