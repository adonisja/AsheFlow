"""ADR-445 D2: the unauthenticated webhook must only accept genuine AWS messages.

Real RSA keys and real signatures throughout — no mocking of the crypto. A test
that mocks `verify()` proves the caller calls it; only a real signature proves
the verifier rejects a forgery, which is the property that matters on an
endpoint anyone can POST to.
"""
import base64
import datetime
import json

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.services.sns_verify import SNSVerificationError, verify

GOOD_CERT_URL = "https://sns.us-east-2.amazonaws.com/SimpleNotificationService-abc.pem"
TOPIC = "arn:aws:sns:us-east-2:123456789012:asheflow-delivery"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM)


def _sign(key, msg: dict) -> dict:
    """Build the canonical string the way AWS does and sign it."""
    fields = (("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type")
              if msg["Type"] == "Notification"
              else ("Message", "MessageId", "SubscribeURL", "Timestamp",
                    "Token", "TopicArn", "Type"))
    canonical = "".join(f"{f}\n{msg[f]}\n" for f in fields if f in msg)
    sig = key.sign(canonical.encode(), padding.PKCS1v15(), hashes.SHA1())
    return {**msg, "Signature": base64.b64encode(sig).decode(),
            "SigningCertURL": GOOD_CERT_URL, "SignatureVersion": "1"}


def _notification(key, **over) -> dict:
    base = {
        "Type": "Notification",
        "MessageId": "m-1",
        "TopicArn": TOPIC,
        "Timestamp": "2026-09-19T00:00:00.000Z",
        "Message": json.dumps({"eventType": "Bounce"}),
    }
    base.update(over)
    return _sign(key, base)


@pytest.fixture
def served_cert(monkeypatch, keypair):
    """Serve the real certificate for any URL the verifier is willing to fetch."""
    _, pem = keypair

    class Resp:
        content = pem
        def raise_for_status(self): pass

    monkeypatch.setattr("app.services.sns_verify.requests.get", lambda *a, **k: Resp())
    return pem


def test_a_genuine_message_verifies(keypair, served_cert):
    key, _ = keypair
    verify(_notification(key), expected_topic_arn=TOPIC)


def test_a_tampered_message_is_rejected(keypair, served_cert):
    """The payload is what an attacker wants to change — the address to flag."""
    key, _ = keypair
    msg = _notification(key)
    msg["Message"] = json.dumps({"eventType": "Bounce", "tampered": True})
    with pytest.raises(SNSVerificationError):
        verify(msg, expected_topic_arn=TOPIC)


def test_a_message_signed_by_the_wrong_key_is_rejected(keypair, served_cert):
    """The core forgery: a well-formed message signed by someone else."""
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    msg = _notification(attacker)
    with pytest.raises(SNSVerificationError):
        verify(msg, expected_topic_arn=TOPIC)


@pytest.mark.parametrize("url", [
    "https://evil.com/cert.pem",
    "https://sns.us-east-2.amazonaws.com.evil.com/cert.pem",  # suffix smuggling
    "https://evil-sns.us-east-2.amazonaws.com/cert.pem",      # prefix smuggling
    "http://sns.us-east-2.amazonaws.com/cert.pem",            # downgraded to http
    "https://s3.amazonaws.com/cert.pem",                      # AWS, wrong service
])
def test_the_certificate_url_must_be_an_aws_sns_host(keypair, monkeypatch, url):
    """THE load-bearing check.

    The message supplies both the signature and the certificate that validates
    it, so an unconstrained SigningCertURL means the attacker signs with a key
    they also serve — and every other check passes. These must fail BEFORE any
    fetch happens.
    """
    key, _ = keypair

    def explode(*a, **k):
        raise AssertionError(f"fetched a non-AWS certificate URL: {url}")

    monkeypatch.setattr("app.services.sns_verify.requests.get", explode)

    msg = _notification(key)
    msg["SigningCertURL"] = url
    with pytest.raises(SNSVerificationError):
        verify(msg, expected_topic_arn=TOPIC)


def test_a_valid_signature_for_another_topic_is_rejected(keypair, served_cert):
    """Signed by AWS, but not for us — another account's topic pointed at our URL."""
    key, _ = keypair
    msg = _notification(key, TopicArn="arn:aws:sns:us-east-2:999:someone-else")
    with pytest.raises(SNSVerificationError):
        verify(msg, expected_topic_arn=TOPIC)


def test_an_unknown_signature_version_is_refused(keypair, served_cert):
    """Refuse rather than guess: a silently accepted version is unverified."""
    key, _ = keypair
    msg = _notification(key)
    msg["SignatureVersion"] = "2"
    with pytest.raises(SNSVerificationError):
        verify(msg, expected_topic_arn=TOPIC)


def test_a_missing_signature_is_refused(keypair, served_cert):
    key, _ = keypair
    msg = _notification(key)
    del msg["Signature"]
    with pytest.raises(SNSVerificationError):
        verify(msg, expected_topic_arn=TOPIC)


def test_subscription_confirmation_verifies_with_its_own_field_set(keypair, served_cert):
    """A different message type signs a different field list, in a fixed order."""
    key, _ = keypair
    msg = _sign(key, {
        "Type": "SubscriptionConfirmation",
        "MessageId": "m-2",
        "TopicArn": TOPIC,
        "Timestamp": "2026-09-19T00:00:00.000Z",
        "Message": "confirm me",
        "SubscribeURL": "https://sns.us-east-2.amazonaws.com/?Action=Confirm",
        "Token": "tok",
    })
    verify(msg, expected_topic_arn=TOPIC)


def test_a_subject_when_present_is_part_of_the_signature(keypair, served_cert):
    """Subject is optional; omitted when absent, signed when present.

    Getting this wrong makes every message with a subject fail, or every
    message without one verify against the wrong bytes.
    """
    key, _ = keypair
    msg = _notification(key, Subject="hello")
    verify(msg, expected_topic_arn=TOPIC)

    tampered = dict(msg, Subject="goodbye")
    with pytest.raises(SNSVerificationError):
        verify(tampered, expected_topic_arn=TOPIC)
