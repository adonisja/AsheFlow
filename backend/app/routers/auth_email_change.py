"""Confirming an admin-started email change from the new inbox (ADR-563 D3).

PUBLIC: the link is the proof. It goes only to the new address, works once,
expires in 72 hours, and is stored only as a hash. Rate-limited on the real
client IP (ADR-562) so a token can't be guessed by volume.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.ratelimit import limiter
from app.services import email_change

router = APIRouter(prefix="/auth/email-change", tags=["auth"])


class _ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(..., min_length=20, max_length=200)


@router.post("/confirm", status_code=status.HTTP_200_OK)
@limiter.limit("20/hour")
def confirm_email_change(request: Request, body: _ConfirmIn, db: Session = Depends(get_db)):
    try:
        result = email_change.confirm_admin_change(db, body.token)
    except email_change.EmailChangeError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {"detail": "Your email is changed. Sign in with your username and password.",
            "signed_out": result["signed_out"]}
