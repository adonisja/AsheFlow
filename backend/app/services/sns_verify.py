"""Verify that an SNS message genuinely came from AWS (ADR-445 D2).

THE THREAT. `POST /sns/ses-events` is unauthenticated, because SNS cannot
present a credential. Without this module anyone who finds the URL can post a
message naming any employee's address and have us flag their account as
undeliverable -- a trivial denial-of-onboarding against a competitor's tenant.

THE TRAP, and it is the whole reason this file is not four lines: the message
supplies BOTH the signature and the URL of the certificate that validates it.
Fetch whatever `SigningCertURL` points at and the check proves nothing, because
the attacker signed the payload with the key they also served. Constraining that
URL to an AWS SNS host is not a detail of the verification -- it IS the
verification. Everything else is arithmetic.

Deliberately not using boto3: it has no public SNS signature verifier. The
canonical string construction below is from the AWS documented format, and the
tests pin it against a real RSA key pair.
"""
from __future__ import annotations

import base64
import logging
import re
from urllib.parse import urlparse

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate

logger = logging.getLogger(__name__)

# The certificate host AWS serves from, per region. Anchored at both ends: a
# bare `endswith(".amazonaws.com")` accepts `evil-amazonaws.com` and
# `sns.us-east-2.amazonaws.com.attacker.net`, which is how this check is
# usually defeated.
_CERT_HOST = re.compile(r"^sns\.[a-z0-9-]+\.amazonaws\.com$")

# The fields that are signed, in the order AWS specifies, per message type.
# Order is part of the signature -- a set would silently verify nothing.
_SIGNED_FIELDS = {
    "Notification": ("Message", "MessageId", "Subject", "Timestamp",
                     "TopicArn", "Type"),
    "SubscriptionConfirmation": ("Message", "MessageId", "SubscribeURL",
                                 "Timestamp", "Token", "TopicArn", "Type"),
}
_SIGNED_FIELDS["UnsubscribeConfirmation"] = _SIGNED_FIELDS["SubscriptionConfirmation"]

_CERT_TIMEOUT = 5


class SNSVerificationError(Exception):
    """The message is not provably from AWS. The caller must discard it."""


def _canonical_string(msg: dict) -> bytes:
    """Rebuild the exact bytes AWS signed.

    `Subject` is included only when present -- an absent optional field is
    omitted entirely rather than signed as empty, and getting that wrong makes
    every unsubjected message fail to verify.
    """
    fields = _SIGNED_FIELDS.get(msg.get("Type"))
    if fields is None:
        raise SNSVerificationError("unknown message type")

    parts = []
    for field in fields:
        if field not in msg:
            if field == "Subject":
                continue
            raise SNSVerificationError(f"missing signed field: {field}")
        parts.append(f"{field}\n{msg[field]}\n")
    return "".join(parts).encode("utf-8")


def _fetch_certificate(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SNSVerificationError("certificate URL is not https")
    if not _CERT_HOST.match(parsed.netloc):
        # The load-bearing line in this file.
        raise SNSVerificationError("certificate URL is not an AWS SNS host")

    try:
        resp = requests.get(url, timeout=_CERT_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise SNSVerificationError("could not fetch the signing certificate") from exc
    return resp.content


def verify(msg: dict, *, expected_topic_arn: str | None = None) -> None:
    """Raise SNSVerificationError unless `msg` is a genuine AWS SNS message.

    `expected_topic_arn` is checked AFTER the signature. Checking it first would
    reject forgeries with a different error and tell a prober which ARN we
    listen to; checking it after means an attacker learns nothing either way.
    """
    if msg.get("SignatureVersion") != "1":
        # Version 2 exists (SHA256); AWS still sends 1 for SES event
        # destinations. Refuse rather than guess -- a silently accepted unknown
        # version is an unverified message.
        raise SNSVerificationError("unsupported SignatureVersion")

    for required in ("Signature", "SigningCertURL"):
        if not msg.get(required):
            raise SNSVerificationError(f"missing {required}")

    cert_pem = _fetch_certificate(msg["SigningCertURL"])
    try:
        cert = load_pem_x509_certificate(cert_pem)
        signature = base64.b64decode(msg["Signature"])
    except Exception as exc:
        raise SNSVerificationError("malformed certificate or signature") from exc

    try:
        cert.public_key().verify(
            signature,
            _canonical_string(msg),
            padding.PKCS1v15(),
            hashes.SHA1(),   # AWS SignatureVersion 1 is RSA/SHA1. Not our choice.
        )
    except InvalidSignature as exc:
        raise SNSVerificationError("signature does not match") from exc

    if expected_topic_arn and msg.get("TopicArn") != expected_topic_arn:
        raise SNSVerificationError("message is signed but for a different topic")
