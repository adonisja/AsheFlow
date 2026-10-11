"""ADR-494 D3/D6/D8 — when a GATE stops being a gate.

These are unit tests over `degrade_channels` with stub rows, not DB tests. The
function's whole job is a decision about a channel list, and the decision is what
is worth pinning; the queries it makes are covered by the router tests.

Why a stub row rather than a real `Notification`: the inputs that matter are
`type`, `expires_at`, `company_id` and `employee_id`, and a stub makes the
timezone cases (naive vs aware `expires_at`) expressible without writing rows
that the SQLite mirror would strip tzinfo from anyway -- which is the bug the
`replace(tzinfo=utc)` guard exists for.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.notification_degrade import (
    _types_needing_role_guide,
    degrade_channels,
)


def _db_where_everything_checks_out():
    """A stub session for which every non-expiry gate check succeeds.

    Needed so an expiry test cannot pass via the no-session fallback. Returns a
    truthy first() for the role-guide existence probe, which is the only query
    the /my-role-dependent path makes.
    """
    class _Q:
        def filter(self, *a, **k): return self
        def first(self): return ("row-exists",)
        def join(self, *a, **k): return self
        def order_by(self, *a, **k): return self

    class _DB:
        def query(self, *a, **k): return _Q()

    return _DB()


def _row(**kw):
    base = dict(
        id=uuid.uuid4(),
        type="credentials_sent",
        expires_at=None,
        company_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestItOnlyEverRemovesAGate:
    """The invariant that makes this module readable: it never ADDS a gate.

    If it could, the complete set of ways a gate reaches a client would be "the
    registry, plus whatever this function decides", and nobody could answer
    "why am I being walled" by reading SPEC.
    """

    @pytest.mark.parametrize("channels", [
        ["banner"],
        ["banner", "prompt"],
        ["ticker"],
        ["banner", "push", "discord"],
        [],
    ])
    def test_a_non_gate_list_is_returned_untouched(self, channels):
        out = degrade_channels(None, _row(), list(channels))
        assert out == channels
        assert "gate" not in out

    def test_it_never_introduces_a_gate(self):
        for ch in (["banner"], ["prompt"], ["ticker", "banner"], []):
            assert "gate" not in degrade_channels(None, _row(), list(ch))


class TestExpiry:
    """D8 — an expired gate does not block.

    No query needed, so this is the one check that survives `db=None`.
    """

    def test_an_expired_gate_becomes_a_prompt(self):
        """Pass a session, so this tests EXPIRY and not the no-session fallback.

        Probed: with `db=None` this test passes even when the expiry branch is
        disabled entirely, because execution falls through to the
        "cannot verify without a session" degradation and reaches the same
        answer by the wrong route. A stub db that answers "yes, role guides
        exist" removes that second path, so the only thing that can degrade
        this row is its expiry.
        """
        row = _row(
            type="graduation",   # a type whose gate depends on a /my-role row
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        out = degrade_channels(_db_where_everything_checks_out(), row, ["banner", "gate"])
        assert "gate" not in out
        assert "prompt" in out

    def test_an_unexpired_gate_still_needs_a_session(self):
        """Not expired, but unverifiable without a db -> still degrades.

        Failing SAFE is the point: the alternative is walling someone on the
        strength of a check that never ran.
        """
        row = _row(expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        out = degrade_channels(None, row, ["banner", "gate"])
        assert "gate" not in out and "prompt" in out

    def test_a_naive_expires_at_is_treated_as_utc(self):
        """The SQLite mirror drops tzinfo, so a naive value must not raise.

        A naive/aware comparison is a TypeError inside a read of fifty rows --
        it would 500 the whole notification list, which is the failure mode
        `_resolve_for_read` was already written to avoid for unknown types.
        """
        # A NAIVE datetime on purpose -- constructed by stripping tzinfo rather
        # than with the deprecated utcnow(), because the point is the shape of
        # the value the SQLite mirror hands back, not how it was made.
        naive = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
        row = _row(expires_at=naive)
        out = degrade_channels(None, row, ["banner", "gate"])
        assert "gate" not in out

    def test_expiry_wins_over_everything(self):
        """An expired gate degrades without any query at all.

        Passing a db that would raise proves the expiry branch returns first.
        """
        class Exploding:
            def query(self, *a, **k):
                raise AssertionError("expiry must short-circuit before any query")

        row = _row(type="timecard_mismatch",
                   expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        out = degrade_channels(Exploding(), row, ["banner", "gate"])
        assert "gate" not in out


class TestTheRoleGuideDependencyIsDerived:
    """The set of types needing a /my-role row comes from SPEC, not a list."""

    def test_it_matches_the_registry(self):
        from app.services.notification_spec import SPEC

        expected = {
            t for t, s in SPEC.items()
            if any(a.route == "/my-role" for a in s.actions)
        }
        assert _types_needing_role_guide() == expected

    def test_the_two_my_role_types_are_in_it(self):
        found = _types_needing_role_guide()
        assert "graduation" in found
        assert "operating_mode_change" in found

    def test_a_type_with_no_action_is_not_in_it(self):
        assert "credentials_sent" not in _types_needing_role_guide()


class TestOutputShape:
    """A degraded list must stay a valid, stable channel list."""

    def test_the_result_is_sorted_so_two_reads_compare_equal(self):
        row = _row(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        out = degrade_channels(None, row, ["push", "banner", "gate"])
        assert out == sorted(out), "an unordered list breaks cache keys and tests"

    def test_prompt_is_not_duplicated_when_already_present(self):
        row = _row(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        out = degrade_channels(None, row, ["banner", "gate", "prompt"])
        assert out.count("prompt") == 1

    def test_the_other_channels_survive(self):
        """Degrading the gate must not drop push or discord.

        A half-fix here is silent: the reader gets their prompt and never gets
        the push that would have told them to open the app at all.
        """
        row = _row(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        out = degrade_channels(None, row, ["banner", "push", "discord", "gate"])
        assert set(out) == {"banner", "push", "discord", "prompt"}
