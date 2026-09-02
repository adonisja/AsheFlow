"""A dispatch separation blocks a pairing without either employee seeing it (ADR-361).

The feature's whole risk surface is "every read and write that touches
employee_relationships". A separation shares that table with bans and sits in
the same two columns, so invisibility is an explicit exclusion at each surface
rather than a property of the schema — and a forgotten one shows the employee a
ban they never made.

These tests pin all four surfaces plus the enforcement count.
"""
import re
import uuid
from pathlib import Path

import pytest

from app.models.employee_relationship import EmployeeRelationship
from app.services.check_ban import BLOCKING_TYPES, check_ban_relationship
from tests.conftest import SEED_COMPANY_ID, make_employee, make_relationship

APP = Path(__file__).resolve().parents[2] / "app"


class TestSeparationBlocksPairing:
    def test_a_separation_blocks_co_assignment_in_both_directions(self, db):
        a = make_employee(db, "walker", "Sep A")
        b = make_employee(db, "walker", "Sep B")
        make_relationship(db, a, b, "sep")

        assert check_ban_relationship(a.id, b.id, db, SEED_COMPANY_ID) is True, (
            "a separation must block the pairing the same as a ban"
        )
        assert check_ban_relationship(b.id, a.id, db, SEED_COMPANY_ID) is True, (
            "a separation is symmetric — order of the pair must not matter"
        )

    def test_an_unrelated_pair_is_not_blocked(self, db):
        a = make_employee(db, "walker", "Free A")
        b = make_employee(db, "walker", "Free B")
        assert check_ban_relationship(a.id, b.id, db, SEED_COMPANY_ID) is False

    def test_the_check_is_company_scoped(self, db):
        """Shipped without a company_id filter; fixed in ADR-361."""
        a = make_employee(db, "walker", "Scoped A")
        b = make_employee(db, "walker", "Scoped B")
        other_company = uuid.uuid4()
        db.add(
            EmployeeRelationship(
                id=uuid.uuid4(),
                company_id=other_company,
                employee_id=a.id,
                target_employee_id=b.id,
                relationship_type="sep",
            )
        )
        db.commit()

        assert check_ban_relationship(a.id, b.id, db, SEED_COMPANY_ID) is False, (
            "another tenant's separation must not block this company's pairing"
        )


class TestSeparationIsInvisibleToBothEmployees:
    def test_it_is_excluded_from_the_per_employee_read(self, db):
        src = APP / "routers" / "employee_relationships.py"
        body = src.read_text()
        reads = [
            m for m in re.finditer(
                r"EmployeeRelationship\.employee_id == employee_id,\s*\n\s*"
                r"EmployeeRelationship\.company_id == caller\.company_id,",
                body,
            )
        ]
        assert reads, "the per-employee read moved — re-pin this test"
        for m in reads:
            window = body[m.start(): m.end() + 200]
            assert 'relationship_type != "sep"' in window, (
                "the per-employee read would return a separation to the employee, "
                "who would see it as a ban they never made"
            )

    def test_the_clear_all_path_does_not_delete_separations(self, db):
        body = (APP / "routers" / "employee_relationships.py").read_text()
        idx = body.index("def clear_employee_relationships")
        window = body[idx: idx + 2000]
        assert 'relationship_type != "sep"' in window, (
            "clearing an employee's preferences would silently lift a dispatch "
            "separation placed on them"
        )

    def test_an_employee_cannot_delete_a_separation_by_id(self, db):
        body = (APP / "routers" / "employee_relationships.py").read_text()
        idx = body.index("def delete_employee_relationships")
        window = body[idx: idx + 1200]
        assert 'relationship_type == "sep"' in window, (
            "the ownership check passes for the separation's source employee, so "
            "without a type check they can lift a separation dispatch placed on them"
        )


class TestSeparationDoesNotSpendTheBanCap:
    def test_the_cap_query_counts_bans_only(self, db):
        """ADR-361 D3 — a separation is dispatch's decision, not the employee's.

        Counting it would refuse an employee their own second ban for a reason
        they cannot see.
        """
        body = (APP / "routers" / "employee_relationships.py").read_text()
        idx = body.index("ban_count = db.query(EmployeeRelationship)")
        window = body[idx: idx + 400]
        assert 'relationship_type == "ban"' in window, (
            "the 2-ban cap must count bans only"
        )
        assert "BLOCKING_TYPES" not in window and '"sep"' not in window, (
            "a separation must not consume the employee's own ban allowance"
        )


class TestEveryEnforcementSiteCoversSeparations:
    """The one that fails loudly when someone adds a ninth site.

    A site filtering the literal "ban" pairs a separated pair silently, which is
    the single failure this feature exists to prevent. Grepping for it in a test
    is crude, and it is the only thing that catches a NEW site added later by
    someone who has not read this ADR.
    """

    def test_no_enforcement_site_filters_on_the_ban_literal(self):
        offenders = []
        for path in sorted((APP / "services").rglob("*.py")):
            body = path.read_text(errors="ignore")
            for num, line in enumerate(body.split("\n"), 1):
                if 'EmployeeRelationship.relationship_type == "ban"' in line:
                    offenders.append(f"{path.name}:{num}")
        assert not offenders, (
            "these filter bans only, so a dispatch separation would not block the "
            "pairing — import BLOCKING_TYPES from app.services.check_ban instead: "
            + ", ".join(offenders)
        )

    def test_the_expected_services_enforce_blocking_types(self):
        expected = {
            "assign_walkers.py",
            "assign_captains.py",
            "assign_trainers.py",
            "rebalance_crews.py",
            "seat_crew_pins.py",
            "seat_truck_pins.py",
        }
        found = {
            p.name
            for p in (APP / "services").rglob("*.py")
            if "BLOCKING_TYPES" in p.read_text(errors="ignore") and p.name != "check_ban.py"
        }
        missing = expected - found
        assert not missing, (
            f"these stopped enforcing separations: {sorted(missing)}. If a service "
            "was renamed or removed, update this list deliberately."
        )

    def test_blocking_types_is_exactly_ban_and_sep(self):
        assert set(BLOCKING_TYPES) == {"ban", "sep"}


class TestSeparationIsNotOverridable:
    def test_a_separation_is_never_walker_override_eligible(self):
        """ADR-361 D2 — a preference must not undo a management decision."""
        body = (APP / "services" / "assign_walkers.py").read_text()
        assert 'overridable = ban.relationship_type == "ban"' in body, (
            "the override-eligibility flag no longer distinguishes a sep, so a "
            "walker-vs-walker override could release a dispatch separation"
        )
        assert body.count("is_walker = overridable and") == 2, (
            "both branches of the ban map must gate override eligibility on the "
            "relationship type; one unguarded branch is a releasable separation"
        )
