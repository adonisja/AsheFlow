"""The interruptive surface has a caller, and it obeys D5/D6/D11 (ADR-494).

WHY A PYTHON TEST FOR TYPESCRIPT
Same reasoning as test_adr289_client_capabilities.py: the web app has no test
runner in CI, and the backend suite is what runs on every push. Parsing files
for structure needs no DOM and no bundler.

WHAT THIS EXISTS TO CATCH
ADR-381's failure: a backend ships, a type is exported, and nothing renders it.
Three features shipped that way in one week, and the worst was live — a field
user's 14-day clock running behind a trigger no client consumed. An interruptive
notification has the same shape: the server can emit `gate` forever and, if
nothing mounts a dialog, the only symptom is that nothing happens.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "frontend" / "src"

HOST = WEB / "components" / "notifications" / "InterruptiveHost.tsx"
DIALOG = WEB / "components" / "notifications" / "InterruptiveDialog.tsx"
GATE = WEB / "components" / "notifications" / "NotificationGate.tsx"
GRAD = WEB / "components" / "notifications" / "GraduationPrompt.tsx"
MODE = WEB / "components" / "notifications" / "OperatingModeChangePrompt.tsx"
LAYOUT = WEB / "components" / "layout" / "Layout.tsx"
CONTEXT = WEB / "contexts" / "NotificationContext.tsx"


def _function_body(src: str, name: str) -> str:
    """The text of one arrow-function const, by brace matching.

    Crude but sufficient, and it buys what a file-wide substring search cannot:
    an assertion about WHERE something appears. Four probes in this pass passed
    against file-wide checks because the needle had a second legitimate home.
    """
    m = re.search(rf"const {name}\s*=\s*useCallback\(|const {name}\s*=", src)
    if not m:
        return ""
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    return src[i:]


def _strip_comments(src: str) -> str:
    """Code only. This suite has recorded more than fifteen false passes where
    an assertion matched an explanatory comment instead of the code it
    describes — including one in THIS pass, where a comment naming
    `from_row_scoped` made a substring assertion pass while the call was wrong.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


class TestTheSurfaceExists:
    @pytest.mark.parametrize("path", [HOST, DIALOG, GATE, GRAD, MODE])
    def test_the_component_file_is_present(self, path):
        assert path.exists(), f"{path.name} is missing — the ADR-494 surface is unbuilt"


class TestItIsActuallyMounted:
    """A component with no caller is the ADR-381 failure."""

    def test_the_host_is_mounted_in_the_layout(self):
        src = _strip_comments(LAYOUT.read_text())
        assert "<InterruptiveHost" in src, (
            "InterruptiveHost is not rendered — the gates and prompts exist and "
            "nothing shows them"
        )
        assert "InterruptiveHost" in src and "import" in src

    def test_the_host_renders_all_three_surfaces(self):
        src = _strip_comments(HOST.read_text())
        for component in ("NotificationGate", "GraduationPrompt",
                          "OperatingModeChangePrompt"):
            assert f"<{component}" in src, (
                f"{component} is imported but never rendered by the host"
            )

    def test_the_host_is_a_sibling_of_the_banner_not_a_child(self):
        """The banner is a capped, scrollable container (ADR-487 D4a).

        A dialog nested inside something that can be scrolled past is not
        interruptive — the same reasoning that put the URGENT region outside
        the cap.
        """
        src = _strip_comments(LAYOUT.read_text())
        assert "<InterruptiveHost" in src
        banner_src = _strip_comments((WEB / "components" / "NotificationBanner.tsx").read_text())
        assert "InterruptiveHost" not in banner_src, (
            "the host moved inside NotificationBanner, which is the 40vh capped "
            "scroll container — an interruptive dialog there can be scrolled away"
        )


