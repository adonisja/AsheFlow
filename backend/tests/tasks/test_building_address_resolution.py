"""ADR-277 D1 — address resolution for typed BuildingProfile submissions.

The failure this prevents is silent: a captain types '433 West 32nd Street',
the manifest says '433 W 32 ST', and routing matches neither. Nothing errors —
the profile just never applies to a stop.

building_profiles.py is proprietary; CI copies it in from AsheFlow-private
before pytest, so there is deliberately NO skip guard (a guard would turn a
failed private pull into silently-passing tests).
"""
import inspect

import pytest

from app.models.building_profile import BuildingProfile


class TestSchema:
    def test_model_has_the_resolution_columns(self):
        cols = BuildingProfile.__table__.columns
        for name, nullable in [
            ("address_status", False),
            ("geo_grc", True),
            ("geo_message", True),
            ("lat", True),
            ("lng", True),
            ("segment_id", True),
        ]:
            col = cols.get(name)
            assert col is not None, f"ADR-277: BuildingProfile.{name} missing"
            assert col.nullable is nullable, f"{name} nullability wrong"

    def test_address_status_defaults_to_pending(self):
        """A row created without an explicit status must be resolvable, not
        silently treated as already-canonical."""
        col = BuildingProfile.__table__.columns["address_status"]
        assert col.server_default is not None
        assert "pending" in str(col.server_default.arg)

    def test_status_and_segment_are_indexed(self):
        """Both are query predicates: routing filters on status, the D3 truck
        page joins on segment_id. An unindexed predicate over a profile table
        that grows per-building is a sequential scan per stop."""
        for name in ("address_status", "segment_id"):
            assert BuildingProfile.__table__.columns[name].index is True, (
                f"{name} must be indexed — it is a predicate, not storage"
            )


class TestResolverRules:
    """The task's decision table, asserted on source.

    The resolver's branches depend on a live GeoClient and a DB session, so
    these pin the RULES rather than mocking a pipeline into existence — the
    mock would encode my assumptions about GeoClient twice and prove neither.
    """

    def _src(self):
        from app.tasks import resolve_building_addresses
        return inspect.getsource(resolve_building_addresses)

    def test_transport_failure_does_not_reject_the_address(self):
        """The trap: `except Exception -> rejected` is the obvious handler and
        it is wrong. A network blip is not the address's fault, and marking it
        rejected tells the captain to fix an address that is correct."""
        src = self._src()
        exc_block = src[src.index("except Exception:"):]
        first_branch = exc_block[: exc_block.index("continue")]
        assert 'address_status = "rejected"' not in first_branch, (
            "a transport failure must leave the row `pending` for the next "
            "sweep, never `rejected`"
        )
        assert "skipped" in first_branch

    def test_missing_segment_is_a_rejection_for_a_building(self):
        """grc 42 is a WARNING for a package (it still gets delivered) but a
        REJECTION for a building profile — a house number that does not exist
        on that street cannot be the building the row describes."""
        src = self._src()
        assert "if not geo.segment_id:" in src
        seg = src[src.index("if not geo.segment_id:"):]
        assert 'address_status = "rejected"' in seg[:400]

    def test_success_rewrites_the_address_and_rederives_block_key(self):
        """block_key is denormalised FROM the address. Rewriting one without
        the other groups the building under its old spelling — the exact
        fragmentation this ADR removes, reintroduced by the fix for it."""
        src = self._src()
        assert "profile.normalised_address = geo.normalised_address" in src
        i = src.index("profile.normalised_address = geo.normalised_address")
        after = src[i : i + 600]
        assert "derive_block_key" in after, "block_key must be re-derived"
        assert "ParsedBlock" in after, "and only applied when the address parses"

    def test_it_is_one_shot_not_a_retry_loop(self):
        """Operator's call: one-shot plus a manual retry from the rejected tag.
        A geocoder that failed on a string fails again on the same string, and
        a silent loop hides the problem from the person who can fix it."""
        src = self._src()
        assert "max_retries" not in src
        assert "self.retry" not in src
        assert 'address_status == "pending"' in src, (
            "the task must claim only pending rows, never re-walk rejected ones"
        )

    def test_borough_is_company_scoped(self):
        """GeoClient needs a borough. Hardcoding manhattan would mis-resolve
        every other tenant's addresses into a plausible-but-wrong building."""
        src = self._src()
        assert "geoclient_borough" in src
        assert "Company" in src

    def test_batch_is_bounded(self):
        src = self._src()
        assert ".limit(" in src, "an unbounded sweep can hold a worker"


class TestSubmitPath:
    """Where the status is decided, and what must not be re-resolved."""

    def _src(self):
        from app.routers import building_profiles
        return inspect.getsource(building_profiles)

    def test_manifest_sourced_addresses_are_not_re_resolved(self):
        """A stop's address came FROM GeoClient. Re-resolving it spends a call
        to confirm GeoClient's own output, and a transport failure mid-way
        could flip a live building to rejected."""
        src = self._src()
        assert 'address_status = "resolved" if body.block_key else "pending"' in src

    def test_typed_addresses_queue_resolution(self):
        src = self._src()
        assert "resolve_pending_addresses.delay()" in src
        i = src.index("resolve_pending_addresses.delay()")
        before = src[max(0, i - 300) : i]
        assert 'address_status == "pending"' in before, (
            "dispatch must be gated on there being something to resolve"
        )

    def test_a_dead_broker_does_not_fail_the_submission(self):
        """The observation is already committed. Losing the dispatch costs a
        10-minute delay (the beat sweep), not the captain's work."""
        src = self._src()
        i = src.index("resolve_pending_addresses.delay()")
        assert "try:" in src[max(0, i - 400) : i]
        assert "except Exception:" in src[i : i + 400]

    def test_the_address_is_not_logged(self):
        """ADR-115 dim 7. block_key is public street geography; the address is
        a customer's doorstep."""
        src = self._src()
        i = src.index("building_profile submitted")
        block = src[i : i + 500]
        assert '"normalised_address": normalised_address' not in block
        assert '"block_key"' in block

    def test_unresolved_addresses_cannot_lock_or_nominate(self):
        """lock is also the nomination gate (ADR-220). Promoting a building
        whose address GeoClient could not match would publish, to every tenant,
        a record that matches no stop."""
        src = self._src()
        assert 'if profile.address_status != "resolved":' in src
        i = src.index('if profile.address_status != "resolved":')
        assert "409" in src[i : i + 300] or "HTTP_409_CONFLICT" in src[i : i + 300]


class TestRTSStubs:
    def test_rts_stubs_are_born_resolved(self):
        """The RTS troublesome-score path creates a stub from the enriched
        manifest's address — already canonical. Marking it pending would queue
        a redundant geocode and expose a live building to a transport-failure
        rejection."""
        from app.services import building_troublesome
        src = inspect.getsource(building_troublesome)
        assert 'address_status="resolved"' in src


class TestTaskIsActuallyRegistered:
    def test_celery_loads_the_module(self):
        """A task the worker never imports is a task that never runs. The
        include list is explicit, not autodiscovered, so a new module is
        invisible until it is added — and nothing else would fail to say so."""
        from app.celery_app import celery_app
        assert "app.tasks.resolve_building_addresses" in celery_app.conf.include

    def test_the_sweep_is_scheduled(self):
        from app.celery_app import celery_app
        assert "resolve-building-addresses" in celery_app.conf.beat_schedule
