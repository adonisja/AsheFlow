"""The bot says WHY it cannot authenticate, instead of raising KeyError (ADR-362).

`bot/services/api_client.py` read `resp["AuthenticationResult"]["IdToken"]`
unconditionally. Cognito returns EITHER that OR a `ChallengeName` plus a
`Session`, so any challenge raised `KeyError: 'AuthenticationResult'` — a
message that names neither the cause nor the fix.

The failure is quiet in the worst way: the token refreshes hourly, so the bot
keeps working until its next refresh and then stops, with a stack trace in a log
nobody is watching, an hour after the change that caused it.

A bot cannot ANSWER a challenge — there is no human to read a code out of an
authenticator app. So these do not test recovery. They test that the operator
reading the log learns which challenge fired and what clears it.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / "bot" / "services" / "api_client.py"


def _refresh_source() -> str:
    """The password path's CODE, with its docstring stripped.

    ADR-363 split `_refresh_token` into a dispatcher plus two paths, so this
    follows the logic to `_refresh_token_password`. The challenge handling still
    matters after the split: the password path is retained for rollback, and it
    is what makes a botched cutover legible instead of a KeyError.

    The docstring is stripped because it explains the bug it fixes and so
    mentions AuthenticationResult before the code checks for a challenge, which
    defeats an ordering assertion made against the raw text.
    """
    tree = ast.parse(CLIENT.read_text(errors="ignore"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_refresh_token_password"
    )
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        fn.body.pop(0)
    return ast.unparse(fn)


class TestTheChallengeIsNamedNotCrashedOn:
    def test_the_result_is_never_subscripted_unconditionally(self):
        src = _refresh_source()
        assert "resp['AuthenticationResult']['IdToken']" not in src, (
            "a challenge response has no AuthenticationResult key, so this "
            "raises KeyError instead of reporting what Cognito asked for"
        )

    def test_the_challenge_is_checked_before_the_result(self):
        src = _refresh_source()
        assert "ChallengeName" in src, "the challenge branch is gone"
        assert src.index("ChallengeName") < src.index("AuthenticationResult"), (
            "the result is read before checking for a challenge, which is the "
            "original bug"
        )

    def test_every_reachable_challenge_names_its_remedy(self):
        """Which challenge determines who fixes it and how; a generic message
        sends the reader to the wrong place."""
        src = _refresh_source()
        for challenge in (
            "NEW_PASSWORD_REQUIRED",
            "SOFTWARE_TOKEN_MFA",
            "EMAIL_OTP",
            "SELECT_MFA_TYPE",
            "MFA_SETUP",
        ):
            assert challenge in src, f"{challenge} has no operator guidance"

    def test_an_unknown_challenge_still_reports_rather_than_crashing(self):
        src = _refresh_source()
        assert re.search(r"\.get\(challenge,", src) or "no automated path" in src, (
            "an unrecognised challenge must fall back to a message, not a "
            "KeyError on the remedy lookup"
        )

    def test_a_response_with_neither_branch_is_an_error_not_a_crash(self):
        src = _refresh_source()
        assert 'resp.get("AuthenticationResult")' in src or \
               "resp.get('AuthenticationResult')" in src, (
            "the result must be fetched defensively"
        )
        assert "unexpected response" in src, (
            "a response with neither tokens nor a challenge must say so"
        )

    def test_the_failure_is_loud(self):
        """The bot cannot continue, so it must not swallow this and appear
        healthy while every API call 401s."""
        src = _refresh_source()
        assert "logger.error" in src, "the failure is not logged at error level"
        assert "raise" in src, "a failed auth must propagate, not return None"
