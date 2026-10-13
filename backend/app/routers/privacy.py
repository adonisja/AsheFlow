"""Erasure of Personal Information on Amazon's request (ADR-493 D2).

POST /privacy/erasure            admin — the caller's tenant
POST /privacy/platform-erasure   platform owner  — rows that belong to no tenant
                                 (open-campaign collections, the Library)

Both take {kind, value, dry_run}. `dry_run` defaults to TRUE: a destructive,
unrecoverable action must be asked for explicitly, and the dry run returns
exactly what the real run would touch — per-table counts and every stored
spelling the address matched — so the person erasing confirms first.

A real run writes ONE audit row and ONE ledger row, neither holding the value:
an audit row that stored the address would re-persist what was just erased.
Both carry an HMAC of it instead, which is what lets the ledger be replayed
after a backup restore (D3).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee, get_super_admin
from app.core.config import settings
from app.database import get_db
from app.models.employee import Employee
from app.models.pi_erasure_ledger import PiErasureLedger
from app.services import pi_erasure
from app.services.audit import super_admin_identity, write_audit

router = APIRouter(prefix="/privacy", tags=["privacy"])

# Amazon's requests go to the DSP owner, and the only surface is Company
# Settings, which is admin-only (App.tsx). Management in the gate would hold an
# API with no screen — a role in the gate with no use case (Dimension 2).
_allow_erasure = RoleChecker(["admin"])


class ErasureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["address", "tba"]
    value: str = Field(min_length=3, max_length=200)
    dry_run: bool = True


class ErasureResult(BaseModel):
    dry_run: bool
    kind: str
    total: int
    counts: dict[str, int]
    # Every stored spelling the request matched. Shown to the person who typed
    # the request, so they can see a fold that caught more than they meant.
    matched: list[str]


def _run(db: Session, body: ErasureRequest, company_id, actor: dict) -> ErasureResult:
    if not body.dry_run and not settings.pi_erasure_hmac_key:
        # Without the key the ledger cannot be written, and an unledgered
        # erasure is silently undone by the next backup restore.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Erasure is not configured on this server (missing ledger key). Nothing was changed.",
        )
    req = pi_erasure.Request(kind=body.kind, value=body.value, company_id=company_id)
    res = pi_erasure.erase(db, req, dry_run=body.dry_run)
    out = ErasureResult(
        dry_run=body.dry_run, kind=body.kind, total=sum(res.counts.values()),
        counts=dict(sorted(res.counts.items())), matched=sorted(res.matched_spellings),
    )
    if body.dry_run:
        db.rollback()
        return out

    h = pi_erasure.value_hash(body.kind, body.value, settings.pi_erasure_hmac_key)
    entry = PiErasureLedger(company_id=company_id, kind=body.kind, value_hash=h,
                            erased_by=actor.get("ledger_actor"))
    db.add(entry)
    db.flush()
    write_audit(
        db=db, company_id=str(company_id) if company_id else None,
        actor_id=actor.get("actor_id"),
        action_type="privacy.erasure", target_table="pi_erasure_ledger",
        target_id=str(entry.id),
        after={**actor.get("identity", {}), "kind": body.kind, "value_hash": h,
               "total": out.total, "counts": out.counts},
    )
    db.commit()
    return out


@router.post("/erasure", response_model=ErasureResult)
def erase_for_tenant(
    body: ErasureRequest,
    _: dict = Depends(_allow_erasure),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Erase an address or a package id from the caller's tenant."""
    return _run(db, body, caller.company_id,
                {"actor_id": str(caller.id), "ledger_actor": str(caller.id)})


@router.post("/platform-erasure", response_model=ErasureResult)
def erase_for_platform(
    body: ErasureRequest,
    super_admin: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Erase from rows that belong to no tenant. The platform owner only — not
    support staff (ADR-423 D4: platform staff do not read collected data)."""
    ident = super_admin_identity(super_admin)
    return _run(db, body, None,
                {"actor_id": None, "identity": ident,
                 # "id", not "sub": get_current_user maps the Cognito subject to
                 # `id` (the same key super_admin_identity reads).
                 "ledger_actor": (super_admin.get("id") or "")[:64]})
