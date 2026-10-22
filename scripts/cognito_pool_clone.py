"""Create a new Cognito pool as a copy of a live one, plus a sign-in alias (ADR-566).

Usage: python scripts/cognito_pool_clone.py <source-pool-id> <new-pool-name> <domain-prefix> [--apply]

An existing pool can't gain an alias: AliasAttributes, Schema and
UsernameConfiguration are CreateUserPool-only (botocore's model). So the new
pool is built from the live one (ADR-525: never hand-list a config) and the
only intended differences are:
  - AliasAttributes ["preferred_username"]  (owner, item 6)
  - usernames are case-insensitive
  - custom:pw_handed_over exists from birth (ADR-564 D3)
  - deletion protection ACTIVE (prod's was INACTIVE)
  - the app client carries no hosted-UI settings (ADR-560)
  - unused custom attributes are left behind (they can never be removed)

Copied: pool settings, triggers (and the Lambda invoke permission the new pool
needs), MFA config, groups, resource servers + scopes, a hosted domain under a
NEW prefix (prefixes are global and the old pool keeps its own), and the
AsheFlow-App client. NOT copied: users (the account move does that) and the
per-company bot clients (re-provisioned by the move, ADR-364).

Default is a DRY RUN that prints what would be created and every field of the
source that is NOT carried; --apply creates it all and prints the new ids.
"""
import copy
import json
import sys

import boto3
import botocore.session

REGION = "us-east-2"
APP_CLIENT = "AsheFlow-App"
HANDED_OVER = {"Name": "pw_handed_over", "AttributeDataType": "String", "Mutable": True,
               "DeveloperOnlyAttribute": False, "Required": False,
               "StringAttributeConstraints": {"MinLength": "1", "MaxLength": "1"}}

# A custom attribute can never be removed, so one nothing reads is not carried.
# Staging's pool has two from before the database held roles and tenancy; no
# code in backend/, frontend/, mobile/, bot/ or infra/lambda reads either
# (grep, 2026-10-22).
NOT_CARRIED_CUSTOM = {"role", "company_id"}

# Hosted-UI settings left from federated sign-in (removed by ADR-560). The app
# signs in with SRP/password only; prod's client already has none of these.
HOSTED_UI_FIELDS = ("AllowedOAuthFlows", "AllowedOAuthFlowsUserPoolClient", "AllowedOAuthScopes",
                    "CallbackURLs", "LogoutURLs", "DefaultRedirectURI", "SupportedIdentityProviders")

_model = botocore.session.get_session().get_service_model("cognito-idp")


def accepted(op: str) -> list[str]:
    return list(_model.operation_model(op).input_shape.members)


def pool_request(src: dict, name: str) -> dict:
    src = copy.deepcopy(src)   # the diff below is taken against the original
    req = {}
    for k in accepted("CreateUserPool"):
        if k == "PoolName":
            req[k] = name
        elif k in src and src[k] is not None and k not in ("Schema", "AliasAttributes", "UsernameAttributes"):
            req[k] = src[k]
    req.get("AdminCreateUserConfig", {}).pop("UnusedAccountValidityDays", None)
    # Only custom attributes are declared; the standard ones exist in every pool.
    customs = []
    for a in src.get("SchemaAttributes", []):
        if a["Name"].startswith("custom:") and a["Name"][len("custom:"):] not in NOT_CARRIED_CUSTOM:
            a = {k: v for k, v in a.items() if k in ("AttributeDataType", "DeveloperOnlyAttribute", "Mutable",
                                                    "Required", "NumberAttributeConstraints",
                                                    "StringAttributeConstraints")}
            customs.append({"Name": None, **a})
    names = [x["Name"][len("custom:"):] for x in src.get("SchemaAttributes", [])
             if x["Name"].startswith("custom:") and x["Name"][len("custom:"):] not in NOT_CARRIED_CUSTOM]
    for c, n in zip(customs, names):
        c["Name"] = n
    if "pw_handed_over" not in names:
        customs.append(HANDED_OVER)
    req["Schema"] = customs
    req["AliasAttributes"] = ["preferred_username"]
    req["UsernameConfiguration"] = {"CaseSensitive": False}
    req["DeletionProtection"] = "ACTIVE"
    return req


def client_request(src: dict) -> dict:
    req = {k: copy.deepcopy(src[k]) for k in accepted("CreateUserPoolClient")
           if k in src and src[k] is not None and k not in ("UserPoolId",)}
    req["GenerateSecret"] = False
    for k in HOSTED_UI_FIELDS:
        req.pop(k, None)
    return req


