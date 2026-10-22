"""The sign-in triggers stay attached (ADR-530 D4).

With PostAuthentication detached nothing spends the enrolment pass, and an
unenrolled admin keeps it forever -- no error, no log line, nothing red. A pool
update is a full replace and has dropped a trigger before (2026-09-02).
"""
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app.tasks import security_infra_health as h

FN = "arn:aws:lambda:us-east-2:586794453404:function:AsheFlow-CognitoPreAuth"


def _pool(lambda_config):
    c = MagicMock()
    c.describe_user_pool.return_value = {"UserPool": {"LambdaConfig": lambda_config}}
    return c


def _check(cfg):
    with patch("boto3.client", return_value=_pool(cfg)):
        return h._check_pool_triggers("us-east-2", "us-east-2_TEST")


def test_both_triggers_attached_is_clean():
    assert _check({"PreAuthentication": FN, "PostAuthentication": FN,
                   "CustomMessage": "arn:aws:lambda:x:y:function:Other"}) == []


def test_a_dropped_post_trigger_is_caught():
    """The silent one: sign-in still works, the pass is never spent."""
    problems = _check({"PreAuthentication": FN})
    assert len(problems) == 1 and "PostAuthentication" in problems[0]
    assert "missing" in problems[0]


def test_a_dropped_pre_trigger_is_caught():
    problems = _check({"PostAuthentication": FN})
    assert any("PreAuthentication" in p for p in problems)


def test_no_lambda_config_at_all_reports_both():
    """What a hand-built update-user-pool leaves behind."""
    assert len(_check({})) == 2


def test_the_wrong_function_is_caught():
    problems = _check({"PreAuthentication": FN,
                       "PostAuthentication": "arn:aws:lambda:us-east-2:1:function:Something"})
    assert any("not AsheFlow-CognitoPreAuth" in p for p in problems)


def test_a_version_qualifier_is_still_the_right_function():
    assert _check({"PreAuthentication": FN + ":3", "PostAuthentication": FN + ":live"}) == []


def test_an_aws_error_is_a_problem_not_a_crash():
    c = MagicMock()
    c.describe_user_pool.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}}, "DescribeUserPool")
    with patch("boto3.client", return_value=c):
        problems = h._check_pool_triggers("us-east-2", "us-east-2_TEST")
    assert problems and "AccessDenied" in problems[0]


def test_no_pool_configured_is_reported():
    assert h._check_pool_triggers("us-east-2", "")


def test_it_is_part_of_the_hourly_run():
    with patch.object(h, "_check_trail", return_value=[]), \
         patch.object(h, "_check_rule_and_lambda", return_value=[]), \
         patch.object(h, "_check_topic", return_value=[]), \
         patch.object(h, "_check_containment_permissions", return_value=[]), \
         patch.object(h, "_check_pool_triggers", return_value=["PostAuthentication trigger is missing"]), \
         patch.object(h, "_check_client_write_attributes", return_value=[]), \
         patch.object(h, "SessionLocal"), \
         patch.object(h, "raise_platform_alert") as alert:
        r = h.check_security_infra()
    assert r["healthy"] is False
    assert "PostAuthentication" in alert.call_args.kwargs["message"]
