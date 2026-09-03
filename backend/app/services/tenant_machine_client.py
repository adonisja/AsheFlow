"""Provision a Cognito machine client for a tenant (ADR-364).

Each company's Discord bot authenticates as its OWN app client, carrying a
tenant scope that names the company. Tenancy is therefore established when the
token is issued and cannot be asserted by the caller — which matters because an
M2M access token cannot be revoked (ADR-363 D5). A leaked secret exposes one
tenant, and rotation is per-tenant.

This runs from company creation in the superadmin UI so onboarding never touches
the AWS CLI. Microsoft's guidance on this same pattern calls hand-managing
hundreds of app registrations "a potential maintenance nightmare" — which is
true when they are created by hand, and is the reason this is automated rather
than the reason to avoid the pattern.
"""
import logging
from uuid import UUID

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

# One resource server holds one scope per company. NOT one resource server per
# tenant: the quota is 25 (adjustable to 300) resource servers per pool against
# 1,000 (adjustable to 10,000) app clients, so per-tenant resource servers hit a
# ceiling an order of magnitude sooner.
TENANT_RESOURCE_SERVER = "asheflow.tenant"

# The permission scopes every tenant's bot needs (ADR-363 D3). Identical across
# tenants — the TENANT scope is what separates them.
BOT_SCOPES = (
    "asheflow.bot/dispatch.read",
    "asheflow.bot/dispatch.write",
    "asheflow.bot/employees.read",
    "asheflow.bot/training.read",
)

# Scopes per app client is 50 and NOT adjustable. Five here leaves room, but the
# check is cheap and the failure mode (a client created without its tenant
# scope, authorising nothing) is confusing to diagnose.
_MAX_SCOPES_PER_CLIENT = 50


def tenant_scope(company_id: UUID | str) -> str:
    """The scope naming one company.

    The company UUID, not its slug or name: a name can be edited in the UI, and
    a tenant identifier that can be renamed is one that can be pointed at
    another tenant's data.
    """
    return f"{TENANT_RESOURCE_SERVER}/{company_id}"


def _client():
    return boto3.client("cognito-idp", region_name=settings.aws_region)


def _ensure_tenant_scope(pool_id: str, company_id: UUID, company_name: str) -> None:
    """Add this company's scope to the tenant resource server.

    Read-modify-write, because UpdateResourceServer REPLACES the scope list —
    sending only the new scope would delete every other tenant's scope and
    silently strip authorisation from every other bot.
    """
    c = _client()
    existing = c.describe_resource_server(
        UserPoolId=pool_id, Identifier=TENANT_RESOURCE_SERVER
    )["ResourceServer"]

    scopes = list(existing.get("Scopes", []))
    name = str(company_id)
    if any(s["ScopeName"] == name for s in scopes):
        return  # already present; creation is being retried

    # 100 scopes per resource server is a HARD limit (ADR-364 D2). Past it a
    # second resource server is needed, and the failure should name that rather
    # than surface as a Cognito validation error.
    if len(scopes) >= 100:
        raise RuntimeError(
            f"{TENANT_RESOURCE_SERVER} holds 100 tenant scopes, which is the "
            "hard Cognito limit. Add a second tenant resource server "
            "(asheflow.tenant2) and point new companies at it."
        )

    scopes.append({
        "ScopeName": name,
        # Cognito rejects an empty description, and the company name makes the
        # console legible to whoever is debugging a tenant at 4am.
        "ScopeDescription": (company_name or str(company_id))[:256],
    })
    c.update_resource_server(
        UserPoolId=pool_id,
        Identifier=TENANT_RESOURCE_SERVER,
        Name=existing.get("Name", "AsheFlow Tenants"),
        Scopes=scopes,
    )


def provision_machine_client(company_id: UUID, company_name: str) -> tuple[str, str]:
    """Create this tenant's machine client. Returns (client_id, client_secret).

    The secret is returned ONCE and never persisted. It can be read back later
    with `reveal_machine_client_secret`, so there is no reason to store it.

    Raises RuntimeError with an operator-readable message on any failure: this
    runs inside company creation, and "provisioning failed" with no cause turns
    a tenant onboarding into a support ticket.
    """
    pool_id = settings.aws_cognito_user_pool_id
    scopes = [tenant_scope(company_id), *BOT_SCOPES]
    if len(scopes) > _MAX_SCOPES_PER_CLIENT:
        raise RuntimeError(
            f"{len(scopes)} scopes exceeds Cognito's hard limit of "
            f"{_MAX_SCOPES_PER_CLIENT} per app client."
        )

    try:
        _ensure_tenant_scope(pool_id, company_id, company_name)
        resp = _client().create_user_pool_client(
            UserPoolId=pool_id,
            ClientName=f"AsheFlow-Bot-{company_id}",
            GenerateSecret=True,
            AllowedOAuthFlows=["client_credentials"],
            AllowedOAuthScopes=scopes,
            AllowedOAuthFlowsUserPoolClient=True,
            # One hour (ADR-363 D5). An M2M token cannot be revoked, so lifetime
            # is the entire containment story; a longer window saves nothing and
            # hands a stolen token more time.
            AccessTokenValidity=1,
            TokenValidityUnits={"AccessToken": "hours"},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.error("Machine client provisioning failed for %s: %s", company_id, e)
        if code == "LimitExceededException":
            raise RuntimeError(
                "Cognito app client limit reached for this user pool. Request a "
                "quota increase before onboarding more tenants."
            ) from e
        raise RuntimeError(f"Could not provision the machine client ({code}).") from e

    client = resp["UserPoolClient"]
    return client["ClientId"], client["ClientSecret"]


def reveal_machine_client_secret(client_id: str) -> str:
    """Read a client secret back from Cognito.

    The recovery path for a secret shown once at creation and not stored. Every
    call is worth auditing at the router: this returns a live credential.
    """
    try:
        resp = _client().describe_user_pool_client(
            UserPoolId=settings.aws_cognito_user_pool_id, ClientId=client_id
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        if code == "ResourceNotFoundException":
            raise RuntimeError("That machine client no longer exists in Cognito.") from e
        raise RuntimeError(f"Could not read the machine client ({code}).") from e

    secret = resp["UserPoolClient"].get("ClientSecret")
    if not secret:
        raise RuntimeError("That client was created without a secret.")
    return secret


def delete_machine_client(client_id: str) -> None:
    """Remove a tenant's machine client.

    Best effort by design. A company delete must not fail because Cognito is
    unreachable, but an orphaned client still holds a valid tenant scope, so the
    failure is logged loudly enough to be swept up.
    """
    try:
        _client().delete_user_pool_client(
            UserPoolId=settings.aws_cognito_user_pool_id, ClientId=client_id
        )
    except ClientError as e:
        logger.error(
            "ORPHANED machine client %s could not be deleted: %s. It still holds a "
            "valid tenant scope and must be removed by hand.", client_id, e,
        )
