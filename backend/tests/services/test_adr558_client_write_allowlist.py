"""App clients write only the attributes they must (ADR-558).

With WriteAttributes unset, a signed-in user can DELETE their own
custom:mfa_first_seen with their own access token and reopen the ADR-548
enrolment window forever. Measured on staging 2026-10-21 with a throwaway user:

  app client, WriteAttributes=null:      delete stamp -> ALLOWED
  temp client created with []:           reads back as None; delete -> ALLOWED
  app client, WriteAttributes=['email']: delete stamp -> REFUSED (NotAuthorizedException)

So an empty list is NOT a lock, and the health check must treat it as unset.
"""
import importlib.util
import pathlib
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app.tasks import security_infra_health as h

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _check(write):
    c = MagicMock()
    c.describe_user_pool_client.return_value = {"UserPoolClient": {"WriteAttributes": write}}
    with patch("boto3.client", return_value=c):
        return h._check_client_write_attributes("us-east-2", "pool", "client")


# ── the hourly check ───────────────────────────────────────────────────────

def test_an_allow_list_of_plain_attributes_is_clean():
    assert _check(["email"]) == []


def test_unset_means_everything_is_writable():
    problems = _check(None)
    assert problems and "EVERY attribute is writable" in problems[0]


def test_an_empty_list_is_also_unset():
    """The trap measured on staging: [] reads back as None and locks nothing."""
    assert _check([])


def test_a_custom_attribute_in_the_list_is_caught():
    problems = _check(["email", "custom:mfa_first_seen"])
    assert problems and "custom:mfa_first_seen" in problems[0]


def test_an_aws_error_is_a_problem_not_a_crash():
    c = MagicMock()
    c.describe_user_pool_client.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "DescribeUserPoolClient")
    with patch("boto3.client", return_value=c):
        assert h._check_client_write_attributes("us-east-2", "pool", "client") == [
            "app client: AccessDeniedException"]


def test_it_is_part_of_the_hourly_run():
    assert "client_write_attributes" in h._checks("us-east-2", "pool")


# ── the script that applies it ─────────────────────────────────────────────

def _script():
    spec = importlib.util.spec_from_file_location("ccu", ROOT / "scripts/cognito_client_update.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_pool_gets_a_non_empty_list_without_custom_attributes():
    s = _script()
    assert set(s.WRITE_ATTRIBUTES) == {"us-east-2_SvVO2ofAb", "us-east-2_AYHjejPis"}
    for pool, attrs in s.WRITE_ATTRIBUTES.items():
        assert attrs, f"{pool}: an empty list is unset, i.e. everything writable"
        assert not [a for a in attrs if a.startswith("custom:")], pool


def test_prod_cannot_change_its_own_email():
    """Prod has no federated providers to need it, and applies a user-level
    email change immediately (AttributesRequireVerificationBeforeUpdate: []).
    Measured on a staging temp client: ['locale'] refuses the email change."""
    assert "email" not in _script().WRITE_ATTRIBUTES["us-east-2_AYHjejPis"]


def test_the_request_carries_every_live_field_and_changes_only_write_attributes():
    """update-user-pool-client is a full replace: an omitted field is reset."""
    s = _script()
    fields = s.accepted_fields()
    live = {f: f"v-{f}" for f in fields}
    live.update(UserPoolId="pool", ClientId="client", WriteAttributes=None,
                CreationDate="read-only", LastModifiedDate="read-only")
    req = s.request(live, ["email"], fields)
    assert req["WriteAttributes"] == ["email"]
    for f in fields:
        if f != "WriteAttributes":
            assert req[f] == live[f], f"{f} would be dropped or changed"
    assert "CreationDate" not in req and "LastModifiedDate" not in req