class TestTheClientDecidesNothing:
    """ADR-494 D6: the server decides a degradation.

    A client-side expiry check or deadline comparison is the drift D6 exists to
    prevent — two surfaces computing the same rule in two languages, where the
    failure is one walling a user the other lets through.
    """

    @pytest.mark.parametrize("path", [HOST, GATE, GRAD, MODE])
    def test_no_client_side_expiry_logic(self, path):
        src = _strip_comments(path.read_text())
        assert "expires_at" not in src, (
            f"{path.name} reads expires_at — expiry is the SERVER's decision "
            f"(D8 via D6), and a second copy here can disagree with it"
        )

    @pytest.mark.parametrize("path", [HOST, GATE])
    def test_no_client_side_deadline_arithmetic(self, path):
        src = _strip_comments(path.read_text())
        for smell in ("close_deadline", "Date.now()", "86400"):
            assert smell not in src, (
                f"{path.name} computes a deadline ({smell}) — the escalation "
                f"keys on ADPPayPeriod.close_deadline server-side (D3)"
            )

    def test_the_host_switches_on_the_server_channel(self):
        """It must read `channels`, which is the server's answer."""
        src = _strip_comments(HOST.read_text())
        assert "channels.includes('gate')" in src
        assert "channels.includes('prompt')" in src


class TestD5TwoVisuallyDistinctPrompts:
    """*"One parameterised component would make them look alike, and the second
    would read as a promotion nobody earned."*"""

    def test_they_are_separate_files(self):
        assert GRAD.exists() and MODE.exists()
        assert GRAD.read_text() != MODE.read_text()

    def test_the_host_picks_by_type_not_by_a_shared_prop(self):
        src = _strip_comments(HOST.read_text())
        assert "'graduation'" in src
        assert "'operating_mode_change'" in src

    def test_their_header_treatments_differ(self):
        """The headers are each component's visual identity.

        Probed: comparing the full set of palette families passed even after the
        mode prompt's border was changed to the graduation palette, because both
        files legitimately use slate and amber elsewhere (body text, the error
        strip). The HEADER is where the identity lives, so that is what is
        compared.
        """
        grad = _strip_comments(GRAD.read_text())
        mode = _strip_comments(MODE.read_text())
        # The dialog-level className is the outermost visual decision each one
        # makes, and the one a collapsing refactor would unify first.
        def _shell(src: str) -> str:
            m = re.search(r'className="(border-[^"]+)"', src)
            return m.group(1) if m else ""
        assert _shell(grad), "the graduation prompt has no shell palette"
        assert _shell(mode), "the mode prompt has no shell palette"
        assert _shell(grad) != _shell(mode), (
            f"both prompts use the same shell palette ({_shell(grad)!r}) — D5 "
            f"requires them visually distinct, because a mode change is not a "
            f"congratulation"
        )

    def test_their_visual_treatments_differ(self):
        """Not a style audit — a check that the two do not share one palette.

        If a later refactor collapses them into one component with a colour
        prop, this is what notices.
        """
        grad = _strip_comments(GRAD.read_text())
        mode = _strip_comments(MODE.read_text())
        # Semantic token names, not Tailwind palette names: the colour-literal
        # gate (design/check_colour_literals.py) forbids `emerald-500` here, and
        # this test first matched exactly that -- after the token conversion
        # both sets came back EMPTY and compared equal.
        tone = r"\b(?:bg|from|to|text|border|ring)-(success|warning|danger|info|teal|gold|brand)\b"
        grad_colours = set(re.findall(tone, grad))
        mode_colours = set(re.findall(tone, mode))
        assert grad_colours and mode_colours, (
            "a prompt carries no semantic tone at all, so this comparison would "
            "pass on two identical grey dialogs"
        )
        assert grad_colours != mode_colours, (
            f"both prompts use the same palette ({grad_colours}) — D5 requires "
            f"them to be visually distinct, because a mode change is not a "
            f"congratulation"
        )


