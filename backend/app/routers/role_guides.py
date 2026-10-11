"""`/my-role` -- what your role does here, and what just changed (ADR-494 D4).

This router exists because two notifications needed somewhere to send people.
`graduation` and `operating_mode_change` were GATEs under ADR-487 D8: modals with
no exit but "OK". ADR-494 D1 dropped both to PROMPTs on the grounds that a reader
who proceeds uninformed needs INFORMATION, not a wall -- which only works if
there is somewhere to go. This is that somewhere.

FOUR ENDPOINTS, AND WHY DELETE IS A REVERT

    GET    /my-role              the caller's own guide, for their own mode
    GET    /my-role/all          every role's guide (admin + management)
    PATCH  /my-role/{role}       the tenant rewrites one      (admin only)
    DELETE /my-role/{role}       back to the platform's text  (admin only)

DELETE restores the seed rather than removing the row, and that is a security
decision, not a convenience. A hard delete would let an admin empty their own
company's `timecard_mismatch` gate explanation -- the gate would still fire, with
nothing behind its only link. ADR-494 D9: a destructive verb on a row the GATE
depends on must not be able to produce a gate with no exit.

NOT MODE-GATED (D4)

No `RequireMode`. The row is keyed by (company, role, mode) and the read picks
the row matching the company's CURRENT mode -- so a tenant who switches finds the
other set already written. Gating this router by mode would 404 the destination
of the very notification that announces the switch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.company import CompanyConfig
from app.models.employee import Employee
from app.models.role_guide import RoleGuide
from app.services.audit import write_audit
from app.services.role_guide_seeds import SEEDED_ROLES, seed_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/my-role", tags=["role-guides"])

# Every authenticated role reads their own guide -- including the three that
# `notifications.allow_any_auth` omits (captain, field_supervisor,
# driver_trainee). A role gate here that misses a real role would 403 exactly
# the person a role_change notification just sent to this page.
allow_any_auth = RoleChecker(list(SEEDED_ROLES))
allow_oversight = RoleChecker(["management", "admin"])
allow_admin = RoleChecker(["admin"])


# ── schemas ──────────────────────────────────────────────────────────────────

class RoleGuideResponse(BaseModel):
    role: str
    operating_mode: str
    title: str
    body: str
    #: True when the tenant has rewritten this text. The client shows no
    #: "edited" badge to a field user -- this is for the admin editor, so an
    #: admin can see at a glance which guides they own and which still track
    #: the platform's.
    is_customized: bool

    model_config = ConfigDict(from_attributes=True)


class RoleGuideUpdate(BaseModel):
    """D9: a request body, so every field is concrete and bounded.

    No `Any`, no bare `dict`, `extra="forbid"`. `body` is the one free-text
    field and it is capped -- the column is `Text`, so without a cap here a
    single PATCH could store a megabyte and every reader of that role would
    download it.
    """

    title: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=8000)

    model_config = ConfigDict(extra="forbid")


# ── helpers ──────────────────────────────────────────────────────────────────

def _company_mode(db: Session, company_id) -> str:
    """This company's operating mode.

    Reads `CompanyConfig`, NOT `Company` -- `operating_mode` lives on the config
    row, and `Company.operating_mode` does not exist. That mistake is an
    AttributeError at request time rather than at import (CLAUDE.md D3,
    precedent ADR-446), so it is spelled out here rather than left to a reader
    to re-derive.

    Absent config reads as `workforce`, matching `get_my_capabilities` and
    `RequireMode` -- the safe direction, because workforce mode promises less.
    """
    config = (
        db.query(CompanyConfig)
        .filter(CompanyConfig.company_id == company_id)
        .first()
    )
    return config.operating_mode if config else "workforce"


def _fetch(db: Session, company_id, role: str, mode: str) -> RoleGuide | None:
    return (
        db.query(RoleGuide)
        .filter(
            RoleGuide.company_id == company_id,
            RoleGuide.role == role,
            RoleGuide.operating_mode == mode,
        )
        .first()
    )


# ── endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=RoleGuideResponse)
def get_my_role_guide(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_auth),
):
    """The caller's own guide, for their own role and their company's mode.

    Takes no role parameter on purpose: a walker asking for the admin guide is
    asking what admins can do, which is not a question this endpoint answers.
    `/my-role/all` is the oversight read and it is gated.
    """
    mode = _company_mode(db, caller.company_id)
    guide = _fetch(db, caller.company_id, caller.role, mode)

    if guide is None:
        # A role with no seeded row -- a role added to the system without guide
        # text, or a tenant created before the backfill. Reported rather than
        # faked: a 404 here is actionable, whereas an empty page sends the
        # reader looking for a scroll bar.
        logger.warning(
            "no role guide for company=%s role=%s mode=%s",
            caller.company_id, caller.role, mode,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No guide has been written for your role yet. Ask an admin to add one.",
        )

    return RoleGuideResponse(
        role=guide.role,
        operating_mode=guide.operating_mode,
        title=guide.title,
        body=guide.body,
        is_customized=guide.edited_at is not None,
    )


@router.get("/all", response_model=list[RoleGuideResponse])
def list_role_guides(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_oversight),
):
    """Every role's guide for this company's current mode (admin + management).

    Management reads but does not write -- the PATCH is admin-only. A manager
    needs to know what their crews were told; changing it is a different act.
    """
    mode = _company_mode(db, caller.company_id)
    guides = (
        db.query(RoleGuide)
        .filter(
            RoleGuide.company_id == caller.company_id,
            RoleGuide.operating_mode == mode,
        )
        .order_by(RoleGuide.role)
        .all()
    )
    return [
        RoleGuideResponse(
            role=g.role,
            operating_mode=g.operating_mode,
            title=g.title,
            body=g.body,
            is_customized=g.edited_at is not None,
        )
        for g in guides
    ]


@router.patch("/{role}", response_model=RoleGuideResponse)
def update_role_guide(
    role: str,
    payload: RoleGuideUpdate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
):
    """Rewrite one role's guide for this company's current mode.

    Stamps `edited_at`/`edited_by`, which is what stops a later platform
    re-seed from reverting it (`seed_role_guides`). The two columns are set
    together because the model's CHECK requires it -- an edit with no editor is
    not a state this table can hold.
    """
    if role not in SEEDED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown role.",
        )

    mode = _company_mode(db, caller.company_id)
    guide = _fetch(db, caller.company_id, role, mode)
    if guide is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No guide exists for that role yet.",
        )

    guide.title = payload.title
    guide.body = payload.body
    guide.edited_at = datetime.now(timezone.utc)
    guide.edited_by = caller.id

    db.flush()
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="role_guide.update",
        target_table="role_guides",
        target_id=str(guide.id),
        detail={
            "role": role,
            "operating_mode": mode,
            # Lengths, not content: the audit log is read by people who are not
            # entitled to a diff of every page, and a full body per edit would
            # make the log unreadable.
            "title_length": len(payload.title),
            "body_length": len(payload.body),
        },
    )
    db.commit()
    db.refresh(guide)

    return RoleGuideResponse(
        role=guide.role,
        operating_mode=guide.operating_mode,
        title=guide.title,
        body=guide.body,
        is_customized=True,
    )


@router.delete("/{role}", response_model=RoleGuideResponse)
def revert_role_guide(
    role: str,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
):
    """Restore the platform's text for one role. NOT a delete.

    DELETE is the honest verb for what the admin is doing -- discarding their
    customisation -- but the row survives, because a gate's only exit links
    here. ADR-494 D9: if this removed the row, an admin could clear the guide
    behind `timecard_mismatch` and leave their own managers facing a gate whose
    only link 404s. Reverting is destructive to the EDIT and safe for the GATE.

    Returns the restored content, and a count rather than 204, so the caller
    can show what the page now says instead of reporting a silent success.
    """
    if role not in SEEDED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown role.",
        )

    mode = _company_mode(db, caller.company_id)
    guide = _fetch(db, caller.company_id, role, mode)
    if guide is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No guide exists for that role yet.",
        )

    if guide.edited_at is None:
        # Already the platform's text. A 409 rather than a no-op success: the
        # admin believes they are undoing something, and silence would let them
        # think they had.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This guide already uses the platform's text.",
        )

    from app.services.role_guide_seeds import SEED_VERSION, _BODIES

    try:
        title, body = _BODIES[(role, mode)]
    except KeyError:
        # The seed text for this role/mode is gone -- a role removed from the
        # seed module while a tenant's edited row survives. Reverting would
        # need text we no longer have, so refuse rather than blank the page.
        logger.error("no seed text to revert to for role=%s mode=%s", role, mode)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="There is no platform text for this role to restore.",
        ) from None

    guide.title = title
    guide.body = body
    guide.seed_version = SEED_VERSION
    guide.edited_at = None
    guide.edited_by = None

    db.flush()
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="role_guide.revert",
        target_table="role_guides",
        target_id=str(guide.id),
        detail={"role": role, "operating_mode": mode, "seed_version": SEED_VERSION},
    )
    db.commit()
    db.refresh(guide)

    return RoleGuideResponse(
        role=guide.role,
        operating_mode=guide.operating_mode,
        title=guide.title,
        body=guide.body,
        is_customized=False,
    )
