"""Passwords for tests, generated, never written down (ADR-547).

A password-shaped literal in a test is indistinguishable from a real one to
a secret scanner (GitGuardian incident 38384008 stopped PR #80), and one of
ours once WAS real (ADR-456). Splitting the string into pieces only hides it
from the scanner. Every test that needs a password asks for one here, and
test_adr547_no_literal_test_passwords.py fails on any that does not.
"""
import secrets
import string

_SYMBOLS = "!@#$%^&*"
_CLASSES = {
    "upper": string.ascii_uppercase,
    "lower": string.ascii_lowercase,
    "digit": string.digits,
    "symbol": _SYMBOLS,
}


def make_test_password(length: int = 16,
                       classes: tuple[str, ...] = ("upper", "lower", "digit", "symbol")) -> str:
    """A fresh password each call, with one character from each class in
    `classes` and the rest drawn from their union.

    The defaults meet the Cognito policy. A test of a WEAK password narrows
    `classes` or shortens `length` instead of typing one:
    make_test_password(length=6) or make_test_password(classes=("lower",)).
    """
    if not classes or length < len(classes):
        raise ValueError("length must cover one character from each class")
    pools = [_CLASSES[c] for c in classes]
    chars = [secrets.choice(p) for p in pools]
    union = "".join(pools)
    chars += [secrets.choice(union) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
