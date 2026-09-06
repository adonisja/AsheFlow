"""The revoke endpoint has a front door (ADR-381 D3).

DELETE /registration/invite/{employee_id} shipped on 2026-09-05 and nothing
called it: Assets.tsx posted an invite and never revoked one. An endpoint
without a surface is not shipped, which is the whole subject of ADR-381.

The control is gated to the `invited` lifecycle state, mirroring the endpoint's
own guards rather than duplicating their reasoning:

    not_invited  no token exists, so there is nothing to revoke
    invited      a live token -- the only revocable state
    registered   the endpoint 409s: their token is already spent, and the
                 caller almost certainly wants deactivation
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "frontend" / "src" / "pages" / "Assets.tsx"


def _code() -> str:
    """Source with comments stripped.

    Four assertions this session matched prose instead of code -- including one
    on a docstring that explained the very absence being checked.
    """
    src = ASSETS.read_text()
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))


class TestTheControlExists:
    def test_something_calls_the_delete_endpoint(self):
        code = _code()
        assert "axiosClient.delete<" in code and "/registration/invite/" in code, (
            "the revoke endpoint has no caller -- it shipped unreachable"
        )

    def test_the_button_is_wired_to_the_handler(self):
        assert "onClick={() => handleRevokeInvite(emp)}" in _code()


class TestItIsGatedToTheRightState:
    def test_it_renders_only_for_invited(self):
        """A `registered` employee would get a 409, and `not_invited` has no
        token -- offering the button there invites a guaranteed failure."""
        code = _code()
        assert "{lc === 'invited' && (" in code

    def test_it_is_not_offered_to_registered_employees(self):
        """The button must not appear in the branch that renders Resend
        Credentials, which is the registered state."""
        code = _code()
        i_revoke = code.index("handleRevokeInvite(emp)")
        i_registered = code.index("{lc === 'registered'")
        assert i_revoke < i_registered, (
            "the revoke control moved into the registered branch"
        )


class TestTheTwoNonErrorOutcomes:
    def test_revoked_false_is_not_reported_as_a_failure(self):
        """The endpoint returns `revoked: false` when there was no live token,
        because the desired end state already holds. Rendering that as an error
        sends the manager hunting for a problem that is not there."""
        code = _code()
        i = code.index("handleRevokeInvite")
        window = code[i:i + 1600]
        assert "res.data.revoked" in window, (
            "the handler ignores the revoked flag and cannot tell the two "
            "success cases apart"
        )
        assert "ok: true" in window
        assert "no pending invite" in window.lower()

    def test_a_real_failure_still_reports_as_one(self):
        code = _code()
        i = code.index("handleRevokeInvite")
        window = code[i:i + 1600]
        assert "ok: false" in window and "errorText(" in window


class TestItConfirmsFirst:
    def test_it_asks_before_revoking(self):
        """Not undoable from the UI -- re-inviting is a separate deliberate act."""
        code = _code()
        i = code.index("handleRevokeInvite")
        window = code[i:i + 700]
        # The confirm must GATE the call, not merely appear. Asserting its
        # presence let a mutant through that wrapped it in `if (false && ...)`:
        # the string was still there, the guard was dead.
        assert "if (!window.confirm(" in window, (
            "the confirm does not gate the revoke -- it must early-return"
        )
        assert ")) return;" in window, (
            "the confirm's negative branch does not abort"
        )
        assert "if (false" not in window and "if (true" not in window, (
            "the confirm guard is short-circuited by a constant"
        )

    def test_the_confirm_says_the_record_survives(self):
        """The manager's alternative was DELETING the employee. If the wording
        does not distinguish the two, they will assume this is that."""
        code = _code()
        i = code.index("handleRevokeInvite")
        window = code[i:i + 900]
        assert "employee record stays" in window

    def test_it_reloads_rather_than_guessing_the_new_state(self):
        code = _code()
        i = code.index("handleRevokeInvite")
        assert "load();" in code[i:i + 1600]
