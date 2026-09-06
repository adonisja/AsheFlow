"""Deleting a favourite or block must not 500 (ADR-384).

WHAT WENT WRONG
`delete_employee_relationships` built its audit `before` snapshot from
`relationship.related_employee_id`. That column does not exist — the model's
column is `target_employee_id` — so every DELETE raised AttributeError and
returned 500. Favourites and blocks could be created but never removed.

The bad reference arrived with ADR-132's compliance sweep (654dd657), which
added the snapshot for GDPR Art. 17 traceability. The audit trail meant to make
deletions accountable is what made them impossible.

WHY IT SURVIVED
Every existing test for this endpoint reads the router's SOURCE TEXT and asserts
on substrings — ADR-361's separation guard, ADR-353's cap query. A source-level
test cannot see an AttributeError: the string `relationship_type == "sep"` was
present, the guard was "covered", and the function still failed on every call.

So these tests CALL the endpoint function. That is the only kind that fails when
an attribute does not exist.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.models.employee_relationship import EmployeeRelationship
from app.routers.employee_relationships import delete_employee_relationships
from tests.conftest import make_employee, make_relationship


class TestDeletingARelationshipActuallyWorks:
    def test_an_employee_can_delete_their_own_favourite(self, db):
        """The regression. Before the fix this raised AttributeError -> 500."""
        me = make_employee(db, role="walker", name="Walker One")
        them = make_employee(db, role="driver", name="Driver Two")
        rel = make_relationship(db, me, them, "fav")

        delete_employee_relationships(
            employee_relationship_id=rel.id, db=db, caller=me,
        )

        assert db.query(EmployeeRelationship).filter_by(id=rel.id).first() is None, (
            "the favourite survived a successful delete call"
        )

    def test_an_employee_can_delete_their_own_block(self, db):
        me = make_employee(db, role="walker", name="Walker One")
        them = make_employee(db, role="walker", name="Walker Two")
        rel = make_relationship(db, me, them, "ban")

        delete_employee_relationships(
            employee_relationship_id=rel.id, db=db, caller=me,
        )

        assert db.query(EmployeeRelationship).filter_by(id=rel.id).first() is None

    def test_the_audit_snapshot_reads_a_column_that_exists(self, db):
        """Pin the specific defect.

        `target_employee_id` is the model's column. Asserting the attribute is
        readable here means a rename that misses this write site fails LOUDLY,
        rather than only when a user presses the delete button.
        """
        me = make_employee(db, role="walker", name="Walker One")
        them = make_employee(db, role="driver", name="Driver Two")
        rel = make_relationship(db, me, them, "fav")

        assert hasattr(rel, "target_employee_id")
        assert not hasattr(rel, "related_employee_id"), (
            "the audit snapshot in delete_employee_relationships reads this name; "
            "if it exists now, update the snapshot rather than deleting this test"
        )


class TestTheGuardsStillHold:
    """The ADR-361 and ownership guards, exercised rather than grepped."""

    def test_another_employees_relationship_is_403(self, db):
        owner = make_employee(db, role="walker", name="Owner")
        other = make_employee(db, role="walker", name="Interloper")
        target = make_employee(db, role="driver", name="Target")
        rel = make_relationship(db, owner, target, "fav")

        with pytest.raises(HTTPException) as exc:
            delete_employee_relationships(
                employee_relationship_id=rel.id, db=db, caller=other,
            )
        assert exc.value.status_code == 403

    def test_a_separation_is_404_even_for_its_source_employee(self, db):
        """ADR-361 — a separation is dispatch's decision. The ownership check
        PASSES for the source employee, so only the type check stops them
        lifting it."""
        me = make_employee(db, role="walker", name="Walker One")
        them = make_employee(db, role="walker", name="Walker Two")
        sep = make_relationship(db, me, them, "sep")

        with pytest.raises(HTTPException) as exc:
            delete_employee_relationships(
                employee_relationship_id=sep.id, db=db, caller=me,
            )
        assert exc.value.status_code == 404
        assert db.query(EmployeeRelationship).filter_by(id=sep.id).first() is not None

    def test_a_missing_relationship_is_404(self, db):
        me = make_employee(db, role="walker", name="Walker One")
        with pytest.raises(HTTPException) as exc:
            delete_employee_relationships(
                employee_relationship_id=uuid.uuid4(), db=db, caller=me,
            )
        assert exc.value.status_code == 404
