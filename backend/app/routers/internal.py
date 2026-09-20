"""internal.py — bot-to-backend internal API endpoints.

These endpoints are NOT protected by Cognito JWT.  They use a shared
X-Internal-Secret header instead and are only reachable from the bot
container on the internal Docker network.

Endpoints:
  GET /internal/guild-config/{company_id}
    Returns the Discord guild/channel/role config for the given company.
    The bot calls this on startup and caches the result for 5 minutes.
    Returns 404 if the company doesn't exist.
    Returns 200 with all-null fields if Discord is not configured yet
    (bot should skip Discord operations for that company).
"""

import logging
import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.ratelimit import limiter
from app.services.company_config import get_discord_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

_INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET") or ""

if not _INTERNAL_SECRET:
    import logging as _logging
    _logging.getLogger(__name__).critical(
        "INTERNAL_SECRET is not set — internal endpoints will reject all requests. "
        "Set INTERNAL_SECRET in the environment before starting the server."
    )


def _verify_secret(x_internal_secret: str = Header(default="")) -> None:
    if not _INTERNAL_SECRET or x_internal_secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


class GuildConfigResponse(BaseModel):
    company_id:          str
    guild_id:            int | None
    drivers_channel_id:  int | None
    trainers_channel_id: int | None
    captains_channel_id: int | None
    general_channel_id:  int | None
    invite_channel_id:   int | None
    role_admin:          int | None
    role_manager:        int | None
    role_asheflow:       int | None
    role_bot:            int | None
    role_dispatch:       int | None
    role_driver:         int | None
    role_trainer:        int | None
    role_captain:        int | None
    role_walker:         int | None
    is_configured:       bool


class GuildOwnerResponse(BaseModel):
    """Which company owns a Discord guild (ADR-446 D2).

    The INVERSE of /guild-config/{company_id}, for the one caller that has a
    guild and needs the company: the bot warming its reverse map at startup.

    Deliberately NOT a "list every company and its guild" endpoint. That would
    hand anyone holding INTERNAL_SECRET a complete tenant roster in a single
    request, and ADR-441 raised the value of that secret precisely because it
    now spans tenants. Asking one guild at a time returns only what the caller
    could already observe by being in the guild.
    """
    company_id: str


class MachineCredentialResponse(BaseModel):
    """One tenant's Cognito machine credential.

    Returns a LIVE secret, which is why the endpoint is audited and rate
    limited. It is the narrowest way for the bot to authenticate as the tenant
    whose guild sent a command (ADR-441 D1).
    """
    company_id:    str
    client_id:     str
    client_secret: str


