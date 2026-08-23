"""ADR-284 — a hub crew is walkers.

THE FAILURE THIS GUARDS AGAINST
-------------------------------
`AssignmentMember.role` is the SLOT (the job for the day), deliberately distinct
from `Employee.role` (the job title). The dispatch UI sends the job title on
every drop, and the assign endpoint used to persist it verbatim without ever
reading `is_hub`.

A hub runs no route, so a captain there leads nothing and a trainer supervises
nobody — they work it as ordinary labour. But 15+ queries read the slot as
truth: `driver_surveys` filters `role.in_(["trainer","walker"])` with no is_hub
branch, and ADR-256's one-captain-per-truck index makes a hub consume a captain
seat.

The invariant was already enforced in every AUTOMATIC path (assign_captains,
run_dispatch, run_sort all exclude hubs) and nowhere a human dragged.

dispatch.py is proprietary; CI copies it in from AsheFlow-private before pytest,
so there is deliberately NO skip guard.
"""
import inspect

from app.routers import dispatch
from app.services.constants import (
    ROLE_CAPTAIN, ROLE_DRIVER, ROLE_TRAINEE, ROLE_TRAINER, ROLE_WALKER,
)


def _code_only(obj) -> str:
    """Source with comments and docstring stripped.

    This code documents the rule it enforces, and the comments name the very
    roles the assertions look for — a bare `in` check would pass on the
    explanation alone."""
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


SRC = _code_only(dispatch.manual_assignment)


class TestCoercionOnHubs:
    def test_captain_and_trainer_become_walker(self):
        """D1. Neither slot denotes anything on a hub."""
        assert "if requested_role in (ROLE_CAPTAIN, ROLE_TRAINER):" in SRC
        assert "effective_role = ROLE_WALKER" in SRC

    def test_it_is_gated_on_the_truck_being_a_hub(self):
        """Coercing on a delivery truck would strip real captains."""
        assert "if truck.is_hub:" in SRC

    def test_driver_is_preserved(self):
        """ADR-274 D10: 'a hub has no captain, so the driver leads'. Coercing
        driver would strip the hub's route lead — the gate ROUTE_LEAD_ROLES
        grants it through `driver`."""
        i = SRC.index("if requested_role in (ROLE_CAPTAIN, ROLE_TRAINER):")
        window = SRC[i : i + 200]
        assert "ROLE_DRIVER" not in window

    def test_the_key_is_the_requested_slot_not_the_job_title(self):
        """A captain-TITLED employee slotted as a driver must stay a driver.
        Keying on Employee.role would demote them."""
        assert "requested_role = assignment_in.role" in SRC
        assert "employee.role" not in SRC


class TestTraineesAreRefused:
    def test_a_trainee_on_a_hub_is_a_409(self):
        """D2. Coercion is right for a captain (they still do real hub work
        under another name) and wrong for a trainee: a silent relabel produces
        a day that looks like work while phase progression does not advance."""
        assert "if requested_role == ROLE_TRAINEE:" in SRC
        i = SRC.index("if requested_role == ROLE_TRAINEE:")
        window = SRC[i : i + 500]
        assert "HTTP_409_CONFLICT" in window

    def test_the_refusal_says_what_to_do_instead(self):
        i = SRC.index("if requested_role == ROLE_TRAINEE:")
        window = SRC[i : i + 600]
        assert "Assign them to a delivery truck." in window

    def test_the_trainee_check_precedes_the_coercion(self):
        """If coercion ran first the trainee slot would survive as `trainee`
        (it is not in the coerced set) and the guard would still fire — but the
        order is load-bearing if the coerced set ever grows."""
        assert SRC.index("if requested_role == ROLE_TRAINEE:") < SRC.index(
            "if requested_role in (ROLE_CAPTAIN, ROLE_TRAINER):"
        )


class TestTheCoercionReachesEverything:
    """A partially-converted change fails only on the path nobody tested.
    Seven sites downstream consumed the requested role."""

    def test_the_persisted_row_uses_the_effective_slot(self):
        assert "role=effective_role," in SRC

    def test_the_seat_conflict_checks_use_the_effective_slot(self):
        """ADR-256's captain checks must NOT fire on a hub — the effective slot
        there is walker, so there is no captain seat to contend for."""
        assert "if effective_role == ROLE_CAPTAIN:" in SRC
        assert "if effective_role in (ROLE_CAPTAIN, ROLE_DRIVER):" in SRC

    def test_no_downstream_site_still_reads_the_requested_role(self):
        """The capture itself is the only legitimate use."""
        uses = [ln for ln in SRC.splitlines() if "assignment_in.role" in ln]
        assert len(uses) == 1, f"unconverted uses remain: {uses}"
        assert "requested_role = assignment_in.role" in uses[0]

    def test_the_notification_describes_the_job_they_will_work(self):
        """Telling someone they are the captain of a hub is telling them to do
        something the hub has no work for."""
        assert "role = effective_role" in SRC


class TestItIsTraceable:
    def test_the_audit_records_both_roles(self):
        """Recording only the effective slot makes a coercion look like the
        dispatcher asked for a walker."""
        assert '"role": effective_role' in SRC
        assert '"requested_role": requested_role' in SRC
        assert '"coerced": effective_role != requested_role' in SRC

    def test_the_response_tells_the_client_what_happened(self):
        """D3 — the card shows 'Captain Test — WALKER'. Without these the UI
        would have to re-derive the rule to know a coercion occurred."""
        assert '"requested_role": requested_role,' in SRC
        assert '"coerced": new_member.role != requested_role,' in SRC


class TestTenancy:
    def test_the_hub_check_uses_the_already_scoped_truck(self):
        """ADR-115 dim 1. The truck is fetched with company_id above; reading
        is_hub off it adds no unscoped query."""
        assert SRC.index("Truck.company_id == caller.company_id") < SRC.index(
            "if truck.is_hub:"
        )
