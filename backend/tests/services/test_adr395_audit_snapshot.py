"""Audit snapshots are validated against the model (ADR-395).

WHY THIS EXISTS
ADR-384: `delete_employee_relationships` read
`relationship.related_employee_id` for its audit payload. The column is
`target_employee_id`. Every DELETE raised AttributeError and 500'd, so favourites
and blocks could be created and never removed -- for months, while two ADRs added
source-text tests to that very function.

An audit snapshot runs on the UNHAPPY path, which is where nobody looks. This
helper moves the failure from "a user pressed delete" to "any test touched the
code".
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.employee_relationship import EmployeeRelationship
from app.services.audit_snapshot import UnknownAuditColumn, snapshot


def _rel():
    return EmployeeRelationship(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        target_employee_id=uuid.uuid4(),
        relationship_type="fav",
    )


class TestTheAdr384RegressionIsCaught:
    def test_the_exact_bad_column_raises(self):
        with pytest.raises(UnknownAuditColumn) as exc:
            snapshot(_rel(), "related_employee_id")
        assert "related_employee_id" in str(exc.value)

    def test_the_message_names_the_model_and_the_real_columns(self):
        """ADR-384 took a database query to diagnose. The answer was in the
        mapper the whole time, so the error carries it."""
        with pytest.raises(UnknownAuditColumn) as exc:
            snapshot(_rel(), "related_employee_id")
        msg = str(exc.value)
        assert "EmployeeRelationship" in msg
        assert "target_employee_id" in msg, "the correct name must be suggested"

    def test_a_valid_column_set_works(self):
        out = snapshot(_rel(), "employee_id", "target_employee_id", "relationship_type")
        assert set(out) == {"employee_id", "target_employee_id", "relationship_type"}
        assert out["relationship_type"] == "fav"

    def test_it_subclasses_AttributeError(self):
        """The original failure WAS an AttributeError, so existing handlers and
        any `except AttributeError` in a caller keep behaving the same."""
        assert issubclass(UnknownAuditColumn, AttributeError)


class TestTheValuesAreJsonSafe:
    def test_a_uuid_becomes_a_string(self):
        """The payload lands in a JSONB column; a raw UUID is not serialisable.
        This is why the original call sites were full of str() casts."""
        out = snapshot(_rel(), "employee_id")
        assert isinstance(out["employee_id"], str)

    def test_a_datetime_becomes_an_isoformat_string(self):
        class Fake:
            created_at = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
        out = snapshot(Fake(), "created_at")
        assert out["created_at"].startswith("2026-09-07T12:00")

    def test_none_survives_as_none(self):
        """None is meaningful in an audit row -- "this field was unset" is not
        the same as the string 'None'."""
        r = _rel()
        r.relationship_type = None
        assert snapshot(r, "relationship_type")["relationship_type"] is None

    def test_a_plain_string_is_not_mangled(self):
        assert snapshot(_rel(), "relationship_type")["relationship_type"] == "fav"


class TestExtraValuesAreMergedUnvalidated:
    def test_extra_keys_appear(self):
        """`extra` is for things that are NOT columns -- a computed count, the
        actor's identity -- so there is nothing to validate them against."""
        out = snapshot(_rel(), "relationship_type", reason="cleanup", count=3)
        assert out["reason"] == "cleanup"
        assert out["count"] == 3

    def test_extra_does_not_bypass_column_validation(self):
        """A bad column must still raise even when extra values are supplied."""
        with pytest.raises(UnknownAuditColumn):
            snapshot(_rel(), "related_employee_id", reason="cleanup")


class TestANonMappedObjectIsNotRejected:
    def test_a_plain_object_still_works(self):
        """Not everything audited is a mapped model. Validation applies where a
        mapper exists and gets out of the way where it does not, rather than
        forcing callers to special-case."""
        class Plain:
            foo = "bar"
        assert snapshot(Plain(), "foo") == {"foo": "bar"}
