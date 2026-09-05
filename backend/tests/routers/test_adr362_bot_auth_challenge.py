"""The bot's auth challenge handling, retired with the path it guarded (ADR-377).

WHAT THIS FILE USED TO DO

`bot/services/api_client.py` once read `resp["AuthenticationResult"]["IdToken"]`
unconditionally. Cognito returns EITHER that OR a `ChallengeName` plus a
`Session`, so any challenge raised `KeyError: 'AuthenticationResult'` -- naming
neither the cause nor the fix, an hour after the change that caused it. ADR-362
made the failure legible; six tests here pinned that legibility.

WHY IT IS GONE

Those tests read `_refresh_token_password`, the USER_PASSWORD_AUTH fallback.
ADR-377 removed that function: a bot has no phone and cannot answer an MFA
challenge, so under `MfaConfiguration: ON` the `asheflow.bot` user account is
refused at sign-in. Keeping the fallback would have left a rollback that looks
like a safety net and provably cannot work.

With the path gone, the bot cannot receive an auth challenge at all. The
machine identity uses `client_credentials`, which has no challenge step and no
refresh token -- verified against a real token in ADR-363.

WHAT REPLACED THE COVERAGE

  test_adr363_machine_identity.py
    test_the_password_path_is_gone          -- the removal stays removed
    test_missing_m2m_credentials_fail_loudly -- the new loud failure
    test_a_token_endpoint_error_is_named     -- OAuth errors stay legible

The lesson ADR-362 taught -- a response with two possible shapes must be
branched on, not subscripted -- is in LEARNING_GUIDE.md and applies to any
client of a challenge-capable API. It is the reason this file existed, and it
outlives the code.

This file is kept as a tombstone rather than deleted so that `git log` on the
path explains itself, and so that reintroducing a password fallback has an
obvious place to restore its tests from.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / "bot" / "services" / "api_client.py"


def test_the_bot_has_no_challengeable_auth_path():
    """The premise of every retired test in this file.

    If a USER_PASSWORD_AUTH path comes back, the bot can be challenged again and
    the ADR-362 legibility tests must come back with it -- restore them from
    git history rather than rewriting them from memory.
    """
    tree = ast.parse(CLIENT.read_text(errors="ignore"))
    names = {
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_refresh_token_password" not in names, (
        "a challengeable auth path is back; ADR-362's challenge-handling tests "
        "were retired on the premise that it was gone (see this file's header)"
    )
    # Check executable code only. A whole-file grep matches this module's own
    # epitaph, and ast.unparse still carries docstrings -- including the one in
    # _refresh_token explaining WHY the password flow was removed. Both would
    # pass on prose describing the absence of the thing being checked. (Same
    # trap as ADR-378's watch-list test, which passed on a comment.)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    code = ast.unparse(tree)
    assert "USER_PASSWORD_AUTH" not in code, (
        "the bot authenticates as a USER again -- that cannot survive "
        "MfaConfiguration: ON (ADR-377)"
    )
