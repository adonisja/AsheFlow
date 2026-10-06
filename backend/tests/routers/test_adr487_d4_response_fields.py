"""The registry reaches the client, on both transports (ADR-487 D4).

WHY THIS NEEDS A TEST AT ALL
============================

Before this, `NotificationResponse` carried `type` and nothing else about
routing, so each client had its own `classify.ts` with ONE hardcoded rule
(`type !== 'dispatch_assignment'`). The registry held severity/label/tone/icon
for all 82 types and no client could see any of it. D4a and D4b both route by
severity, so the contract is the prerequisite.

THE SHAPE THAT MAKES THIS FRAGILE
=================================

Notifications serialise on TWO paths that share no code:

  * REST   `GET /notifications/{id}`  -> NotificationResponse (Pydantic)
  * SSE    `GET /notifications/{id}/stream` -> a hand-built dict for json.dumps

A Pydantic field added to the first does NOT appear in the second. Half-convert
this and the client gets a severity for rows it fetched and no severity for rows
that arrived live — rendering the same notification two different ways
depending on which transport delivered it. That is ADR-487 D9's "check EVERY
write site" lesson, applied to a read.
"""
from __future__ import annotations

import inspect
import json

import pytest

from app.schemas.notification import (
    NotificationResponse,
    _UNKNOWN_FALLBACK,
    spec_fields,
)
from app.services.notification_spec import RETIRED, SPEC, Severity, Tone

_REGISTRY_FIELDS = ("severity", "label", "tone", "icon", "channels")


class TestTheSchemaCarriesTheRegistryFields:
    def test_all_four_are_declared(self):
        for f in _REGISTRY_FIELDS:
            assert f in NotificationResponse.model_fields, f"{f} missing from the response"

    def test_no_colour_is_sent(self):
        """`tone` is a semantic role. A hex value from a Python file would land
        in a native app's dark-mode palette, which is how a "danger"
        notification ends up unreadable on one of the two themes.

        code_only, because the docstring ABOVE the field list explains the rule
        by naming the very tokens it forbids. That is the ninth time in this
        body of work that an absence assertion has matched its own
        explanation — and the pattern is always the same: the better the
        comment, the more likely the test fails.
        """
        from tests.conftest import code_only

        src = code_only(NotificationResponse)
        for forbidden in ("#dc", "#ef4", "rgb(", "c.danger", "bg-danger"):
            assert forbidden not in src, f"the response leaked a colour: {forbidden}"

    def test_the_fields_are_not_columns(self):
        """Resolved per read, so improving a label fixes it everywhere —
        including rows already in the archive."""
        from app.models.notification import Notification
        for f in _REGISTRY_FIELDS:
            assert not hasattr(Notification, f), (
                f"{f} became a column; it must stay resolved at read time or a "
                f"reworded label goes stale on every existing row"
            )


class TestEveryDeclaredTypeResolves:
    @pytest.mark.parametrize("ntype", sorted(SPEC))
    def test_a_declared_type_resolves(self, ntype):
        got = spec_fields(ntype)
        assert set(got) == set(_REGISTRY_FIELDS)
        assert got["severity"] in {s.value for s in Severity}
        assert got["tone"] in {t.value for t in Tone}
        assert got["label"] and got["icon"]

    @pytest.mark.parametrize("ntype", sorted(RETIRED))
    def test_a_retired_type_still_resolves(self, ntype):
        """Removal is two-step: stop raising it, keep its entry. A deleted entry
        would break the read of its historical rows."""
        got = spec_fields(ntype)
        assert got["label"], f"{ntype} is retired but unreadable"


class TestTheTwoTransportsAgree:
    """The defect this exists to prevent: a field on the Pydantic model that the
    hand-built SSE dict does not have."""

    def test_both_paths_use_one_resolver(self):
        """Not "both happen to be right today" — both must CALL the same thing,
        or the next field added to one is missing from the other."""
        import app.routers.notifications as N

        rest = inspect.getsource(N.get_notifications)
        stream = inspect.getsource(N.stream_notifications)
        assert "from_row" in rest, "the REST path must resolve per row"
        assert "spec_fields(" in stream, (
            "the SSE path hand-builds its dict for json.dumps, so it does NOT "
            "inherit the schema's fields — it must call spec_fields explicitly"
        )

    def test_from_row_delegates_rather_than_duplicating(self):
        """from_row calling resolve_spec itself is the half-fix: REST would
        500 on an undeclared legacy row while the stream rendered it fine."""
        src = inspect.getsource(NotificationResponse.from_row)
        assert "spec_fields(" in src
        assert "resolve_spec(" not in src, (
            "from_row must go through spec_fields so both transports share the "
            "same unknown-type fallback"
        )

    def test_the_sse_payload_is_json_serialisable(self):
        """The enums must arrive as strings: json.dumps cannot serialise a
        StrEnum member, and the wire contract is the string either way."""
        payload = {"type": "rts_rejected", **spec_fields("rts_rejected")}
        round_tripped = json.loads(json.dumps(payload))
        assert round_tripped["severity"] == "info"
        assert isinstance(round_tripped["tone"], str)


