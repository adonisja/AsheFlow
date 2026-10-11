"""Mobile can reach every action route, or says it cannot (ADR-494).

WHY A PYTHON TEST FOR TYPESCRIPT
The mobile app has no test runner in CI and the backend suite is what runs on
every push (same reasoning as test_adr289_client_capabilities.py). Parsing files
for structure needs no Metro and no simulator.

THE PROPERTY THAT MATTERS MOST
`SPEC.actions[].route` is a web path. Mobile navigates by TAB KEY and has no
linking config, so every route needs a translation — and a route with no
translation is a button that goes nowhere, which for a GATE is a wall with no
exit.

So this walks SPEC (the thing that grows) and requires every action route to be
either mapped or EXPLICITLY declared unmapped. That direction is the point:
walking the map and checking each entry resolves would pass forever while SPEC
accumulated routes mobile silently could not reach (the ADR-499 lesson).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.notification_spec import SPEC, Channel

ROOT = Path(__file__).resolve().parents[3]
MOBILE = ROOT / "mobile" / "src"

ROUTES = MOBILE / "navigation" / "actionRoutes.ts"
HOST = MOBILE / "components" / "notifications" / "InterruptiveHost.tsx"
SHEET = MOBILE / "components" / "notifications" / "InterruptiveSheet.tsx"
GATE = MOBILE / "components" / "notifications" / "NotificationGate.tsx"
GRAD = MOBILE / "components" / "notifications" / "GraduationPrompt.tsx"
MODE = MOBILE / "components" / "notifications" / "OperatingModeChangePrompt.tsx"
ACK = MOBILE / "components" / "notifications" / "useAcknowledge.ts"
SCREEN = MOBILE / "screens" / "MyRole" / "MyRoleScreen.tsx"
NAV = MOBILE / "navigation" / "index.tsx"
GATES = MOBILE / "navigation" / "roles.ts"


def _code(path: Path) -> str:
    """Comments stripped. This repo has recorded 17 false passes where an
    assertion matched an explanatory comment instead of the code."""
    src = path.read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


#: PROMPT types with no mobile component, exempted ONLY because nothing raises
#: them. `route_ready` appears on exactly one line in the whole repo — its own
#: registry entry (ADR-494 D8 finding, recorded not retired: retiring asserts a
#: past it does not have). Building a sheet for a notification nothing sends
#: would be a surface with no caller, which is the ADR-381 failure inverted.
#:
#: `test_the_exemptions_are_still_unraised` re-derives the justification from
#: the call sites on every run, so this cannot quietly become a real gap.
NO_SURFACE_YET: set[str] = {"route_ready"}


def _action_routes() -> set[str]:
    return {a.route for s in SPEC.values() for a in s.actions}


class TestEveryActionRouteIsAccountedFor:
    """The completeness test, walking SPEC rather than the map."""

    @pytest.mark.parametrize("route", sorted(_action_routes()))
    def test_the_route_is_mapped_or_declared_unmapped(self, route):
        src = _code(ROUTES)
        # Either it appears as a key in the map / the mode-dependent branch, or
        # it is listed in DELIBERATELY_UNMAPPED. Absent from all three means a
        # notification action that silently does nothing on mobile.
        assert f"'{route}'" in src, (
            f"{route} has no mobile mapping and is not in DELIBERATELY_UNMAPPED. "
            f"A notification action pointing here renders no button on mobile, "
            f"and nothing reports it. Map it, or declare it unmapped with the reason."
        )

    def test_unmapped_is_an_explicit_set_not_an_omission(self):
        """The distinction between 'decided' and 'forgotten'."""
        src = _code(ROUTES)
        assert "DELIBERATELY_UNMAPPED" in src
        assert "'/dispatch'" in src, (
            "/dispatch was removed from DELIBERATELY_UNMAPPED — if it gained a "
            "mobile surface that is fine, but it must then be in the map"
        )

    def test_my_route_is_mode_dependent(self):
        """`/my-route` resolves to two different tabs by operating mode.

        MyRoute is gated on feature 'route_sort' (full) and WorkforceRoute on
        'workforce_sort' (workforce). A static map would pick one and send half
        the tenants to a tab that is not rendered for them — ADR-305's
        divergence as a dead link.
        """
        src = _code(ROUTES)
        assert "workforce_sort" in src and "route_sort" in src
        assert "WorkforceRoute" in src and "MyRoute" in src

    def test_every_mapped_target_is_a_real_tab(self):
        """A tab key that is not in ALL_TABS switches to nothing.

        `switchTab` sets state unconditionally; MainShell then finds no matching
        tab and falls back to Home. The person taps "See what changed" and lands
        on the home screen, which reads as a broken button.
        """
        routes_src = _code(ROUTES)
        nav_src = _code(NAV)
        declared = set(re.findall(r"key: '([A-Za-z]+)'", nav_src))
        # Targets are the quoted values on the right of a map entry, plus the
        # two mode-dependent returns.
        targets = set(re.findall(r":\s*'([A-Z][A-Za-z]+)'", routes_src))
        targets |= set(re.findall(r"return '([A-Z][A-Za-z]+)'", routes_src))
        unknown = targets - declared
        assert unknown == set(), (
            f"mapped to tab key(s) that do not exist in ALL_TABS: {unknown}. "
            f"switchTab would set state nothing matches and the shell falls back "
            f"to Home."
        )


class TestTheMyRoleTabExists:
    """The destination of both /my-role prompts."""

    def test_the_screen_file_exists(self):
        assert SCREEN.exists(), "MyRoleScreen is missing; both prompts link to it"

    def test_the_tab_is_registered(self):
        nav = _code(NAV)
        assert "key: 'MyRole'" in nav
        assert "MyRoleScreen" in nav

    def test_the_tab_is_open_to_every_role(self):
        """`roles: []` = everyone. A role list here would 403 whoever it omits,
        and role_change/graduation send exactly those people here."""
        gates = _code(GATES)
        m = re.search(r"MyRole:\s*\{([^}]*)\}", gates)
        assert m, "MyRole has no TAB_GATES entry"
        assert "roles: []" in m.group(1), (
            f"MyRole's gate is {m.group(1)!r} — a role list excludes someone a "
            f"notification just sent here"
        )

    def test_the_tab_is_not_mode_gated(self):
        """A `feature:` gate would hide the destination of the notification
        that announces a mode switch."""
        gates = _code(GATES)
        m = re.search(r"MyRole:\s*\{([^}]*)\}", gates)
        assert "feature" not in m.group(1), (
            "MyRole is capability-gated — operating_mode_change links here, so "
            "gating it on a capability hides the explanation of the switch"
        )


class TestTheSurfaceIsMounted:
    """ADR-381: a component with no caller ships as done and does nothing."""

    def test_the_host_is_mounted_in_mainshell(self):
        nav = _code(NAV)
        assert "<InterruptiveHost" in nav, (
            "InterruptiveHost is not rendered — the gate and prompts exist and "
            "nothing shows them"
        )

    def test_it_is_mounted_beside_the_mfa_prompt(self):
        """MainShell mounts once per session, so the sheet appears once per
        launch rather than on every tab change — matching MfaGracePrompt."""
        nav = _code(NAV)
        assert "<MfaGracePrompt" in nav and "<InterruptiveHost" in nav

    def test_the_host_renders_all_three_surfaces(self):
        src = _code(HOST)
        for component in ("NotificationGate", "GraduationPrompt",
                          "OperatingModeChangePrompt"):
            assert f"<{component}" in src, f"{component} is imported but never rendered"


class TestTheClientDecidesNothingTheServerDecided:
    """ADR-494 D6. The whole point of server-side degradation is that neither
    client implements a downgrade rule, so they cannot disagree about one."""

    @pytest.mark.parametrize("path", [HOST, GATE, GRAD, MODE])
    def test_no_client_side_expiry_logic(self, path):
        src = _code(path)
        assert "expires_at" not in src, (
            f"{path.name} reads expires_at — expiry is the server's decision "
            f"(D8 via D6), and a second copy here can disagree with web"
        )

    @pytest.mark.parametrize("path", [HOST, GATE])
    def test_no_client_side_deadline_arithmetic(self, path):
        src = _code(path)
        for smell in ("close_deadline", "Date.now()", "86400"):
            assert smell not in src, f"{path.name} computes a deadline ({smell})"

    def test_the_host_switches_on_the_server_channel(self):
        src = _code(HOST)
        assert "channels.includes('gate')" in src
        assert "channels.includes('prompt')" in src


class TestD5TwoVisuallyDistinctPrompts:
    def test_they_are_separate_files(self):
        assert GRAD.exists() and MODE.exists()
        assert GRAD.read_text() != MODE.read_text()

    def test_the_host_picks_by_type(self):
        src = _code(HOST)
        assert "'graduation'" in src and "'operating_mode_change'" in src

    def test_their_accent_palettes_differ(self):
        """Each component's ACCENT tokens are its visual identity.

        Two earlier versions of this assertion passed against a deliberately
        unified palette, and both failures are worth recording:

        1. Comparing every `c.X` in the file -- both legitimately use
           `foreground`, `surfaceMuted` and `warningLight` (the error strip), so
           the sets differed for unrelated reasons.
        2. Comparing "the first header-ish style block" -- the regex matched
           `band` in one file and `headerRow` in the other, so it compared two
           unrelated blocks and passed by accident.

        So this compares the SEMANTIC ACCENT tokens only. Those carry "this is a
        celebration" versus "this is a change you did not ask for", and a
        refactor collapsing the two components would unify exactly them.
        """
        ACCENTS = {
            "success", "successLight", "danger", "dangerLight",
            "warning", "warningLight", "info", "infoLight",
            "gold", "goldLight", "brand", "brandLight",
        }

        def accents(path: Path) -> set[str]:
            return set(re.findall(r"c\.(\w+)", _code(path))) & ACCENTS

        # The FAMILY, not the token. `warningLight` is shared legitimately --
        # both sheets render the same "we couldn't record that" strip -- so
        # comparing raw token sets passed even when one sheet's identity colour
        # was swapped to the other's. Reduced to families and with the shared
        # error accent removed, the comparison is about identity again.
        SHARED_ERROR = {"warning", "warningLight"}

        def families(path: Path) -> set[str]:
            """Accent FAMILIES, with the shared error accent removed.

            The subtraction is the load-bearing part and I got it wrong once:
            SHARED_ERROR was defined and never applied, so graduation scored
            {success, warning} purely because of its error strip. That made it
            unequal to a mutated mode prompt scoring {success} — the sets
            differed for a reason that had nothing to do with identity, and the
            probe passed while both sheets rendered green.
            """
            toks = {t.replace("Light", "") for t in accents(path)}
            return toks - SHARED_ERROR

        grad, mode, gate = families(GRAD), families(MODE), families(GATE)
        assert grad and mode, (
            "neither prompt has an accent of its own beyond the shared error "
            "strip, so nothing distinguishes them"
        )
        assert grad != mode, (
            f"both prompts use the same accent families (grad={grad}, "
            f"mode={mode}) -- D5 requires them visually distinct, because a mode "
            f"change is not a congratulation and must not look like one"
        )
        # And the gate must not look like either prompt: it is the only surface
        # with no way out, so it must not be mistaken for one that has.
        assert gate != grad and gate != mode, (
            f"the gate shares an accent family with a prompt (gate={gate}) -- a "
            f"wall must not look like a sheet the reader can dismiss"
        )

    def test_they_share_the_acknowledgement_call(self):
        """D5 requires them to LOOK different, not to POST differently.

        Three copies of the request is how one ends up sending
        shown_as: 'prompt' from a gate.
        """
        assert ACK.exists()
        for p in (GATE, GRAD, MODE):
            assert "useAcknowledge" in _code(p), f"{p.name} does not use the shared hook"


class TestD11Accessibility:
    def test_the_back_button_is_the_escape_analogue(self):
        """Web blocks Escape on a GATE; mobile must block the Android hardware
        back button, which RN delivers as Modal.onRequestClose.

        Scoped to the onRequestClose EXPRESSION. The file-wide version did not
        fire when probed: `kind === 'gate'` also appears in the announcement
        logic, so an `or` across both spellings matched there while the handler
        unconditionally dismissed. One needle, two legitimate homes.
        """
        src = _code(SHEET)
        m = re.search(r"onRequestClose=\{([^}]*(?:\}[^}]*)?)\}", src)
        assert m, "onRequestClose is gone — nothing handles the back button"
        handler = m.group(1)
        assert "kind" in handler, (
            f"onRequestClose is not conditional on kind ({handler!r}) — either "
            f"every sheet traps the user, or the gate does not hold"
        )
        assert "onDismiss" in handler, (
            f"onRequestClose never dismisses ({handler!r}) — a PROMPT cannot be "
            f"closed with the back button either, which is a WCAG violation "
            f"with no exception to claim"
        )

    def test_the_sheet_is_modal_to_assistive_tech(self):
        """`accessibilityViewIsModal` is RN's equivalent of showModal()'s
        inertness: everything behind the sheet is hidden from the screen reader.

        It must be on the Modal AND the inner sheet View — both, because iOS
        honours it on the modal and the nested flag is what keeps the backdrop
        itself out of the accessibility tree. Counted rather than existence-
        checked: the probe showed removing one left the other matching.
        """
        src = _code(SHEET)
        n = src.count("accessibilityViewIsModal")
        assert n >= 2, (
            f"accessibilityViewIsModal appears {n} time(s); it belongs on the "
            f"Modal and on the sheet View, or content behind the sheet stays in "
            f"the accessibility tree"
        )

    def test_it_announces_itself(self):
        """A sheet that appears silently is one a screen reader user does not
        know has taken over the screen."""
        assert "announceForAccessibility" in _code(SHEET)

    def test_reduced_motion_is_respected(self):
        src = _code(SHEET)
        assert "useReducedMotionState()" in src, (
            "the hook is imported but not called — an animation that ignores "
            "reduced motion is a bug, not a flourish (CLAUDE.md)"
        )
        assert "reduceMotion ?" in src, "the result is never used"

    @pytest.mark.parametrize("path", [GATE, GRAD, MODE])
    def test_every_control_meets_the_44pt_floor(self, path):
        """MIN_TARGET is 44 in primitives. A walker taps these wearing gloves."""
        src = _code(path)
        buttons = src.count("<TouchableOpacity")
        floors = src.count("MIN_TARGET")
        assert floors >= buttons, (
            f"{path.name} has {buttons} control(s) and {floors} MIN_TARGET "
            f"reference(s) — D11 requires every touch target to meet the floor"
        )

    @pytest.mark.parametrize("path", [GATE, GRAD, MODE])
    def test_controls_declare_a_button_role(self, path):
        src = _code(path)
        assert "accessibilityRole=\"button\"" in src, (
            f"{path.name}'s controls have no accessibilityRole — a screen reader "
            f"announces them as plain text"
        )


class TestHapticsOnConfirm:
    """CLAUDE.md: haptics on confirm/reject — a walker in a van feels it
    without looking."""

    @pytest.mark.parametrize("path", [GATE, GRAD, MODE])
    def test_confirm_ticks(self, path):
        assert "tick()" in _code(path), f"{path.name} confirms with no haptic"


class TestTheGateCannotBeAnsweredFalsely:
    def test_a_degraded_gate_records_unavailable(self):
        """`skipped` would assert a declined choice that was never presented.

        Mobile has a degradation case web does not: the server cannot know that
        this client has no screen for a route, so a gate can arrive with an
        action mobile cannot reach.
        """
        src = _code(GATE)
        assert "'unavailable'" in src
        assert "'skipped'" not in src, (
            "the gate can record 'skipped' — a gate offers no skip, so that "
            "value would be a false statement about what the person did"
        )

    def test_a_failed_acknowledgement_keeps_the_sheet_open(self):
        for path in (GATE, GRAD, MODE):
            src = _code(path)
            assert "if (!ok) return;" in src, (
                f"{path.name} proceeds after a failed acknowledgement — the "
                f"person gets through with no record of what they chose"
            )

    def test_the_button_is_hidden_when_there_is_no_destination(self):
        """A button that navigates nowhere is the dismiss-only control D1
        removes; for a gate it is a wall with no exit."""
        for path in (GRAD, MODE):
            assert "&& onNavigate" in _code(path), (
                f"{path.name} renders its action without checking onNavigate"
            )
        assert "!onNavigate" in _code(GATE), (
            "the gate does not check onNavigate, so it can render a primary "
            "button that goes nowhere"
        )


class TestTheInterruptiveChannelsAreCovered:
    """Every type the server can send interruptively has a mobile surface."""

    def test_every_gate_or_prompt_type_is_handled(self):
        host = _code(HOST)
        interruptive = {
            t for t, s in SPEC.items()
            if Channel.GATE in s.channels or Channel.PROMPT in s.channels
        }
        # A GATE is handled generically; PROMPTs are per-type by D5.
        gates = {t for t in interruptive if Channel.GATE in SPEC[t].channels}
        prompts = interruptive - gates

        assert gates, "no type carries GATE — the registry changed"
        unhandled = {t for t in prompts if f"'{t}'" not in host} - NO_SURFACE_YET
        assert unhandled == set(), (
            f"PROMPT type(s) with no mobile component: {unhandled}. They fall to "
            f"the host's default branch and do not interrupt — which is a safe "
            f"failure, but it must be a DECISION, so add the component or add it "
            f"to NO_SURFACE_YET with the reason."
        )

    def test_the_exemptions_are_still_unraised(self):
        """An exemption list that nobody re-checks is where a real gap hides.

        NO_SURFACE_YET is justified ONLY by the type having no raiser. The
        moment something raises it, a person receives a PROMPT that interrupts
        nobody — so this walks the call sites and fails if an exempted type
        became raisable.
        """
        import ast as _ast
        import pathlib as _pl

        raised: set[str] = set()
        for f in _pl.Path("app").rglob("*.py"):
            try:
                tree = _ast.parse(f.read_text())
            except Exception:
                continue
            for n in _ast.walk(tree):
                if not (isinstance(n, _ast.Call)
                        and isinstance(n.func, (_ast.Name, _ast.Attribute))):
                    continue
                fn = n.func.id if isinstance(n.func, _ast.Name) else n.func.attr
                if fn not in ("write_notification", "fan_out"):
                    continue
                for kw in n.keywords:
                    if kw.arg == "type" and isinstance(kw.value, _ast.Constant):
                        raised.add(kw.value.value)

        now_raised = NO_SURFACE_YET & raised
        assert now_raised == set(), (
            f"{now_raised} is exempted from needing a mobile surface because "
            f"nothing raised it — but something does now. Either build the "
            f"component or stop raising it; an interruptive type that cannot "
            f"interrupt is a message nobody receives."
        )
