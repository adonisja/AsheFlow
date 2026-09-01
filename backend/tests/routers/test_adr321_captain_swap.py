"""There is no Pythonic swap when the DB forbids the intermediate state (ADR-321).

Dragging a captain onto a truck that already had one 500'd, while every other
role swapped fine. `swap_assignment` moved the incoming member and never moved
the sitting one out, so both briefly held role='captain' on one assignment_id.

Only captains broke because captain is the ONLY role with a one-per-truck index:

    CREATE UNIQUE INDEX uq_assignment_members_one_captain
      ON assignment_members (assignment_id) WHERE role = 'captain'

Measured against that real index: moving the incoming captain in directly fails,
AND so does a single UPDATE ... CASE swapping both — it is a bare unique index,
not a constraint, so it cannot be DEFERRABLE and Postgres checks it per
statement, row by row. There is no atomic exchange; only a sequence works.
"""
import ast
import inspect

from app.models.assignment_member import AssignmentMember
from app.routers import dispatch as D


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


SRC = _code_only(D.swap_assignment)


# ── The constraint that makes captains special ───────────────────────────────

def test_only_captain_has_a_one_per_truck_index():
    """Two drivers on a truck is legal, which is why the identical code path
    worked for every other role."""
    idx = {i.name: i for i in AssignmentMember.__table__.indexes}
    assert "uq_assignment_members_one_captain" in idx
    one = idx["uq_assignment_members_one_captain"]
    assert one.unique is True
    assert "captain" in str(one.dialect_options["postgresql"]["where"])


# ── D1: the sequence ─────────────────────────────────────────────────────────

def test_the_sitting_captain_is_displaced_before_the_incoming_one_moves():
    """THE ordering. Each flush boundary must leave the index satisfied — this
    is not stylistic, getting it wrong is the 500 being fixed."""
    # Position alone is not the invariant: a mutation that moved the park to
    # immediately before the move kept `park < move` true while changing the
    # flush structure. What matters is that the park is FLUSHED — sent to the
    # database — before the move statement runs, because the index is checked
    # per statement.
    park = SRC.index("displaced_member.role = _PARKED_ROLE")
    move = SRC.index("target_member.assignment_id = destination_assignment.id")
    assert park < move, "the sitting captain must be parked BEFORE the move"

    between = SRC[park:move]
    assert "db.flush()" in between, (
        "the park must be flushed before the move — without its own flush the "
        "two statements reach Postgres together and the partial index rejects "
        "the transient duplicate"
    )

    # And the park must sit inside the captain guard, not be hoisted out of it
    # into the common path where it would run for every role.
    guard = SRC.index("if displaced_member is not None")
    assert guard < park, "the park must stay inside its own guard"

    # NOTE on what is deliberately NOT asserted: relocating the park to
    # immediately before the move, keeping its flush, is an EQUIVALENT mutant —
    # verified against Postgres that it emits the same statements in the same
    # order and swaps correctly. Failing it would pin code shape rather than
    # behaviour. The real regression is losing the flush, which the assertion
    # above catches.


def test_the_source_is_captured_before_any_mutation():
    """After the move the row no longer records where the incoming captain came
    from, and the displaced captain needs that slot."""
    capture = SRC.index("source_assignment_id = target_member.assignment_id")
    move = SRC.index("target_member.assignment_id = destination_assignment.id")
    assert capture < move


def test_only_one_displacement_is_needed():
    """Moving the incoming captain out of its source frees that slot as a side
    effect, so the displaced captain has somewhere to land."""
    assert SRC.count("_PARKED_ROLE") == 1


def test_the_displacement_only_runs_for_captains():
    """Every other role has no such index and must keep its existing path."""
    i = SRC.index("displaced_member = None")
    guard = SRC[i:i + 200]
    # ADR-322 D3 generalised this from `== ROLE_CAPTAIN` to set membership so
    # a second one-per-truck role needs no new swap code.
    assert "incoming_role in _ONE_PER_TRUCK_ROLES" in guard


def test_the_sitting_captain_lookup_excludes_the_member_being_moved():
    """A same-truck role change would otherwise find the mover as its own
    displaced captain and park it."""
    assert "AssignmentMember.employee_id != target_member.employee_id" in SRC


def test_an_unassigned_swap_leaves_the_displaced_member_unassigned():
    """`source_assignment_id is None` means the incoming captain came from the
    pool — so the displaced one goes there, which is a true exchange."""
    assert "if source_assignment_id is not None" in SRC
    i = SRC.index("if source_assignment_id is not None")
    assert "db.delete(displaced_member)" in SRC[i:i + 400]


# ── D2: park by role, not by delete ──────────────────────────────────────────

def test_the_displaced_member_is_parked_by_role_not_deleted():
    """`assignment_id` is NOT NULL so there is no null slot, and this schema
    represents unassigned as NO ROW. Deleting would discard paired_trainer_id,
    ap_arrived_at, trip_count and the row identity that audit rows and
    DispatchConfirmation reference by member id."""
    assert AssignmentMember.__table__.columns["assignment_id"].nullable is False
    assert "displaced_member.role = _PARKED_ROLE" in SRC
    # the role is restored in the same transaction
    assert "displaced_member.role = incoming_role" in SRC


def test_the_parked_role_is_outside_the_index_predicate():
    """Any value outside WHERE role='captain' works; it must not be 'captain'."""
    assert D._PARKED_ROLE != "captain"
    assert D._PARKED_ROLE == D.ROLE_WALKER


# ── D3: a constraint violation is a 409 ──────────────────────────────────────

def test_an_integrity_error_becomes_a_409_naming_the_sitting_captain():
    """It escaped as a 500, which cost twice: the message said "Internal Server
    Error" for a state the system understands exactly, and because a 500
    bypasses the CORS middleware the browser reported a MISSING
    Access-Control-Allow-Origin header instead — pointing at CORS and at
    permissions, when the cause was neither."""
    assert "except IntegrityError" in SRC
    assert "HTTP_409_CONFLICT" in SRC
    assert "already has a captain" in SRC
    assert "db.rollback()" in SRC


def test_the_409_does_not_leak_the_database_error():
    """Dimension 6 — the raw IntegrityError text must not reach the response."""
    i = SRC.index("except IntegrityError")
    block = SRC[i:i + 900]
    for leak in ("str(e)", "str(exc)", "IntegrityError)", "orig"):
        assert leak not in block.replace("except IntegrityError:", ""), leak


def test_the_sitting_captain_lookup_is_company_scoped():
    """Dimension 1 — a caller must not learn another tenant's captain's name
    from a refusal."""
    i = SRC.index("except IntegrityError")
    block = SRC[i:i + 900]
    assert block.count("company_id == caller.company_id") >= 2


# ── The other roles are untouched ────────────────────────────────────────────

def test_the_trainer_trainee_pairing_branches_are_unchanged():
    """ADR-210's pairing travel must survive this change."""
    assert "if role == ROLE_TRAINER:" in SRC
    assert "elif role == ROLE_TRAINEE:" in SRC
    assert "paired_trainer_id" in SRC
