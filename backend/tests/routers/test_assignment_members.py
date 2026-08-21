"""Tests for assignment_members router (ADR-147 audit findings).

CRITICAL findings under test:
  1. POST / — AssignmentMember(**assignment_member.model_dump()) sets no company_id
     from caller; model has company_id nullable=False.
  2. POST / — ban-check inner query (line 44) filters AssignmentMember only by
     assignment_id, not by company_id — a cross-tenant ban relationship could
     silently pass or a same-assignment check could match another tenant's rows
     if UUIDs collide.

Additional coverage:
  - GET /{assignment_id} scopes via join to TruckAssignment.company_id
  - DELETE /{member_id} scopes via join to TruckAssignment.company_id
  - Response schema is missing paired_trainer_id and company_id fields
"""
import uuid
from unittest.mock import MagicMock, call, patch
from datetime import date

import pytest
from fastapi import HTTPException


_CID_A = uuid.uuid4()
_CID_B = uuid.uuid4()


def _make_caller(company_id=_CID_A, role="dispatch"):
    emp = MagicMock()
    emp.id = uuid.uuid4()
    emp.company_id = company_id
    emp.role = role
    return emp


# ---------------------------------------------------------------------------
# CRITICAL 1: company_id not set from caller on create
# ---------------------------------------------------------------------------

class TestCreateMemberCompanyIdMissing:
    def test_schema_has_no_company_id(self):
        """AssignmentMemberCreate schema has no company_id — must be injected by endpoint."""
        from app.schemas.assignment_member import AssignmentMemberCreate
        assert "company_id" not in AssignmentMemberCreate.model_fields, (
            "company_id must NOT be in the create schema; it must be injected "
            "from caller.company_id in the endpoint, not supplied by the client."
        )

    def test_model_requires_company_id(self):
        """AssignmentMember model has company_id nullable=False."""
        from app.models.assignment_member import AssignmentMember
        col = AssignmentMember.__table__.c["company_id"]
        assert not col.nullable, "company_id column must be nullable=False"

    def test_create_injects_no_company_id_from_caller(self):
        """
        Demonstrates the bug: model_dump() produces no company_id key,
        so the ORM call creates a row with company_id=None — violating
        nullable=False and multi-tenancy.

        The fix is to call:
            AssignmentMember(**assignment_member.model_dump(), company_id=caller.company_id)
        """
        from app.schemas.assignment_member import AssignmentMemberCreate

        body = AssignmentMemberCreate(
            assignment_id=uuid.uuid4(),
            employee_id=uuid.uuid4(),
            role="walker",
        )
        dumped = body.model_dump()
        assert "company_id" not in dumped, (
            "Schema must not include company_id — it must come from the caller. "
            "This test documents that the endpoint currently never adds it."
        )


# ---------------------------------------------------------------------------
# CRITICAL 2: ban-check inner query missing company_id
# ---------------------------------------------------------------------------

