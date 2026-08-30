"""A truck publishes into its OWN phase, and confirm-all repairs gaps (ADR-326).

Eagle was published with 19 members and got ZERO DispatchConfirmation rows,
leaving it unconfirmable from the UI. Root cause: publish_hub derived a
day-level phase from the OTHER trucks on the date and skipped seeding because
Falcon had been finalized hours earlier. Eagle's own status was `active` —
squarely inside its own confirmation window.

The gate predates ADR-288's per-truck publish/finalize split, when a day moved
through one lifecycle together.
"""
import ast
import inspect

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


# ── D1: the seeding gate ─────────────────────────────────────────────────────

def test_the_seeding_gate_reads_this_trucks_own_status():
    src = _code_only(D.publish_hub)
    assert "overall_phase = assignment.status" in src, (
        "the confirmation window must be derived from THIS truck, not the day"
    )


def test_no_other_truck_influences_whether_confirmations_are_seeded():
    """THE bug. `other_statuses` made a finalized neighbour suppress seeding."""
    src = _code_only(D.publish_hub)
    assert "other_statuses" not in src, (
        "a neighbouring truck's status must not decide whether this truck's "
        "crew is asked to confirm (ADR-326 D1)"
    )
    assert "TruckAssignment.id != assignment.id" not in src


def test_the_gate_is_positive_not_an_exclusion():
    """`!= "completed"` behaves identically today but lets a future status
    (cancelled, abandoned) fall through into seeding."""
    src = _code_only(D.publish_hub)
    assert "in ('planned', 'active')" in src or 'in ("planned", "active")' in src
    assert "!= 'completed'" not in src and '!= "completed"' not in src


def test_seeding_and_the_notification_wording_share_one_condition():
    """They used to be able to disagree — telling a crew "please confirm" while
    seeding nothing for them to confirm against."""
    src = _code_only(D.publish_hub)
    assert src.count("overall_phase in ('planned', 'active')") == 2


# ── D2: confirm-all repairs, and says so ─────────────────────────────────────

def test_confirm_all_creates_rows_for_members_that_have_none():
    """It only UPDATEd, so a truck whose seeding was skipped matched nothing and
    returned 200 with confirmed_count=0 — success while confirming nobody."""
    src = _code_only(D.confirm_all_pending)
    assert "DispatchConfirmation(" in src, "confirm-all cannot create a missing row"
    assert "AssignmentMember" in src, "it must resolve who is actually assigned"


def test_confirm_all_reports_created_separately_from_updated():
    """A created row means publish never seeded that member — a different fact
    from someone who simply never replied. One combined number hid the bug."""
    src = _code_only(D.confirm_all_pending)
    assert "'updated': len(pending_rows)" in src
    assert "'created': len(created_ids)" in src


def test_created_rows_are_marked_as_an_override():
    src = _code_only(D.confirm_all_pending)
    assert src.count("dispatch_override") >= 2


def test_the_created_ids_are_audited_not_just_counted():
    src = _code_only(D.confirm_all_pending)
    assert "created_employee_ids" in src


def test_created_rows_reach_the_redis_mirror():
    """Otherwise a member whose row was invented here reads back as unconfirmed
    from the cache — confirmed in Postgres, pending in Redis.

    Asserted on the LOOP that feeds set_confirmation. A first version grepped a
    300-char window before the call, which caught `created_ids` from unrelated
    code above and survived the mutation that removed it from the loop.
    """
    tree = ast.parse(_code_only(D.confirm_all_pending))
    loops = [
        ast.unparse(n) for n in ast.walk(tree)
        if isinstance(n, (ast.For, ast.AsyncFor)) and "set_confirmation" in ast.unparse(n)
    ]
    assert loops, "no loop calls set_confirmation"
    assert any("created_ids" in loop for loop in loops), (
        "the Redis mirror loop skips created rows — they would read back as "
        "unconfirmed from the cache"
    )


def test_no_member_can_receive_two_rows():
    """The create path is keyed on the existing set, so a re-run is a no-op."""
    src = _code_only(D.confirm_all_pending)
    assert "if eid not in existing_ids" in src


# ── Dimension 1 ──────────────────────────────────────────────────────────────

def test_the_new_member_lookup_is_company_scoped():
    """Scoped to the ASSIGNED-MEMBER query specifically.

    A first version sliced from `assigned_ids` to `created_ids`, which spans
    BOTH queries — so deleting company_id from the member lookup still passed on
    the neighbouring existing_ids filter. It survived the mutation. Parse the
    one query instead of grepping a range that contains two.
    """
    tree = ast.parse(_code_only(D.confirm_all_pending))
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "assigned_ids" for t in node.targets
        ):
            target = ast.unparse(node)
    assert target is not None, "assigned_ids assignment not found"
    assert "AssignmentMember" in target
    assert "TruckAssignment.company_id == caller.company_id" in target, (
        "the assigned-member lookup is unscoped — it would confirm another "
        "tenant's crew for the same date"
    )
