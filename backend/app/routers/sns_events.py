"""SES delivery events from SNS (ADR-445).

UNAUTHENTICATED BY NECESSITY. SNS cannot present a credential, so every request
is verified cryptographically instead (`app.services.sns_verify`). Nothing in
this module may trust a field from the body before `verify()` has returned.

WHY THIS EXISTS. SES accepts a message, returns a MessageId, and the bounce
arrives seconds later out of band -- long after the endpoint that sent it
returned 200 and told an administrator the invite was on its way. Without this
handler that bounce reaches nobody, and the employee sits at
`pending_verification` forever while the admin believes it worked.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.ratelimit import limiter
from app.core.config import settings
from app.database import get_db
from app.models.employee import Employee
from app.models.notification import Notification
from app.services.audit import write_audit
from app.services.sns_verify import SNSVerificationError, verify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sns", tags=["sns"])

# SES bounceType values. 'Transient' is deliberately absent (ADR-445 D3): a full
# mailbox is not a bad address, AWS does not suppress it, and flagging it would
# train admins to ignore the flag.
_HARD = "Permanent"
_COMPLAINT = "Complaint"

# An SES event is a few KB. Generous ceiling, but a ceiling: this endpoint takes
# a raw body from anyone who can reach it (ADR-445 D2).
_MAX_BODY_BYTES = 256 * 1024


def _expected_topic() -> str | None:
    return getattr(settings, "sns_ses_topic_arn", None) or None


def _confirm_subscription(msg: dict) -> None:
    """Complete the SNS handshake, but only for OUR topic.

    Reached only after the signature verified, so the SubscribeURL is AWS's own.
    """
    url = msg.get("SubscribeURL")
    if not url:
        return
    try:
        requests.get(url, timeout=5).raise_for_status()
        logger.info("Confirmed SNS subscription for %s", msg.get("TopicArn"))
    except requests.RequestException:
        # Logged, not raised: AWS retries the confirmation, and a 500 here would
        # make the subscription look broken when it is merely slow.
        logger.error("SNS subscription confirmation failed for %s", msg.get("TopicArn"))


def _recipients(payload: dict) -> tuple[list[str], str | None]:
    """The addresses that failed, and how.

    A single SES event can name several recipients, and they can fail for
    different reasons -- so the bounce type is read once per event and the
    addresses are collected together, which is how SES actually shapes it.
    """
    kind = payload.get("eventType") or payload.get("notificationType")

    if kind == "Bounce":
        bounce = payload.get("bounce", {}) or {}
        if bounce.get("bounceType") != _HARD:
            return [], None
        return ([r.get("emailAddress") for r in bounce.get("bouncedRecipients", [])
                 if r.get("emailAddress")], _HARD)

    if kind == "Complaint":
        complaint = payload.get("complaint", {}) or {}
        return ([r.get("emailAddress") for r in complaint.get("complainedRecipients", [])
                 if r.get("emailAddress")], _COMPLAINT)

    return [], None


def _flag(db: Session, address: str, bounce_type: str, when: datetime) -> int:
    """Flag EVERY employee row holding this address. Returns rows touched.

    Email is unique per company, NOT globally (uq_employees_company_email), so
    the same person working at two DSPs has two rows. Updating only the first
    match is the cross-tenant bug hiding in this feature: the second company's
    admin would keep resending into a dead mailbox with no indication why.
    """
    # DIMENSION 1 — DELIBERATELY UNSCOPED, and the only query in this codebase
    # that should be. There is no caller and therefore no caller.company_id: the
    # request is from AWS, about an address, not from a person about their
    # tenant. Scoping this to one company would be the bug (see the docstring),
    # and the flag it writes is only ever read back through an authenticated,
    # company-scoped endpoint. Do not "fix" this by adding a company filter.
    rows = db.query(Employee).filter(Employee.email == address).all()
    touched = 0

    for emp in rows:
        # Idempotent on the event's own timestamp -- SNS guarantees at-least-once
        # delivery, so the same bounce arrives more than once and must not
        # produce a second notification.
        #
        # Compared as a naive UTC instant: a value that has been through the
        # database may come back without tzinfo (SQLite drops it outright, and
        # a column read can differ from the value just assigned), and comparing
        # an aware datetime to a naive one raises TypeError in Python rather
        # than returning False. That would turn a duplicate delivery into a 500.
        existing = emp.email_bounced_at
        if existing is not None and emp.email_bounce_type == bounce_type:
            if existing.tzinfo is not None:
                existing = existing.astimezone(timezone.utc).replace(tzinfo=None)
            if existing == when.replace(tzinfo=None):
                continue

        emp.email_bounced_at = when
        emp.email_bounce_type = bounce_type
        touched += 1

        reason = ("reported the message as spam" if bounce_type == _COMPLAINT
                  else "could not be delivered to")
        managers = db.query(Employee).filter(
            Employee.company_id == emp.company_id,
            Employee.role.in_(["management", "admin"]),
            Employee.is_active.is_(True),
            # Never the person whose own address bounced, even when they are the
            # manager. Their mail does not work -- that is the entire point --
            # and an in-app notice about their own dead address tells them
            # nothing they can act on that the employee record does not.
            Employee.id != emp.id,
        ).all()
        for manager in managers:
            db.add(Notification(
                company_id=emp.company_id,
                employee_id=manager.id,
                type="email_bounced",
                # The employee's NAME, never the address (Dimension 7). The
                # admin can see the address on the employee record; a
                # notification list is a wider audience than that record.
                message=(f"Email to {emp.name} {reason} their address. "
                         f"Check the address on their profile and resend."),
            ))

        write_audit(
            db=db,
            company_id=emp.company_id,
            actor_id=None,  # AWS, not a person
            action_type="employee.email_bounced",
            target_table="employees",
            target_id=str(emp.id),
            detail={"bounce_type": bounce_type, "source": "ses"},
        )

    return touched


@router.post("/ses-events", status_code=status.HTTP_200_OK)
# DIMENSION 11. Unauthenticated, and every request costs an RSA verification
# and possibly an outbound certificate fetch -- so it is cheap to attack and
# not cheap to serve. Keyed on the real client IP: ProxyHeadersMiddleware
# (main.py:57) resolves X-Forwarded-For, without which this would rate-limit
# the load balancer as one client.
#
# 120/minute is far above real SES volume (a few events per day) and far below
# what would hurt. A genuine burst -- a bulk import bouncing at once -- arrives
# from SNS batched, not as 120 separate posts.
@limiter.limit("120/minute")
async def ses_events(request: Request, db: Session = Depends(get_db)) -> dict:
    """Receive a verified SES bounce or complaint.

    Always answers 200 on a verified message, including one naming nobody we
    know. SNS retries a non-2xx for hours and then disables the subscription;
    "this is not our employee" is a successful delivery of an irrelevant fact,
    not a failure.
    """
    raw = await request.body()

    # DIMENSION 9 — a raw body instead of a Pydantic model, which is the
    # exception this dimension allows and not an oversight. The signature is
    # computed over the EXACT bytes AWS sent; parsing into a model and
    # re-serialising loses key order and numeric formatting, so a
    # model-validated body cannot be verified at all.
    #
    # The bound D9 asks for is therefore applied here as a size cap rather than
    # field constraints. An SES event is a few KB; 256 KB is generous and stops
    # an unauthenticated endpoint from being an unbounded-memory sink.
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large.")

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Malformed request body.")

    # A JSON scalar or list parses fine and then fails on .get() with a 500.
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=400, detail="Malformed request body.")

    try:
        verify(envelope, expected_topic_arn=_expected_topic())
    except SNSVerificationError as exc:
        # The reason is logged, never returned: a prober must not learn whether
        # they failed on the host check, the signature, or the topic.
        logger.warning("Rejected unverified SNS message: %s", exc)
        raise HTTPException(status_code=403, detail="Message could not be verified.")

    msg_type = envelope.get("Type")
    if msg_type == "SubscriptionConfirmation":
        _confirm_subscription(envelope)
        return {"status": "subscription confirmed"}

    if msg_type != "Notification":
        return {"status": "ignored"}

    try:
        payload = json.loads(envelope.get("Message") or "{}")
    except json.JSONDecodeError:
        logger.error("Verified SNS message carried a malformed SES payload.")
        return {"status": "ignored"}

    addresses, bounce_type = _recipients(payload)
    if not addresses or not bounce_type:
        return {"status": "ignored"}

    when = datetime.now(timezone.utc)
    touched = 0
    for address in addresses:
        touched += _flag(db, address, bounce_type, when)

    if touched:
        db.commit()

    # The count, not 204 -- a silent success after a state change is how nobody
    # notices the handler stopped matching anyone.
    return {"status": "recorded", "employees_flagged": touched}
