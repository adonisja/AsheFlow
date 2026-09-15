"""ADR-417 D3-D5 — the route log's quarantine table.

No skip guards (ADR-311): CI supplies every module these tests import.
"""
import datetime as dt

import pytest
from pydantic import ValidationError

from app.schemas.walker_day import RouteIn, ToteIn, WalkerDayIn, WalkerDaySubmitIn

TODAY = dt.date.today()


def _day(**over):
    base = {"walker_name": "Sam Walker", "collected_on": TODAY}
    base.update(over)
    return base


class TestTheTrustBoundaryIsTypedAtEveryLevel:
    """Dimension 9. The payload lands in JSONB, which is exactly the case the
    rule exists for: `Any` here would be persisted verbatim and echoed into a
    UI."""

    def test_a_valid_day_is_accepted(self):
        got = WalkerDayIn(**_day(routes=[{
            "route_id": 1, "difficulty": "hard",
            "totes": [{"bag_id": "Navy 228", "addresses": ["1 Main St"]}],
        }]))
        assert got.routes[0].totes[0].bag_id == "Navy 228"

    @pytest.mark.parametrize("over,why", [
        ({"id": "sneaky"},                              "a client cannot set the row id"),
        ({"updated_at": "2026-01-01"},                  "the timestamp is the server's"),
        ({"company_id": "00000000-0000-0000-0000-000000000000"},
                                                        "company comes from the token (ADR-415 D2)"),
    ])
    def test_extra_keys_are_refused_at_the_day(self, over, why):
        with pytest.raises(ValidationError):
            WalkerDayIn(**_day(**over)), why

    def test_extra_keys_are_refused_inside_a_route(self):
        """extra="forbid" has to hold at EVERY level, not just the outermost —
        a nested dict is where an unvalidated blob would hide."""
        with pytest.raises(ValidationError):
            WalkerDayIn(**_day(routes=[{"route_id": 1, "injected": True}]))

    def test_extra_keys_are_refused_inside_a_tote(self):
        with pytest.raises(ValidationError):
            WalkerDayIn(**_day(routes=[{
                "route_id": 1, "totes": [{"bag_id": "A", "injected": True}],
            }]))

    @pytest.mark.parametrize("bad", ["7am", "25:00", "8:5", "08:60"])
    def test_times_must_be_hh_mm(self, bad):
        with pytest.raises(ValidationError):
            WalkerDayIn(**_day(arrival_time=bad))

    def test_an_empty_time_is_allowed(self):
        """Not every day has a recorded arrival. Blank is honest; inventing one
        is not."""
        assert WalkerDayIn(**_day(arrival_time="")).arrival_time == ""

    def test_difficulty_is_checked_against_the_client_list(self):
        with pytest.raises(ValidationError):
            WalkerDayIn(**_day(routes=[{"route_id": 1, "difficulty": "lethal"}]))

    def test_ov_size_is_checked(self):
        with pytest.raises(ValidationError):
            WalkerDayIn(**_day(routes=[{"route_id": 1, "ovs": [{"size": "XXL"}]}]))

    def test_counts_cannot_be_negative(self):
        with pytest.raises(ValidationError):
            ToteIn(bag_id="A", stop_package_count=-1)

    def test_an_address_is_bounded(self):
        """max_length on the LIST caps the count, not the size of each entry."""
        with pytest.raises(ValidationError):
            ToteIn(bag_id="A", addresses=["x" * 201])

    def test_the_batch_is_bounded(self):
        with pytest.raises(ValidationError):
            WalkerDaySubmitIn(token="k" * 32, days=[_day() for _ in range(41)])

    def test_a_walker_needs_a_name(self):
        with pytest.raises(ValidationError):
            WalkerDayIn(**_day(walker_name=""))


class TestTheUpsertKey:
    """ADR-417 D5 — one row per walker per date per campaign."""

    def test_the_constraint_is_token_day_walker(self):
        from app.models.collection import CollectedWalkerDay
        uniques = [
            c for c in CollectedWalkerDay.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        ]
        assert len(uniques) == 1
        assert sorted(c.name for c in uniques[0].columns) == [
            "collected_on", "token_id", "walker_name",
        ]

    def test_the_endpoint_upserts_rather_than_appending(self):
        """Pins the behaviour, not the prose: a resubmission must find the
        existing row and bump its revision."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C.submit_walker_days)
        assert "existing.revision" in src, "a resubmission must bump the revision"
        assert "replaced += 1" in src, "an overwrite must be reported as replaced"


class TestTheDayIsAQuarantine:
    """ADR-417 D3 — nothing joins to it, so the PII strip is a DELETE."""

    def test_no_foreign_key_into_the_tenant_model(self):
        """A FK to employees would give referential integrity and make the
        eventual strip a schema change touching live relationships."""
        from app.models.collection import CollectedWalkerDay
        targets = {
            fk.column.table.name
            for c in CollectedWalkerDay.__table__.columns
            for fk in c.foreign_keys
        }
        assert targets == {"collection_tokens"}, (
            f"the quarantine must not reference the tenant model; found {targets}"
        )

    def test_the_payload_is_written_as_json_not_a_python_object(self):
        """A JSONB column handed a Pydantic object stores its repr. The write
        site must call .model_dump()."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C.submit_walker_days)
        assert 'model_dump(mode="json")' in src


class TestTheReadsAreSuperAdminOnly:
    """ADR-417 D3 / ADR-343 D4. These rows carry real coworkers' NAMES, and a
    platform_support login is cross-tenant."""

    @pytest.mark.parametrize("path", [
        "/collection/walker-days",
        "/collection/walker-days/{day_id}",
    ])
    def test_the_gate_never_admits_platform_staff(self, path):
        """ADR-423 widened these from "super admin only" to "super admin OR the
        owning company's admin", so the gate is no longer one dependency — it
        is _scope_reads.

        The invariant that must NOT erode is the other one: a cross-tenant
        `platform_support` login may never reach these rows, which carry real
        coworkers' names (ADR-343 D4). Widening to a principal who already owns
        the data is not the same as widening to one who does not.
        """
        import inspect
        from app.api.deps import get_platform_staff
        from app.routers.collection import router

        route = next(r for r in router.routes
                     if r.path == path and "GET" in r.methods)
        gates = [
            p.default.dependency
            for p in inspect.signature(route.endpoint).parameters.values()
            if getattr(p.default, "dependency", None) is not None
        ]
        assert get_platform_staff not in gates, (
            f"{path} admits platform_support to named field data"
        )
        assert "_scope_reads(" in inspect.getsource(route.endpoint), (
            f"{path} does not scope its read to the caller"
        )

    def test_the_public_day_path_accepts_no_GET(self):
        from app.routers.collection import router
        for r in router.routes:
            if r.path.endswith("/submit-day"):
                assert "GET" not in r.methods, "the public path exposes a read"