def mfa_request(src: dict) -> dict:
    return {k: src[k] for k in accepted("SetUserPoolMfaConfig") if k in src and k != "UserPoolId"}


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    source, name, prefix, apply = sys.argv[1], sys.argv[2], sys.argv[3], "--apply" in sys.argv
    c = boto3.client("cognito-idp", region_name=REGION)
    src = c.describe_user_pool(UserPoolId=source)["UserPool"]
    mfa = c.get_user_pool_mfa_config(UserPoolId=source)
    # Cognito makes a "<pool-id>_<Provider>" group per federated provider; those
    # belong to the source pool and its (removed) providers.
    groups = [g for g in c.list_groups(UserPoolId=source, Limit=60)["Groups"]
              if not g["GroupName"].startswith(source + "_")]
    servers = c.list_resource_servers(UserPoolId=source, MaxResults=50)["ResourceServers"]
    app = [c.describe_user_pool_client(UserPoolId=source, ClientId=x["ClientId"])["UserPoolClient"]
           for x in c.list_user_pool_clients(UserPoolId=source, MaxResults=60)["UserPoolClients"]
           if x["ClientName"] == APP_CLIENT]
    if len(app) != 1:
        sys.exit(f"expected one {APP_CLIENT} client in {source}, found {len(app)}")
    domain_src = c.describe_user_pool_domain(Domain=src["Domain"])["DomainDescription"] if src.get("Domain") else {}

    preq, creq, mreq = pool_request(src, name), client_request(app[0]), mfa_request(mfa)
    print(f"source {source} ({src['Name']}) -> new pool {name!r}, domain {prefix!r}")
    print("  carried pool fields:", sorted(k for k in preq if k not in ("Schema",)))
    print("  custom attributes:", [x["Name"] for x in preq["Schema"]])
    print("  alias:", preq["AliasAttributes"], "| username:", preq["UsernameConfiguration"],
          "| deletion:", preq["DeletionProtection"])
    print("  triggers:", preq.get("LambdaConfig"))
    print("  mfa:", json.dumps(mreq, default=str))
    print("  groups:", sorted(g["GroupName"] for g in groups))
    print("  resource servers:", [(s["Identifier"], len(s.get("Scopes", []))) for s in servers])
    print("  app client fields:", sorted(creq))
    print("  app client hosted-UI fields dropped:", [k for k in HOSTED_UI_FIELDS if app[0].get(k)])
    print("  custom attributes NOT carried:", sorted(NOT_CARRIED_CUSTOM & {x["Name"][len("custom:"):]
          for x in src.get("SchemaAttributes", []) if x["Name"].startswith("custom:")}))
    dropped = sorted(k for k in src if k not in preq and k not in (
        "Id", "Name", "Arn", "Status", "LastModifiedDate", "CreationDate", "SchemaAttributes",
        "EstimatedNumberOfUsers", "Domain", "CustomDomain"))
    print("  source fields NOT carried (read-only or create-time):", dropped)
    if not apply:
        print("DRY RUN — nothing created.")
        return

    pool = c.create_user_pool(**preq)["UserPool"]
    pid, parn = pool["Id"], pool["Arn"]
    print("created pool", pid)
    lam = boto3.client("lambda", region_name=REGION)
    for fn in sorted({v for v in (preq.get("LambdaConfig") or {}).values() if isinstance(v, str)}):
        lam.add_permission(FunctionName=fn, StatementId=f"cognito-{pid.replace('_', '-')}",
                           Action="lambda:InvokeFunction", Principal="cognito-idp.amazonaws.com", SourceArn=parn)
        print("  invoke permission:", fn.split(":")[-1])
    c.set_user_pool_mfa_config(UserPoolId=pid, **mreq)
    for g in groups:
        c.create_group(UserPoolId=pid, **{k: g[k] for k in ("GroupName", "Description", "Precedence", "RoleArn") if k in g})
    for s in servers:
        c.create_resource_server(UserPoolId=pid, Identifier=s["Identifier"], Name=s["Name"], Scopes=s.get("Scopes", []))
    dreq = {"Domain": prefix, "UserPoolId": pid}
    if domain_src.get("ManagedLoginVersion"):
        dreq["ManagedLoginVersion"] = domain_src["ManagedLoginVersion"]
    c.create_user_pool_domain(**dreq)
    new_client = c.create_user_pool_client(UserPoolId=pid, **creq)["UserPoolClient"]
    print(json.dumps({"pool_id": pid, "app_client_id": new_client["ClientId"],
                      "domain": f"{prefix}.auth.{REGION}.amazoncognito.com"}, indent=1))


if __name__ == "__main__":
    main()
