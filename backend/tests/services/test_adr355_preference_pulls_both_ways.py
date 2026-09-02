"""ADR-355 — a preference pulls both ways, weighted by who expressed it.

Before this, `get_fans` read only "who ON A TRUCK favs the candidate", so a
candidate's own favourite was inert: no fan meant no boost, no tie to break, and
the bidirectional check never ran. Measured on staging over 40 runs each,
driver→walker placed the pair together 27% of the time and walker→driver 15%
against a ~17% baseline — the walker's own choice did nothing.

Two invariants are load-bearing and easy to break by accident:

  D2  the boost is weighted by the role of WHOEVER EXPRESSED the preference.
      Weighting by the TARGET's role reads naturally and inverts the hierarchy:
      a walker favouring a driver would out-pull a driver favouring a walker.

  D3  one pair earns one boost. A mutual fav produces two rows with two
      different expressors; a dedupe keyed on the expressor keeps both and the
      boosts compound. Measured at 2.170 instead of 1.800 — more pull than the
      tridirectional bonus that is supposed to be the strongest signal.
"""
import ast
import inspect

from app.services import fans_list as FL
from app.services import calculate_weights as CW


def _src(fn) -> str:
    return ast.unparse(ast.parse(inspect.getsource(fn)))


def test_get_fans_reads_both_directions():
    """Either half of a pair must be able to create pull."""
    src = _src(FL.get_fans)
    assert "or_(" in src, "both directions must be OR'd into one query"
    assert "employee_id == candidate_id" in src, (
        "the candidate's OWN favourites must be read — that direction was inert"
    )
    assert "target_employee_id == candidate_id" in src, (
        "the placed crew member's favourites must still be read"
    )


def test_the_returned_id_is_the_one_who_expressed_the_preference():
    """D2 — the role that weights the boost.

    Returning the placed crew member in both cases would weight a walker's pick
    by the driver's 0.70 and invert the hierarchy the weights encode.
    """
    src = _src(FL.get_fans)
    assert "expressed_by" in src, (
        "get_fans must return the EXPRESSOR, since calculate_weights weights the "
        "boost by that person's role"
    )


def test_a_mutual_pair_yields_one_entry_not_two():
    """D3 — dedupe on the PAIR, not on the expressor.

    Keyed on the expressor, a mutual fav survives twice (two distinct ids) and
    the role loop runs twice.
    """
    src = _src(FL.get_fans)
    assert "pair_seen" in src, "the dedupe must be keyed on the pair"
    # The key must be the OTHER party, which is stable across both directions.
    assert "other" in src, "the pair key must be the non-candidate half"


def test_the_mutual_winner_is_deterministic():
    """Whichever row the database returned first is not an acceptable tie-break.

    The placed crew member's half must win, so a driver favouring a walker keeps
    the driver's weight even when the walker favours back.
    """
    src = _src(FL.get_fans)
    assert "seen[other] == candidate_id" in src, (
        "when both directions exist, the placed member's half must be kept "
        "explicitly — not left to row order"
    )


def test_the_candidate_can_be_their_own_fan_without_crashing():
    """The candidate is not in assigned_crews, so the role lookup must not assume it.

    A bare next() over the crew raised StopIteration and would have aborted the
    whole dispatch run the first time a candidate's own favourite counted.
    """
    src = _src(CW.calculate_weights)
    assert "str(fan_id) == str(employee_id)" in src, (
        "calculate_weights must recognise the candidate as their own fan"
    )
    assert "employee_role" in src
    idx = src.find("assigned_crews[truck_id] if c['id'] == fan_id")
    if idx == -1:
        idx = src.find("assigned_crews[truck_id]")
    assert idx != -1
    # The crew lookup must have a default rather than raising.
    window = src[idx - 200: idx + 200]
    assert "None" in window, "the crew role lookup must fall back, not raise"


# ── Behavioural tests ────────────────────────────────────────────────────────
# The grep-based tests above assert the code MENTIONS the right things. Both of
# the bugs this ADR fixed survived them: deduping by expressor, and returning
# the placed member instead of the expressor, each left every string in place.
# Presence is not behaviour — these run the function.

import uuid as _uuid

from app.models.employee import Employee
from app.models.employee_relationship import EmployeeRelationship


def _emp(db, company_id, role):
    e = Employee(
        id=_uuid.uuid4(), company_id=company_id, name=f"{role}-{_uuid.uuid4().hex[:6]}",
        role=role, is_active=True, account_status="active",
        reset_on_graduation=False, hr_system_id_adp=_uuid.uuid4(),
        hr_system_id_adp_verified=False,
    )
    db.add(e)
    return e


def _fav(db, company_id, a, b):
    db.add(EmployeeRelationship(
        id=_uuid.uuid4(), company_id=company_id,
        employee_id=a.id, target_employee_id=b.id, relationship_type="fav",
    ))


def test_behaviour_candidates_own_fav_creates_pull(db):
    """The direction that used to be inert must now return a fan."""
    cid = _uuid.uuid4()
    driver, walker = _emp(db, cid, "driver"), _emp(db, cid, "walker")
    _fav(db, cid, walker, driver)          # candidate -> placed member
    db.flush()

    crews = {"t1": [{"id": driver.id, "role": "driver"}], "t2": []}
    fans = FL.get_fans(walker.id, crews, db)
    assert fans.get("t1"), "the candidate's own favourite produced no pull"


def test_behaviour_the_expressor_is_returned_not_the_target(db):
    """D2 — returning the target would weight a walker's pick by the driver's role."""
    cid = _uuid.uuid4()
    driver, walker = _emp(db, cid, "driver"), _emp(db, cid, "walker")
    _fav(db, cid, walker, driver)          # the WALKER expressed it
    db.flush()

    crews = {"t1": [{"id": driver.id, "role": "driver"}]}
    fans = FL.get_fans(walker.id, crews, db)
    assert fans["t1"] == [walker.id], (
        f"expected the expressor ({walker.id}), got {fans['t1']} — the boost "
        "would be weighted by the wrong role"
    )


def test_behaviour_a_mutual_pair_returns_exactly_one_fan(db):
    """D3 — two entries means two role boosts compounding on one truck."""
    cid = _uuid.uuid4()
    driver, walker = _emp(db, cid, "driver"), _emp(db, cid, "walker")
    _fav(db, cid, driver, walker)
    _fav(db, cid, walker, driver)
    db.flush()

    crews = {"t1": [{"id": driver.id, "role": "driver"}]}
    fans = FL.get_fans(walker.id, crews, db)
    assert len(fans["t1"]) == 1, (
        f"a mutual pair yielded {len(fans['t1'])} fans — the boosts compound "
        "(measured 2.170 vs the intended 1.800 on staging)"
    )
    assert fans["t1"] == [driver.id], (
        "the PLACED member's half must win, so the stronger role weights the boost"
    )