class TestD11Accessibility:
    """The conditions on claiming the WCAG exception at all."""

    def test_the_dialog_is_a_native_dialog_element(self):
        src = _strip_comments(DIALOG.read_text())
        assert "showModal()" in src, (
            "a hand-rolled overlay leaves background content focusable, so Tab "
            "walks out of the modal — showModal() gives inertness for free"
        )
        assert "<dialog" in src

    def test_it_declares_aria_modal_and_a_label(self):
        src = _strip_comments(DIALOG.read_text())
        assert 'aria-modal="true"' in src
        assert "aria-labelledby" in src

    def test_a_gate_blocks_escape_and_a_prompt_does_not(self):
        """The exception is claimed for GATE ONLY.

        Blocking Escape everywhere would be a plain WCAG violation; allowing it
        on a gate would make the gate decorative. Both halves matter.

        Scoped to the CANCEL handler specifically. The file-wide version of this
        assertion did not fire when probed: `kind === 'gate'` also appears in the
        backdrop-click handler, so deleting the Escape guard left the string
        present and the test green. An existence check cannot see a partial
        removal when the needle has more than one legitimate home.
        """
        src = _strip_comments(DIALOG.read_text())
        cancel = _function_body(src, "handleCancel")
        assert cancel, "handleCancel is gone — nothing handles Escape at all"
        assert "preventDefault" in cancel, (
            "handleCancel does not preventDefault, so Escape closes every "
            "dialog including a gate"
        )
        assert "kind === 'gate'" in cancel, (
            "the Escape block is not conditional on kind — either every dialog "
            "traps the user, or the gate does not hold"
        )
        # And the prompt path must still dismiss.
        assert "onDismiss()" in cancel, (
            "handleCancel never calls onDismiss, so a PROMPT cannot be closed "
            "with Escape either — that is a WCAG violation with no exception"
        )

    def test_focus_returns_to_the_opener(self):
        """Both halves: the opener is captured on open AND restored on close.

        Probed: asserting `activeElement in src` passed with the restore effect
        deleted, because the CAPTURE also mentions activeElement. One string,
        two responsibilities — so each is asserted where it lives.
        """
        src = _strip_comments(DIALOG.read_text())
        assert "opener.current = document.activeElement" in src, (
            "the opener is never captured, so there is nothing to restore to"
        )
        restores = src.count("prev.focus()")
        assert restores >= 2, (
            f"focus is restored in {restores} place(s); both the close handler "
            f"and the unmount cleanup need it — a route change can unmount this "
            f"while open, and then the close handler never runs"
        )

    def test_every_control_meets_the_44px_floor(self):
        """`min-h-11` is 44px in this Tailwind scale. A walker taps these in a van."""
        for path in (GATE, GRAD, MODE):
            src = _strip_comments(path.read_text())
            buttons = src.count("<button")
            floors = src.count("min-h-11")
            assert floors >= buttons, (
                f"{path.name} has {buttons} button(s) and {floors} with the 44px "
                f"floor — D11 requires every touch target to meet it"
            )

    def test_reduced_motion_is_respected(self):
        """The hook must be CALLED and its result must gate the animation.

        Probed: `"useReducedMotion" in src` passed with the call replaced by
        `const reduceMotion = false`, because the import line still matched.
        """
        src = _strip_comments(DIALOG.read_text())
        assert "useReducedMotion()" in src, (
            "the hook is imported but not called — an animation that ignores "
            "prefers-reduced-motion is a bug, not a flourish (CLAUDE.md)"
        )
        assert "reduceMotion ?" in src or "!reduceMotion" in src, (
            "the hook's result is never used to gate the animation"
        )


class TestTheAcknowledgementIsWired:
    def test_the_context_exposes_acknowledge(self):
        src = _strip_comments(CONTEXT.read_text())
        assert "acknowledge" in src
        assert "/acknowledge" in src, "nothing calls the acknowledge endpoint"

    @pytest.mark.parametrize("path", [GATE, GRAD, MODE])
    def test_every_surface_records_a_choice(self, path):
        src = _strip_comments(path.read_text())
        assert "acknowledge(" in src, (
            f"{path.name} dismisses without recording anything — the row is the "
            f"only evidence the person chose, and for timecard_mismatch it is "
            f"what a payroll dispute turns on"
        )

    def test_a_gate_records_unavailable_not_skipped_when_degraded(self):
        """`skipped` would assert a declined choice that was never presented."""
        src = _strip_comments(GATE.read_text())
        assert "'unavailable'" in src
        assert "'skipped'" not in src, (
            "the gate can record 'skipped' — but a gate offers no skip, so that "
            "value would be a false statement about what the person did"
        )

    def test_a_failed_acknowledgement_keeps_the_surface_open(self):
        """Dismissing on failure lets someone through with no record."""
        for path in (GATE, GRAD, MODE):
            src = _strip_comments(path.read_text())
            assert "setFailed(true)" in src, (
                f"{path.name} does not handle a failed acknowledgement — it "
                f"would close having recorded nothing"
            )
