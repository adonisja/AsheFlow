"""The registry covers every type the code can raise (ADR-487 D1).

TWO LINES OF ENFORCEMENT, AND THE RUNTIME ONE IS PRIMARY
========================================================

`resolve_spec` refusing an undeclared type is the guarantee. This file is the
fast second line over the LITERAL sites, and it is deliberately not the
mechanism — it cannot see the eleven sites that pass `type=` as a variable:

    type=notif_type
    type=f"rts_{payload.status}"
    type=f"incident_{severity}"

Those are the sites most likely to produce an undeclared type, which is exactly
why a source-walking test must not be trusted alone. A test that passes while
asserting something narrower than it claims is the ADR-464 failure, and the
reason that one is cited here rather than paraphrased.

WHY AST AND NOT GREP
====================

A first count of the write sites used `grep "db.add(Notification("` and reported
80. The AST count is 83, and the three it missed include `walker_routes.py:1040`
— a `db.add_all([Notification(...) for ...])` comprehension which turns out to
have no `type=` at all. A gate written on that grep would have been blind to
exactly the worst site.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from app.services.notification_spec import (
    RETIRED,
    SPEC,
    Channel,
    Severity,
    UndeclaredNotificationType,
    is_raisable,
    resolve_spec,
)

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# A `type=` string that is NOT a notification type. Each needs a reason, because
# an exemption with no reason is how a registry goes stale behind a passing test.
NOT_NOTIFICATION_TYPES: dict[str, str] = {
    # Produced by f-string generators whose closed sets ARE declared, but whose
    # literal prefix appears in source. The generated members are in SPEC.
}


def _literal_types_in_source() -> set[str]:
    """Every `Notification(type="...")` literal, by AST."""
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func.id if isinstance(node.func, ast.Name) else None
            # Post-migration the types live on the helper calls. `Notification`
            # stays in the list because the constructor guard is a flag, not a
            # deletion — a future migration could legitimately disarm it.
            if fn not in ("Notification", "write_notification", "fan_out"):
                continue
            for kw in node.keywords:
                if kw.arg == "type" and isinstance(kw.value, ast.Constant):
                    found.add(kw.value.value)
    return found


def _dynamic_type_sites() -> list[str]:
    """Sites passing `type=` as anything other than a literal.

    Counts BOTH call forms. A first version looked only for `Notification(`,
    and the D2 migration then made it fail — not because dynamic sites went
    away, but because they moved to `write_notification(`. The property this
    test protects is "there exist types a source walk cannot resolve", which is
    independent of which function receives them.
    """
    sites: list[str] = []
    for path in APP.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func.id if isinstance(node.func, ast.Name) else None
            if fn not in ("Notification", "write_notification", "fan_out"):
                continue
            for kw in node.keywords:
                if kw.arg == "type" and not isinstance(kw.value, ast.Constant):
                    sites.append(f"{path.relative_to(APP)}:{kw.value.lineno}")
    return sites


class TestTheRegistryIsComplete:
    def test_every_literal_type_is_declared(self):
        """Walk the SOURCE and require each type registered or exempted.

        The inverse — iterating SPEC and checking each entry is used — passes
        forever while new types accumulate unregistered (ADR-464 found 15
        leaking columns under exactly that shape of passing test).
        """
        raised = _literal_types_in_source()
        missing = raised - set(SPEC) - set(RETIRED) - set(NOT_NOTIFICATION_TYPES)
        assert not missing, (
            f"{len(missing)} notification type(s) raised in app/ but not declared "
            f"in notification_spec.SPEC: {sorted(missing)}. Add each with a "
            f"severity, channels, label, tone and icon — or add it to "
            f"NOT_NOTIFICATION_TYPES with a reason if it is not a notification."
        )

    def test_the_source_walk_actually_found_something(self):
        """A walk that finds nothing passes the test above vacuously.

        This is the guard the ADR-464 lesson asks for: assert the derivation is
        non-empty, so a refactor that moves or renames `Notification` turns the
        completeness test into a silent no-op instead of a failure.
        """
        # The D2 migration is COMPLETE, so there are no
        # `Notification(type="...")` literals left in app/ — every site now
        # passes the type to write_notification() or fan_out(). The walk
        # therefore counts those, which is where the types live now.
        #
        # This assertion has been re-pointed twice as the migration proceeded
        # (61 literals -> a ratcheting floor -> helper call sites). Each time the
        # PROPERTY was the same: a walk that finds nothing makes the
        # completeness test above pass vacuously. Only the place the types live
        # changed.
        raised = _literal_types_in_source()
        assert len(raised) >= 55, (
            f"only {len(raised)} literal notification types found by AST — the "
            f"walk is probably broken, which would make the completeness test "
            f"above pass while checking nothing"
        )

    def test_dynamic_sites_exist_and_are_why_runtime_enforcement_is_primary(self):
        """The eleven variable-typed sites this test cannot see.

        Asserted rather than commented, so the claim in the module docstring
        stays true: if these ever reach zero, the static test becomes sufficient
        and this file's framing should change.
        """
        sites = _dynamic_type_sites()
        assert sites, "no dynamic type= sites found — the AST walk may be broken"
        assert len(sites) >= 8, (
            f"only {len(sites)} dynamic sites found; expected ~11. If they were "
            f"genuinely removed, update this test and the module docstring."
        )


class TestResolveSpecRefuses:
    def test_an_undeclared_type_raises(self):
        with pytest.raises(UndeclaredNotificationType) as exc:
            resolve_spec("totally_made_up_type")
        # The message must name the fix, not just the failure.
        assert "notification_spec.SPEC" in str(exc.value)
        assert "ADR-487" in str(exc.value)

    def test_it_does_not_default_to_info(self):
        """The whole point. A lenient lookup reproduces today's behaviour."""
        with pytest.raises(UndeclaredNotificationType):
            resolve_spec("unknown")

    def test_a_retired_type_still_resolves(self):
        """Historical rows must still read after their type stops being raised."""
        spec = resolve_spec("rts_revised")
        assert spec.label == "RTS Revised"

    def test_a_retired_type_is_not_raisable(self):
        assert is_raisable("dispatch_assignment") is True
        assert is_raisable("rts_revised") is False
        assert is_raisable("incident_critical_injury") is False


