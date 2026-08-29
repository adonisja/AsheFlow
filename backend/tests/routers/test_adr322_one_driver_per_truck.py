"""One driver per truck; a trainee is not a second one (ADR-322).

ADR-321 noted that `captain` was the only role with a one-per-truck index, so
two drivers on a truck was legal at the database level. The operator ruled it
should not be — a truck has one driver, and a `driver_trainee` riding with a
driver is the expected pairing, not a second driver.

Measured before adding the index: 0 violations across 2,675 truck-days with at
least one driver, all history. A constraint already true everywhere is the
cheapest kind to add.
"""
import ast
import inspect

from app.models.assignment_member import AssignmentMember
from app.routers import dispatch as D
from app.services.constants import ROLE_DRIVER, ROLE_DRIVER_TRAINEE


def _code_only(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ── D1: the index ────────────────────────────────────────────────────────────

def test_one_driver_per_truck_is_enforced_by_a_partial_index():
    idx = {i.name: i for i in AssignmentMember.__table__.indexes}
    assert "uq_assignment_members_one_driver" in idx
    one = idx["uq_assignment_members_one_driver"]
    assert one.unique is True
    assert "driver" in str(one.dialect_options["postgresql"]["where"])


def test_the_index_names_both_dialects():
    """A postgresql_where alone is SILENTLY DROPPED by SQLite, degrading this
    into a plain unique index on assignment_id — one crew member per truck, any
    role. The captain index's own comment records that this is not a test
    artifact: it fails ordinary driver/trainer inserts."""
    one = {i.name: i for i in AssignmentMember.__table__.indexes}["uq_assignment_members_one_driver"]
    assert one.dialect_options["postgresql"]["where"] is not None
    assert one.dialect_options["sqlite"]["where"] is not None


def test_the_predicate_does_not_mention_the_trainee():
    """`driver_trainee` is a DISTINCT role string, so the pairing is legal by
    construction. An exception clause would be redundant AND would risk
    entangling the two roles, which ADR-264 D6 depends on keeping separate."""
    one = {i.name: i for i in AssignmentMember.__table__.indexes}["uq_assignment_members_one_driver"]
    where = str(one.dialect_options["postgresql"]["where"])
    assert "driver_trainee" not in where
    assert where.strip() == "role = 'driver'"


# ── D2: a trainee-only truck WARNS, it does not block ────────────────────────

def test_a_trainee_only_truck_is_detected_separately_from_an_empty_one():
    """"No driver at all" and "trainee only" are different facts with different
    consequences and must not collapse into one branch (supersedes ADR-310 D4)."""
    assert hasattr(D, "_trucks_with_only_a_driver_trainee")
    src = _code_only(D._trucks_with_only_a_driver_trainee)
    assert "ROLE_DRIVER_TRAINEE in" in src
    assert "ROLE_DRIVER not in" in src


def test_publish_warns_about_a_trainee_only_truck_rather_than_refusing():
    src = _code_only(D.publish_dispatch)
    i = src.index("_trucks_with_only_a_driver_trainee")
    block = src[i:i + 700]
    assert "warnings.append" in block
    assert "HTTPException" not in block, (
        "a trainee-only truck must publish with a warning, not 409 (ADR-322 D2)"
    )


def test_a_truck_with_nobody_still_blocks():
    """ADR-310 D1 is unchanged: the reversal is only about the trainee case."""
    src = _code_only(D.publish_dispatch)
    assert "_no_driver" in src
    i = src.index("_no_driver")
    assert "HTTP_409_CONFLICT" in src[i:i + 500]


def test_the_block_is_evaluated_before_the_warning():
    """Otherwise a truck with nobody could be reported as merely warned."""
    src = _code_only(D.publish_dispatch)
    assert src.index("_no_driver") < src.index("_trucks_with_only_a_driver_trainee")


def test_the_warning_names_the_trucks():
    """A warning that does not say which truck is one the dispatcher has to hunt
    for (ADR-309 D1, ADR-300 D2b)."""
    src = _code_only(D.publish_dispatch)
    i = src.index("_trucks_with_only_a_driver_trainee")
    assert "', '.join(_trainee_only)" in src[i:i + 700]


def test_a_trainee_is_never_counted_as_driver_supply():
    """ADR-264 D6's reasoning depends on the separation, and the half of
    ADR-310 D4 that says a trainee is not a driver still stands."""
    assert ROLE_DRIVER != ROLE_DRIVER_TRAINEE
    src = _code_only(D._trucks_missing_a_driver)
    assert "driver_trainee" not in src


# ── D3: the swap sequence generalises ────────────────────────────────────────

def test_the_swap_sequence_covers_every_one_per_truck_role():
    """Adding a second constrained role would otherwise reproduce ADR-321's 500
    for drivers on the next swap."""
    assert D._ONE_PER_TRUCK_ROLES == frozenset({D.ROLE_CAPTAIN, ROLE_DRIVER})
    src = _code_only(D.swap_assignment)
    assert "incoming_role in _ONE_PER_TRUCK_ROLES" in src


def test_the_displaced_member_is_looked_up_by_the_incoming_role():
    """Hardcoding captain here would find no sitting driver and reproduce the
    original IntegrityError."""
    src = _code_only(D.swap_assignment)
    assert "AssignmentMember.role == incoming_role" in src


def test_the_displaced_member_gets_its_own_role_back():
    src = _code_only(D.swap_assignment)
    assert "displaced_member.role = incoming_role" in src


# ── D4: the parked role is outside every predicate ───────────────────────────

def test_the_parked_role_is_outside_every_one_per_truck_predicate():
    """A driver parked as `captain` would trade one violation for another."""
    assert D._PARKED_ROLE not in D._ONE_PER_TRUCK_ROLES
    predicates = {
        str(i.dialect_options["postgresql"]["where"])
        for i in AssignmentMember.__table__.indexes if i.unique
    }
    for p in predicates:
        assert f"'{D._PARKED_ROLE}'" not in p, (
            f"parked role {D._PARKED_ROLE!r} appears in index predicate {p!r}"
        )