@router.get(
    "/machine-credentials/{company_id}",
    response_model=MachineCredentialResponse,
    dependencies=[Depends(_verify_secret)],
)
@limiter.limit("30/minute")
def get_machine_credentials(
    request: Request,
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> MachineCredentialResponse:
    """The machine credential for ONE company (ADR-441 D1).

    THE BOT CANNOT USE THE SUPER-ADMIN REVEAL ENDPOINT. That one is gated on
    get_super_admin, so giving the bot a token for it would hand it every
    tenant's secret plus everything else a super admin can do. This channel is
    the narrower instrument, and the bot already authenticates to it with
    X-Internal-Secret to read guild config.

    This does not restore the blast radius ADR-364 rejected. That was about one
    COGNITO credential authorising every tenant, with no revocation because an
    M2M token cannot be revoked (ADR-363 D5). Each tenant still has its own
    client, scope and rotation; what is shared is INTERNAL_SECRET, which was
    already shared, is not a Cognito credential, and can be rotated in one place.

    Rate limited because a leaked INTERNAL_SECRET enumerating every tenant's
    secret should be slow and loud rather than a single loop.
    """
    from app.models.company import Company
    from app.services.audit import write_audit
    from app.services.tenant_machine_client import reveal_machine_client_secret

    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Company not found")
    if not company.machine_client_id:
        # 404, not 500: a company without a provisioned client is a normal
        # state (ADR-364 provisions after the commit, so creation can succeed
        # and provisioning fail), and the bot's fallback handles it.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No machine client provisioned for this company")

    try:
        secret = reveal_machine_client_secret(company.machine_client_id)
    except RuntimeError as exc:
        logger.warning("machine credential read failed for %s: %s", company_id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Could not read the machine credential.")

    # ADR-441 D4. A credential read that leaves no trace is indistinguishable
    # from an exfiltration. Names the company, never the secret.
    write_audit(
        db=db,
        company_id=str(company.id),
        action_type="company.machine_client_secret_read",
        target_table="companies",
        target_id=str(company.id),
        detail={"client_id": company.machine_client_id, "reader": "internal"},
    )
    db.commit()

    return MachineCredentialResponse(
        company_id=str(company.id),
        client_id=company.machine_client_id,
        client_secret=secret,
    )


@router.get(
    "/guild-config/{company_id}",
    response_model=GuildConfigResponse,
    dependencies=[Depends(_verify_secret)],
)
def get_guild_config(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> GuildConfigResponse:
    from app.models.company import Company
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    cfg = get_discord_config(db, company_id)
    return GuildConfigResponse(
        company_id          = str(company_id),
        guild_id            = cfg.guild_id,
        drivers_channel_id  = cfg.drivers_channel_id,
        trainers_channel_id = cfg.trainers_channel_id,
        captains_channel_id = cfg.captains_channel_id,
        general_channel_id  = cfg.general_channel_id,
        invite_channel_id   = cfg.invite_channel_id,
        role_admin          = cfg.role_admin,
        role_manager        = cfg.role_manager,
        role_asheflow       = cfg.role_asheflow,
        role_bot            = cfg.role_bot,
        role_dispatch       = cfg.role_dispatch,
        role_driver         = cfg.role_driver,
        role_trainer        = cfg.role_trainer,
        role_captain        = cfg.role_captain,
        role_walker         = cfg.role_walker,
        is_configured       = cfg.is_configured,
    )


@router.get(
    "/guild-owner/{guild_id}",
    response_model=GuildOwnerResponse,
    dependencies=[Depends(_verify_secret)],
)
@limiter.limit("30/minute")
def get_guild_owner(
    request: Request,
    guild_id: int,
    db: Session = Depends(get_db),
) -> GuildOwnerResponse:
    """Resolve a Discord guild id to the company that owns it (ADR-446 D2).

    Rate limited on the same grounds as the machine-credential route: a leaked
    INTERNAL_SECRET probing guild ids should not be able to enumerate the
    tenant estate quickly.

    404 when no company claims the guild. That is a real answer, not an error
    condition -- the bot may sit in a guild we do not manage, and the caller
    logs it and moves on.
    """
    from app.models.company import Company

    # DIMENSION 1 — deliberately unscoped, like ADR-445's bounce lookup. There
    # is no caller tenant to scope to: the whole question is "which tenant owns
    # this guild?", asked by the bot, which holds a guild id and nothing else.
    #
    # `.all()` rather than `.first()` because discord_guild_id carries NO unique
    # constraint. Two companies CAN be configured with the same guild id, and
    # `.first()` would silently resolve members of one tenant's guild to the
    # other tenant's company -- a cross-tenant mix-up that looks like working
    # software. Ambiguity is refused instead of guessed.
    companies = db.query(Company).filter(
        Company.discord_guild_id == guild_id,
    ).all()

    if not companies:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company is configured for this guild.",
        )
    if len(companies) > 1:
        # Only the ids, never the names: the caller is entitled to know the
        # mapping is broken, not to a list of tenants (Dimension 7).
        logger.error(
            "Guild %s is claimed by %d companies: %s. Discord routing for this "
            "guild is ambiguous until one of them is corrected.",
            guild_id, len(companies), [str(c.id) for c in companies],
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This guild is claimed by more than one company.",
        )

    return GuildOwnerResponse(company_id=str(companies[0].id))