class TestAnUnknownTypeDegradesInsteadOfRaising:
    """`resolve_spec` REFUSES an undeclared type, which is correct on a WRITE —
    it catches the typo at the call site. On a read it would be a liability.

    The constructor guard was armed on 2026-10-05, so rows written since are all
    declared. Rows written BEFORE carry whatever string their call site passed,
    and one of them inside a 50-row page would raise out of the list
    comprehension and 500 the entire notification list — no notifications at
    all, for a feature a walker uses to find out which truck they are on.
    """

    def test_an_unknown_type_does_not_raise(self):
        got = spec_fields("some_type_from_before_the_registry")
        assert got["severity"] == Severity.INFO.value
        assert got["tone"] == Tone.NEUTRAL.value

    def test_the_raw_type_becomes_the_label(self):
        """Better than "Unknown": it names the thing to go and declare."""
        got = spec_fields("legacy_widget_event")
        assert got["label"] == "legacy_widget_event"

    def test_the_fallback_is_the_quietest_tier(self):
        """An unrecognised row must not claim URGENT and jump the queue above
        a real injury alert."""
        assert _UNKNOWN_FALLBACK["severity"] == Severity.INFO.value
        assert _UNKNOWN_FALLBACK["tone"] == Tone.NEUTRAL.value

    def test_a_declared_type_is_unaffected_by_the_fallback(self):
        """The failure mode of the fallback: swallowing a real resolution and
        rendering everything as a neutral bell."""
        got = spec_fields("incident_critical")
        assert got["severity"] == Severity.URGENT.value
        assert got["label"] != "incident_critical", "the registry label was lost"


class TestChannelsIsSentNotDerived:
    """The ticker set is NOT a function of severity, which is why it is on the wire.

    52 types are INFO and only 20 carry TICKER. The operative rule is about the
    message's SUBJECT:

        INFO about the reader goes to the banner; INFO about a third party or
        about the system goes to the ticker.

    No client can compute that from `severity`. The alternative is a 20-entry
    hardcoded list per client — and ADR-487 D4b's own enumeration is already
    stale (it says 18 of 80; the approved registry has 20 of 82), which is the
    argument for sending it rather than describing it.
    """

    def test_two_info_types_route_differently(self):
        """The pair that makes the point: both INFO, different destinations."""
        system_event = spec_fields("manifest_enrichment")
        about_reader = spec_fields("pto_approved")

        assert system_event["severity"] == about_reader["severity"] == "info"
        assert "ticker" in system_event["channels"]
        assert "ticker" not in about_reader["channels"], (
            "a decision about the reader's own time off must not scroll past"
        )

    def test_channel_names_are_lowercase_strings(self):
        """A Flag is a Python construct; the wire carries strings."""
        got = spec_fields("incident_critical")["channels"]
        assert all(isinstance(c, str) and c == c.lower() for c in got)

    def test_the_list_is_sorted_for_a_stable_response(self):
        """An unordered list makes two identical responses compare unequal in a
        test or a cache key."""
        got = spec_fields("pto_approved")["channels"]
        assert got == sorted(got)

    def test_none_yields_an_empty_list_not_a_none_entry(self):
        """Channel.NONE is zero, so it matches nothing in the iteration."""
        from app.schemas.notification import _channel_names
        from app.services.notification_spec import Channel
        assert _channel_names(Channel.NONE) == []
        assert "none" not in _channel_names(Channel.BANNER | Channel.PUSH)

    def test_an_unknown_type_defaults_to_the_banner_not_the_ticker(self):
        """An unrecognised row must not scroll past unseen when nothing is known
        about whether it matters to the reader."""
        got = spec_fields("some_unregistered_type")
        assert got["channels"] == ["banner"]

    def test_every_declared_type_has_at_least_one_channel(self):
        """A type routing nowhere is a row nothing renders."""
        from app.services.notification_spec import SPEC
        orphans = [t for t in SPEC if not spec_fields(t)["channels"]]
        assert not orphans, f"types that route to no channel: {orphans}"