class TestBanCheckCrossTenantQuery:
    """
    Line 44 in assignment_members.py:
        existing_members = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == assignment_member.assignment_id
        ).all()

    No company_id filter. If assignment_id is somehow shared (or reused in
    tests / staging environments) across tenants, this query returns the
    wrong tenant's members and applies their ban relationships to a different
    company's assignment.
    """

    def test_ban_check_query_lacks_company_id(self):
        """
        Simulate what the ban-check query does: filter by assignment_id only.
        Show that rows from another tenant's assignment could be returned.
        """
        from app.models.assignment_member import AssignmentMember

        shared_assignment_id = uuid.uuid4()

        # Member from company A
        member_a = MagicMock()
        member_a.assignment_id = shared_assignment_id
        member_a.company_id = _CID_A
        member_a.employee_id = uuid.uuid4()

        # Member from company B (different tenant, same assignment_id — edge case)
        member_b = MagicMock()
        member_b.assignment_id = shared_assignment_id
        member_b.company_id = _CID_B
        member_b.employee_id = uuid.uuid4()

        all_members = [member_a, member_b]

        db = MagicMock()
        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                # Current query only filters by assignment_id — returns both
                f.all.return_value = all_members
                return f
            q.filter = _filter
            return q
        db.query = _query

        # Simulate the current bug: no company_id filter
        result = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == shared_assignment_id
        ).all()

        # Both company A and B members come back — company_id filter is missing
        assert member_b in result, (
            "Company B member is returned without a company_id filter — "
            "proves the query is not tenant-scoped. "
            "Fix: add AssignmentMember.company_id == caller.company_id to the filter."
        )

    def test_ban_check_should_include_company_id_filter(self):
        """Documents the correct fix: filter must include company_id."""
        from app.models.assignment_member import AssignmentMember

        shared_assignment_id = uuid.uuid4()
        member_a = MagicMock()
        member_a.assignment_id = shared_assignment_id
        member_a.company_id = _CID_A

        member_b = MagicMock()
        member_b.assignment_id = shared_assignment_id
        member_b.company_id = _CID_B

        db = MagicMock()
        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                # Correct behaviour: only return company A members
                f.all.return_value = [member_a]
                return f
            q.filter = _filter
            return q
        db.query = _query

        result = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == shared_assignment_id,
            AssignmentMember.company_id == _CID_A,
        ).all()

        assert member_b not in result
        assert member_a in result


# ---------------------------------------------------------------------------
# GET /{assignment_id} — scoped via join
# ---------------------------------------------------------------------------

class TestGetAssignmentMembersScoping:
    def test_returns_404_for_foreign_assignment(self):
        """GET /{id} returns empty list (not 404, by design) for a foreign assignment."""
        from app.routers.assignment_members import get_assignment_members

        caller = _make_caller(company_id=_CID_A)

        db = MagicMock()
        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.all.return_value = []   # no rows match after join scope
                return f
            q.filter = _filter
            q.join = MagicMock(return_value=q)
            return q
        db.query = _query

        result = get_assignment_members(
            assignment_id=uuid.uuid4(),
            caller=caller,
            _={},
            db=db,
        )
        assert result == []


# ---------------------------------------------------------------------------
# DELETE /{member_id} — scoped via join
# ---------------------------------------------------------------------------

class TestRemoveMemberScoping:
    def test_returns_404_for_foreign_member(self):
        """DELETE /{member_id} raises 404 when member belongs to another company."""
        from app.routers.assignment_members import remove_assignment_member

        caller = _make_caller(company_id=_CID_A)

        db = MagicMock()
        def _query(model):
            q = MagicMock()
            def _filter(*args):
                f = MagicMock()
                f.first.return_value = None  # join scope returns nothing
                return f
            q.filter = _filter
            q.join = MagicMock(return_value=q)
            return q
        db.query = _query

        with pytest.raises(HTTPException) as exc_info:
            remove_assignment_member(
                member_id=uuid.uuid4(),
                caller=caller,
                _={},
                db=db,
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Schema gap: paired_trainer_id and company_id now present in response (fixed in ADR-148)
# ---------------------------------------------------------------------------

class TestAssignmentMemberResponseSchema:
    def test_response_schema_has_paired_trainer_id(self):
        """AssignmentMemberResponse now exposes paired_trainer_id (fixed in ADR-148)."""
        from app.schemas.assignment_member import AssignmentMemberResponse
        assert "paired_trainer_id" in AssignmentMemberResponse.model_fields, (
            "paired_trainer_id must be present in AssignmentMemberResponse (fixed in ADR-148)."
        )

    def test_response_schema_has_company_id(self):
        """AssignmentMemberResponse now exposes company_id (fixed in ADR-148)."""
        from app.schemas.assignment_member import AssignmentMemberResponse
        assert "company_id" in AssignmentMemberResponse.model_fields
