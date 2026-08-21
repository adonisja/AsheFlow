"""ORE completion certificate storage (ADR-281 D2/D3).

WHAT THIS HOLDS, AND FOR HOW LONG
---------------------------------
A phase-0 certificate carries the trainee's name and an Amazon training id, so
the FILE lives 48 hours. The attestation — `ore_completed_at` and who uploaded
it — lives on the TrainingRecord permanently.

That split is the whole design. If the file were the completion signal, a
trainee who finished ORE in March would lose that fact on the third day.

DEFENCE IN DEPTH
----------------
The guarantees here are enforced by AWS, not by this module:

  * the bucket policy DENIES any PutObject without `aws:kms` encryption, so a
    future edit that forgets the header is rejected by S3
  * IAM scopes the role to `ore-certificates/*` in one bucket, so a
    key-construction bug cannot write elsewhere
  * an S3 lifecycle rule expires objects at 1 day as a backstop under the
    nightly sweep's precise 48h deletion
  * versioning is OFF — object versions would outlive the expiry and quietly
    defeat the retention promise

Verified against staging: unencrypted put and out-of-prefix put both return
AccessDenied from the instance role.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Content types a certificate can plausibly be: a PDF export from AtoZ, or a
# photo/screenshot of the completion page.
ALLOWED_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}

# Magic bytes, checked against the FILE rather than the client's Content-Type
# header. A request body is attacker-controlled input (ADR-115 dim 9), and a
# header claiming image/png costs nothing to forge.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
]


class OreCertificateError(RuntimeError):
    """Storage failed. Carries no AWS detail — see sniff_content_type note."""


def is_enabled() -> bool:
    """False when the bucket is unconfigured.

    An environment without the infrastructure should DEGRADE (503 with a clear
    message) rather than throw a boto3 error at a trainee mid-upload.
    """
    return bool(settings.ore_certificate_bucket)


def sniff_content_type(head: bytes) -> str | None:
    """Real content type from magic bytes, or None if it is not an allowed type.

    Returns None rather than raising so the caller owns the HTTP status — this
    module never decides response codes.
    """
    for signature, content_type in _SIGNATURES:
        if head.startswith(signature):
            return content_type
    return None


def build_key(company_id: UUID, record_id: UUID, extension: str) -> str:
    """S3 key for a certificate.

    Company-prefixed so a bucket policy CAN be scoped per tenant later without
    migrating existing objects. Deliberately contains no PII — not the
    trainee's name, not their email. UUIDs and an extension only.
    """
    return f"ore-certificates/{company_id}/{record_id}.{extension}"


def _client():
    return boto3.client("s3", region_name=settings.aws_region)


def upload(key: str, body: bytes, content_type: str) -> datetime:
    """Store a certificate. Returns when the object expires.

    The encryption headers are passed explicitly even though the bucket sets
    SSE-KMS by default: the bucket policy denies puts that omit them, so being
    explicit turns a silent policy dependency into a visible one.
    """
    if not is_enabled():
        raise OreCertificateError("certificate storage is not configured")

    try:
        _client().put_object(
            Bucket=settings.ore_certificate_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=settings.ore_certificate_kms_key_id,
        )
    except (ClientError, BotoCoreError) as exc:
        # Log the AWS detail; do NOT return it. An S3 error can name the bucket
        # and the key, and an HTTP body is the wrong place for either
        # (ADR-115 dim 6).
        logger.error("ore_certificate_upload_failed", extra={"key": key}, exc_info=exc)
        raise OreCertificateError("could not store the certificate") from exc

    return datetime.now(timezone.utc) + timedelta(
        hours=settings.ore_certificate_retention_hours
    )


def presigned_url(key: str) -> str:
    """Short-lived GET URL for a manager.

    The API never proxies file bytes — it hands back a URL that expires. That
    keeps certificate content out of application logs and off the request path.
    """
    if not is_enabled():
        raise OreCertificateError("certificate storage is not configured")
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.ore_certificate_bucket, "Key": key},
            ExpiresIn=settings.ore_presign_ttl_seconds,
        )
    except (ClientError, BotoCoreError) as exc:
        logger.error("ore_certificate_presign_failed", extra={"key": key}, exc_info=exc)
        raise OreCertificateError("could not produce a download link") from exc


def delete(key: str) -> bool:
    """Delete an object. True if it is gone (including if it never existed).

    Idempotent by design: the nightly sweep must be safe to re-run, and S3's
    lifecycle rule may have removed the object first.
    """
    if not is_enabled():
        return False
    try:
        _client().delete_object(Bucket=settings.ore_certificate_bucket, Key=key)
        return True
    except (ClientError, BotoCoreError) as exc:
        logger.warning("ore_certificate_delete_failed", extra={"key": key}, exc_info=exc)
        return False
