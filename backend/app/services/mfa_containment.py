"""Contain an account whose MFA factor was removed (ADR-386).

Unenrolment cannot be PREVENTED: Amplify calls Cognito directly with
`aws.cognito.signin.user.admin`, a scope attached to every API sign-in token that
cannot be stripped, and our backend is not in that call path (ADR-377 D1). So the
control is detect-and-contain, and this module is the contain half.

Two actions, both required, neither sufficient alone:

  forget devices  -- a remembered device SKIPS the MFA challenge, so leaving it
                     lets whoever removed the factor back in on old trust
  global sign-out -- access tokens outlive the preference change, so leaving them
                     keeps the current session alive

Applied to ALL TIERS. A field account is a smaller prize, not a non-prize, and
both actions are cheap and recoverable if the trigger was a false positive.

Shared deliberately: the admin reset endpoint and the EventBridge responder
(ADR-387) must do the SAME thing. Two implementations would drift, and the one
that drifts is the one nobody exercises by hand.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContainmentResult:
    """What actually happened, so a caller can audit and alert on it.

    Both halves are reported separately because they fail independently: a
    global sign-out can succeed while a device forget fails, and "contained"
    without saying which half ran is not something you can act on later.
    """
    devices_forgotten: int
    signed_out: bool
    factor_cleared: bool
    errors: list[str]

    @property
    def fully_contained(self) -> bool:
        return self.signed_out and not self.errors


def contain(username: str, pool_id: str, region: str,
            clear_factor: bool = False) -> ContainmentResult:
    """Forget every remembered device and end every session for `username`.

    `clear_factor=True` ALSO removes the MFA preference. The two callers want
    different things and conflating them caused a real lockout:

      containment (ADR-387)  clear_factor=False -- the factor is the victim's
                             protection. An attacker removed it; re-adding a
                             challenge they cannot answer is the point.
      admin reset (ADR-389)  clear_factor=True  -- the user LOST their
                             authenticator. Leaving the factor in place leaves
                             them locked out, which is what the endpoint exists
                             to fix.

    ADR-386 originally argued the factor could stay because re-enrolment
    overwrites it (ADR-377 D3). True, and irrelevant: enrolment lives at
    /account, behind the sign-in the factor is blocking.

    Never raises. This runs on two unattended paths -- an admin endpoint that
    must not 500, and a Lambda responding to a security event -- and a partial
    containment reported honestly beats an exception that contains nothing.

    Order matters: clear the factor (when asked), then sign out, THEN forget
    devices. Forgetting devices takes one API call per device and a compromised
    session stays live for the duration; ending the session first shrinks that
    window to a single call.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    errors: list[str] = []
    signed_out = False
    factor_cleared = False
    forgotten = 0

    try:
        client = boto3.client("cognito-idp", region_name=region)
    except (ClientError, BotoCoreError) as exc:
        # No client, no containment. Say so rather than returning a zero that
        # reads like "nothing needed doing".
        logger.error("mfa containment: no cognito client: %s", type(exc).__name__)
        return ContainmentResult(0, False, False, [f"client: {type(exc).__name__}"])

    if clear_factor:
        try:
            # EVERY factor type, not just the software token. Cognito treats
            # each as an independent preference, so clearing one leaves the
            # others enabled and the user still challenged -- while this
            # function reports success. That is exactly what happened to
            # walker.test, which kept EMAIL_OTP after a "successful" reset
            # (ADR-391).
            #
            # WebAuthn is deliberately omitted: a passkey is bound to hardware
            # the user still holds, so it is not what strands them, and clearing
            # it would destroy a working credential.
            off = {"Enabled": False, "PreferredMfa": False}
            client.admin_set_user_mfa_preference(
                UserPoolId=pool_id, Username=username,
                SoftwareTokenMfaSettings=off,
                EmailMfaSettings=off,
                SMSMfaSettings=off,
            )
            factor_cleared = True
        except (ClientError, BotoCoreError) as exc:
            errors.append(f"clear_factor: {type(exc).__name__}")
            logger.error("mfa containment: could not clear factor: %s",
                         type(exc).__name__)

    try:
        client.admin_user_global_sign_out(UserPoolId=pool_id, Username=username)
        signed_out = True
    except (ClientError, BotoCoreError) as exc:
        errors.append(f"sign_out: {type(exc).__name__}")
        logger.error("mfa containment: global sign-out failed: %s", type(exc).__name__)

    try:
        resp = client.admin_list_devices(
            UserPoolId=pool_id, Username=username, Limit=60,
        )
        devices = resp.get("Devices", [])
    except (ClientError, BotoCoreError) as exc:
        errors.append(f"list_devices: {type(exc).__name__}")
        logger.error("mfa containment: could not list devices: %s", type(exc).__name__)
        devices = []

    for d in devices:
        key = d.get("DeviceKey")
        if not key:
            continue
        try:
            client.admin_forget_device(
                UserPoolId=pool_id, Username=username, DeviceKey=key,
            )
            forgotten += 1
        except (ClientError, BotoCoreError) as exc:
            # Keep going. Forgetting 2 of 3 leaves a smaller hole than aborting.
            errors.append(f"forget_device: {type(exc).__name__}")
            logger.error(
                "mfa containment: could not forget a device: %s", type(exc).__name__,
            )

    # No username, no device_name, no IP -- device_name carries OS and browser
    # and the IP is personal data (ADR-115 D7). Counts only.
    logger.warning(
        "mfa containment: signed_out=%s devices_forgotten=%d errors=%d",
        signed_out, forgotten, len(errors),
    )
    return ContainmentResult(forgotten, signed_out, factor_cleared, errors)
