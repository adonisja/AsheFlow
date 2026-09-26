"""An Owner is never challenged on a phone number nobody recorded (ADR-457 D2).

The last-4 challenge works for field staff because a manager recorded the
number from hiring paperwork before the invite went out. For an admin there is
no such prior record, so the only way to populate one is to ask the person and
type in what they say -- after which they "confirm" their own input.

Today the Create Owner form collects no phone, so an admin's phone_number is
NULL and the challenge cannot fire. These tests pin the RULE rather than that
accident: adding a phone field to Create Owner must not resurrect it.
"""
import ast
import inspect
import pathlib

from app.routers import registration as R


def _validate_src() -> str:
    return inspect.getsource(R.validate_token)


def test_admin_is_exempt_from_the_challenge():
    assert "admin" in R._NO_PHONE_CHALLENGE_ROLES


def test_the_exemption_is_applied_where_phone_last4_is_built():
    """Guards the constant being defined and then not consulted."""
    src = _validate_src()
    assert "_NO_PHONE_CHALLENGE_ROLES" in src, (
        "validate_token no longer consults the exemption, so an admin with a "
        "phone number would be challenged on it"
    )
    # The guard must sit on the same condition that sets phone_last4, not in a
    # branch that happens to run earlier.
    tree = ast.parse(src.lstrip())
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "_NO_PHONE_CHALLENGE_ROLES" in ast.dump(node.test):
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            if "phone_last4" in body:
                guarded = True
    assert guarded, "the role check does not gate the phone_last4 assignment"


def test_field_roles_are_still_challenged():
    """The exemption must not quietly disable the check for everyone."""
    for role in ("driver", "walker", "trainer", "captain", "trainee", "dispatch"):
        assert role not in R._NO_PHONE_CHALLENGE_ROLES, (
            f"{role} has a manager-recorded number and should be challenged"
        )


def test_create_owner_collects_no_phone():
    """The premise of D2, asserted rather than assumed.

    If this fails, someone added a phone to the Owner form -- which is allowed,
    but then the exemption above is the only thing keeping the self-referential
    challenge from appearing, and it should be re-read deliberately.
    """
    src = pathlib.Path("app/routers/companies.py").read_text()
    fn = src.split("class BootstrapAdminPatch")[1].split("def ")[0]
    assert "phone" not in fn.lower(), (
        "Create Owner now collects a phone; re-read ADR-457 D2 before relying "
        "on the challenge being skipped"
    )
