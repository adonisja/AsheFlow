"""Set an app client's WriteAttributes (and existence errors) WITHOUT dropping anything else (ADR-558).

Usage: python scripts/cognito_client_update.py <pool-id> <client-id> [--apply]

update-user-pool-client is a FULL REPLACE, exactly like update-user-pool
(ADR-525's four incidents came from omitted fields). So the request is built
from the client's own live config, keeping every field UpdateUserPoolClient
accepts, and only WriteAttributes changes. The accepted fields are read from
botocore's model, not hand-listed, so a field AWS adds later is carried too.

Default is a DRY RUN that prints the diff between the live config and what
would be sent; --apply sends it, then re-reads and diffs before vs after.
"""
import copy
import json
import sys

import boto3
import botocore.session

REGION = "us-east-2"

# ADR-558 D1: the only attributes each app client may write with a USER token.
# Staging's Discord and Google providers map `email`, and Cognito requires a
# mapped attribute to be writable by the client a person federates through.
# Prod has no providers. Never add custom:mfa_first_seen: the PreAuthentication
# Lambda writes it with the admin API, which this list does not restrict.
WRITE_ATTRIBUTES = {
    # staging: Discord/Google sign-in removed (ADR-560), so nothing needs email
    # writable any more. Same reasoning as prod below.
    "us-east-2_SvVO2ofAb": ["locale"],
    # ADR-566: the v3 staging pool, cloned from v2 with the same client allow-list.
    "us-east-2_umklCMhEu": ["locale"],
    # prod: no federated providers, so email must NOT be writable (prod applies a
    # user-level email change immediately, unverified). [] is not a lock -- it
    # reads back as unset -- so the list holds one harmless, unused attribute.
    "us-east-2_AYHjejPis": ["locale"],
}


# ADR-558 D4: every app client answers an unknown username exactly like a wrong
# password. Prod's client was LEGACY ("User does not exist."), and the client id
# ships in the web bundle, so anyone could confirm which first.last names exist.
CLIENT_SETTINGS = {"PreventUserExistenceErrors": "ENABLED"}

# ADR-560: password sign-in only. A federated identity became a SEPARATE
# Cognito user that the backend's email fallback resolved to the employee with
# that email -- proved on staging 2026-10-21: no MFA, no groups, acted as
# manager.test. This only ever REMOVES non-Cognito providers from the live
# list; it never adds one (prod's list is null, and adding COGNITO would switch
# on a hosted sign-in page nothing uses).
ALLOWED_IDENTITY_PROVIDERS = {"COGNITO"}


def accepted_fields() -> list[str]:
    model = botocore.session.get_session().get_service_model("cognito-idp")
    return list(model.operation_model("UpdateUserPoolClient").input_shape.members)


def live(client, pool: str, client_id: str) -> dict:
    return client.describe_user_pool_client(UserPoolId=pool, ClientId=client_id)["UserPoolClient"]


def request(cfg: dict, write: list[str], fields: list[str]) -> dict:
    cfg = copy.deepcopy(cfg)          # never mutate the snapshot the diff is taken against
    req = {k: cfg[k] for k in fields if k in cfg and cfg[k] is not None}
    req["UserPoolId"], req["ClientId"] = cfg["UserPoolId"], cfg["ClientId"]
    req["WriteAttributes"] = list(write)
    req.update(CLIENT_SETTINGS)
    if cfg.get("SupportedIdentityProviders"):
        req["SupportedIdentityProviders"] = [
            p for p in cfg["SupportedIdentityProviders"] if p in ALLOWED_IDENTITY_PROVIDERS]
    return req


def flat(d, p=""):
    if isinstance(d, dict):
        r = {}
        for k, v in d.items():
            r.update(flat(v, f"{p}.{k}" if p else k))
        return r
    return {p: json.dumps(d, sort_keys=True, default=str)}   # boto3 returns datetimes


def diff(a: dict, b: dict) -> list[str]:
    fa, fb = flat(a), flat(b)
    return [f"  {k}: {fa.get(k)} -> {fb.get(k)}" for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)]


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    pool, client_id, apply = argv[1], argv[2], "--apply" in argv
    if pool not in WRITE_ATTRIBUTES:
        print(f"No WRITE_ATTRIBUTES entry for {pool}; add one deliberately.", file=sys.stderr)
        return 2
    cog = boto3.client("cognito-idp", region_name=REGION)
    before = live(cog, pool, client_id)
    req = request(before, WRITE_ATTRIBUTES[pool], accepted_fields())
    # Fields the live client has that the request won't carry: anything here is
    # either read-only (dates, secret) or a field this script would DROP.
    dropped = sorted(k for k in before if k not in req and before[k] is not None)
    print(f"{before['ClientName']} ({client_id}) in {pool}")
    print("not sent (must all be read-only):", dropped)
    print("would change:" if not apply else "changing:")
    print("\n".join(diff({k: before.get(k) for k in req}, req)) or "  (nothing)")
    if not apply:
        print("\nDRY RUN. Re-run with --apply to send.")
        return 0
    cog.update_user_pool_client(**req)
    after = live(cog, pool, client_id)
    print("\nlive before -> after:")
    print("\n".join(diff(before, after)) or "  (nothing)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
