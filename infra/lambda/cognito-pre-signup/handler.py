"""PreSignUp trigger, attached to both pools.

No account in AsheFlow is created by signing up: managers and super admins
create accounts with the admin API (AdminCreateUser, which this allows). Both
self-signup and federated sign-up are refused (ADR-560), so this needs no AWS
client and no pool lookup -- the pool-pinning bug ADR-362 fixed here can't
recur because there is no lookup left to pin.
"""


def handler(event, context):
    trigger = event.get("triggerSource", "")

    # Native username/password signup — always blocked (no self-signup in AsheFlow).
    # Managers create accounts via the admin API; this path should never fire in prod.
    if trigger == "PreSignUp_SignUp":
        raise Exception("Self-signup is not allowed. Contact your dispatcher to create an account.")

    # ADR-560: federated sign-in is removed. This branch used to admit a Discord
    # or Google sign-in whenever ANY native user had the same email, claiming
    # Cognito would then link the two. It doesn't (that needs
    # AdminLinkProviderForUser): it created a separate Discord_/Google_ user,
    # which the backend's email fallback resolved to the employee -- no password,
    # no MFA (proved on staging). Refuse it outright, so re-adding a provider
    # without a design admits nobody.
    if trigger.startswith("PreSignUp_ExternalProvider"):
        raise Exception("Sign in with your AsheFlow username and password.")

    # Admin-created accounts (AdminCreateUser trigger) — always allow.
    return event
