"""rebalance_crews must not move a captain (ADR-256).

rebalance_crews.py is proprietary → gitignored (syncs to private).

Found by the ADR-115 audit (Dimension 8), not by a test. The candidate filter read
``role not in ("driver", "trainee")`` — written before captains existed, so a
captain silently became movable. Two failures follow:

  1. assign_captains places a captain against familiarisation state and manual
     pins; a rebalance move undoes that steering with no warning.
  2. moving a captain onto a truck that already has one builds a crew the partial
     unique index rejects at persist time with an IntegrityError — an error raised
     far from the code that caused it.

The general shape, worth remembering: a filter written as a DENY-LIST of roles
silently admits every role added after it.
"""
import uuid

import pytest

try:
    from app.services.rebalance_crews import rebalance_crews
except ImportError:
    pytest.skip("proprietary dispatch deps not available (CI skip)", allow_module_level=True)

from tests.conftest import make_employee, make_truck


def _crew_ids(crews, truck_id, role):
    return [m["id"] for m in crews[truck_id] if m["role"] == role]


class TestCaptainIsImmovable:
    def test_captain_stays_on_their_truck_when_rebalancing(self, db):
        """An over-staffed truck sheds a walker, never its captain."""
        over, under = make_truck(db, "Over"), make_truck(db, "Under")
        driver = make_employee(db, role="driver", name="D")
        captain = make_employee(db, role="captain", name="C")
        walkers = [make_employee(db, role="walker", name=f"W{i}") for i in range(4)]

        crews = {
            over.id: (
                [{"id": driver.id, "role": "driver"},
                 {"id": captain.id, "role": "captain"}]
                + [{"id": w.id, "role": "walker"} for w in walkers]
            ),
            under.id: [],
        }

        rebalance_crews(crews, db)

        assert captain.id in _crew_ids(crews, over.id, "captain"), (
            "the captain was moved off their assigned truck by rebalancing"
        )
        assert captain.id not in _crew_ids(crews, under.id, "captain")

    def test_rebalance_never_puts_two_captains_on_one_truck(self, db):
        """The D2 invariant must survive rebalancing, not just assignment.

        Both trucks already have a captain. Whatever rebalancing does to even out
        headcount, neither truck may end up with two — that crew would be rejected
        by the partial unique index when persisted.
        """
        over, under = make_truck(db, "Over"), make_truck(db, "Under")
        cap_a = make_employee(db, role="captain", name="Cap A")
        cap_b = make_employee(db, role="captain", name="Cap B")
        walkers = [make_employee(db, role="walker", name=f"W{i}") for i in range(5)]

        crews = {
            over.id: (
                [{"id": cap_a.id, "role": "captain"}]
                + [{"id": w.id, "role": "walker"} for w in walkers]
            ),
            under.id: [{"id": cap_b.id, "role": "captain"}],
        }

        rebalance_crews(crews, db)

        for truck_id in (over.id, under.id):
            assert len(_crew_ids(crews, truck_id, "captain")) == 1, (
                f"truck {truck_id} ended with "
                f"{len(_crew_ids(crews, truck_id, 'captain'))} captains"
            )

    def test_walkers_still_move(self, db):
        """The guard must not freeze rebalancing altogether."""
        over, under = make_truck(db, "Over"), make_truck(db, "Under")
        captain = make_employee(db, role="captain", name="C")
        walkers = [make_employee(db, role="walker", name=f"W{i}") for i in range(5)]

        crews = {
            over.id: (
                [{"id": captain.id, "role": "captain"}]
                + [{"id": w.id, "role": "walker"} for w in walkers]
            ),
            under.id: [],
        }

        rebalance_crews(crews, db)

        assert len(crews[under.id]) > 0, "rebalancing should still shed walkers"
        assert all(m["role"] == "walker" for m in crews[under.id]), (
            "only walkers should have moved"
        )