class TestTheInvariantsTheRegistryExistsForFootnote:
    def test_urgent_and_action_never_enter_the_ticker(self):
        """D4: a message needing an answer must not scroll out of view, and one
        reporting an injury must not be in a strip at all."""
        offenders = [
            t for t, s in SPEC.items()
            if s.severity in (Severity.URGENT, Severity.ACTION)
            and Channel.TICKER in s.channels
        ]
        assert not offenders, f"URGENT/ACTION types in the ticker: {offenders}"

    def test_notice_is_never_pushed(self):
        """D4c: a daily 'remember to sign out' push is how somebody disables
        push for everything, URGENT included."""
        offenders = [
            t for t, s in SPEC.items()
            if s.severity is Severity.NOTICE and Channel.PUSH in s.channels
        ]
        assert not offenders, f"NOTICE types carrying PUSH: {offenders}"

    def test_every_pushed_type_also_mirrors_to_discord(self):
        """The operator's call: Discord is the surface crews actually watch."""
        offenders = [
            t for t, s in SPEC.items()
            if Channel.PUSH in s.channels and Channel.DISCORD not in s.channels
        ]
        assert not offenders, (
            f"types pushed but not mirrored to Discord: {offenders}")

    def test_no_entry_is_channel_less(self):
        """INBOX is implied, so NONE would mean 'archive only' — which is a
        decision no entry currently makes. If one should, say so explicitly."""
        offenders = [t for t, s in SPEC.items() if s.channels is Channel.NONE]
        assert not offenders, f"entries with no channel: {offenders}"

    def test_every_entry_has_a_label_and_an_icon(self):
        """The label is what mobile renders as a title and what the gallery of
        78 types is scanned by. An empty one is a row nobody can identify."""
        bad = [t for t, s in SPEC.items() if not s.label.strip() or not s.icon]
        assert not bad, f"entries missing a label or icon: {bad}"

    def test_no_two_types_share_a_label(self):
        """A label is what mobile renders as the card title, so two types with
        the same label are indistinguishable to the reader.

        Found by reading the generated table rather than the rows: three pairs
        collided, and all three were pairs this ADR had just SPLIT on purpose —
        training_record_due/unsubmitted, quiz_submitted/quiz_submitted_trainer,
        graduation/trainee_graduated. An identical label undoes a split at
        exactly the point somebody sees it, which is why routing and labelling
        cannot be reviewed separately.
        """
        from collections import defaultdict

        by_label: dict[str, list[str]] = defaultdict(list)
        for ty, spec in SPEC.items():
            by_label[spec.label].append(ty)
        collisions = {lbl: ts for lbl, ts in by_label.items() if len(ts) > 1}
        assert not collisions, (
            f"types sharing a label: {collisions}. Each label is a card title; "
            f"two types with one label read as the same notification."
        )

    def test_labels_are_short_noun_phrases(self):
        """Mobile shows the label as a one-line title above the message. A
        sentence there wraps and pushes the message itself off the card."""
        too_long = {t: s.label for t, s in SPEC.items() if len(s.label) > 24}
        assert not too_long, f"labels over 24 chars: {too_long}"


class TestTheCountsMatchTheApprovedRegistry:
    """Pins what was approved after four review passes, so a later edit that
    changes the shape of the registry has to be deliberate.

    AMENDED 2026-10-05 (ADR-487 D4): 82 -> 85 entries, action 26 -> 29.

    The three additions are a CORRECTION, not a change to what was approved.
    `discord_integration_failed`, `email_delivery_failed` and
    `identity_revocation_failed` were already being raised as notifications and
    were missing from the registry, so `_resolve_raisable` refused all three and
    the `except Exception` in `alert_admins_integration_down` swallowed the
    refusal — an integration outage notified nobody and left one log line.

    They escaped the four review passes for a structural reason: the type comes
    from a KEYWORD-ONLY DEFAULT (`notif_type: str = DISCORD_INTEGRATION_FAILED`)
    and every call site takes the default, so the literal appears nowhere that a
    walk over `type=` keyword constants would find it. See
    tests/services/test_adr487_integration_alert_types.py, which enumerates what
    can reach write_notification rather than trusting the registry to be
    complete.
    """

    def test_entry_count(self):
        assert len(SPEC) == 85
        assert len(RETIRED) == 4

    def test_severity_distribution(self):
        counts: dict[str, int] = {}
        for s in SPEC.values():
            counts[s.severity.value] = counts.get(s.severity.value, 0) + 1
        # +3 action: each of the three names something an admin must do by hand.
        assert counts == {"urgent": 4, "action": 29, "info": 52}, counts

    def test_the_four_urgent_types_are_the_approved_ones(self):
        urgent = {t for t, s in SPEC.items() if s.severity is Severity.URGENT}
        assert urgent == {
            "incident_critical",
            "trainee_help_request",
            "driver_help_requested",
            "rebalance_intervention_required",
        }, urgent
