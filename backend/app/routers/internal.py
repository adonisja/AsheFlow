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

import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.company_config import get_discord_config

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
