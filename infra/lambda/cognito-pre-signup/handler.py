import boto3
import os

POOL_ID = os.environ["USER_POOL_ID"]

_client = None

def _cognito():
    global _client
    if _client is None:
        _client = boto3.client("cognito-idp", region_name="us-east-2")
    return _client


def handler(event, context):
    trigger = event.get("triggerSource", "")

    # Native username/password signup — always blocked (no self-signup in AsheFlow).
    # Managers create accounts via the admin API; this path should never fire in prod.
    if trigger == "PreSignUp_SignUp":
        raise Exception("Self-signup is not allowed. Contact your dispatcher to create an account.")

    # Federated sign-in via Discord or Google.
    # Allow only if a native Cognito user with the same email already exists —
    # meaning a manager pre-created the account. Cognito will then link the
    # federated identity to that existing user automatically.
    if trigger.startswith("PreSignUp_ExternalProvider"):
        email = _extract_email(event)

        if email and _native_user_exists(email):
            # Account pre-exists — allow and auto-confirm/verify so linking works.
            event["response"]["autoConfirmUser"] = True
            event["response"]["autoVerifyEmail"] = True
            return event

        # No matching native account — block.
        raise Exception(
            "No AsheFlow account found for this email address. "
            "Ask your dispatcher to create your account before signing in with Discord or Google."
        )

    # Admin-created accounts (AdminCreateUser trigger) — always allow.
    return event


def _extract_email(event):
    attrs = event.get("request", {}).get("userAttributes", {})
    return attrs.get("email", "").lower().strip() or None


def _native_user_exists(email):
    try:
        resp = _cognito().list_users(
            UserPoolId=POOL_ID,
            Filter=f'email = "{email}"',
            Limit=1,
        )
        # Only count native (non-federated) users — federated users have a username
        # like "Discord_123456" and no password; native users have normal usernames.
        for user in resp.get("Users", []):
            username = user.get("Username", "")
            if not username.startswith(("Discord_", "Google_", "SignInWithApple_")):
                return True
        return False
    except Exception:
        # Fail closed — if we can't verify, block the signup.
        return False
