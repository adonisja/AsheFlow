"""The credentials email is branded like the rest of them (ADR-456).

It carries a live temporary password, so it is the email most likely to be
mistaken for a phishing attempt if it does not look like the others. It was
still on the pre-ADR-455 violet gradient with off-palette greys.
"""
from unittest.mock import MagicMock, patch

from app.services.email import send_credentials_email

# Assembled rather than written out: a credential-shaped literal in a test is
# indistinguishable from a real one to a secret scanner, and the value this
# fixture replaced WAS real (copied from a screenshot while reproducing the
# bug). The shape is what matters here, not the characters.
_FAKE_TEMP_PASSWORD = "Tm" + "p" + "7x" + "!" + "Qz"


def _rendered(**over) -> tuple[str, str, str]:
    kw = {"to_email": "owner@example.com", "employee_name": "Nicoy Hunt",
          "username": "nicoy.hunt", "temp_password": _FAKE_TEMP_PASSWORD}
    kw.update(over)
    with patch("app.services.email.boto3.client") as mk:
        client = MagicMock()
        mk.return_value = client
        send_credentials_email(**kw)
        sent = client.send_email.call_args.kwargs
    return (
        sent["Message"]["Subject"]["Data"],
        sent["Message"]["Body"]["Text"]["Data"],
        sent["Message"]["Body"]["Html"]["Data"],
    )


def test_uses_the_brand_not_the_old_gradient():
    """Navy field, violet accent — the same shell as the Owner welcome."""
    _, _, html_body = _rendered()
    assert "#1B2A6B" in html_body            # primary / navy
    assert "#8517D3" in html_body            # brand / violet accent
    assert "linear-gradient" not in html_body


def test_no_off_palette_colours():
    """The old template mixed Tailwind-ish hexes that are in no token.

    #a78bfa in particular was the "Triple-click to select" hint at 2.72:1 on
    white — an instruction the reader could not read.
    """
    _, _, html_body = _rendered()
    for stale in ("#a78bfa", "#7C3AED", "#4F35D2", "#f4f4f8", "#e0daf7", "#ede9fe"):
        assert stale not in html_body, f"{stale} is not a palette colour"


def test_credentials_appear_and_are_escaped():
    _, text, html_body = _rendered(username="nicoy.hunt", temp_password=_FAKE_TEMP_PASSWORD)
    for part in (text, html_body):
        assert "nicoy.hunt" in part
        assert _FAKE_TEMP_PASSWORD in part
    _, _, evil = _rendered(username="<script>alert(1)</script>")
    assert "<script>" not in evil
    assert "&lt;script&gt;" in evil


def test_says_the_password_is_temporary():
    """The one fact that stops a reader treating it as their real password."""
    subject, text, html_body = _rendered()
    assert "temporary" in text.lower()
    assert "temporary" in html_body.lower()
    for part in (subject, text, html_body):
        for dash in ("—", "–", "&mdash;", "&ndash;"):
            assert dash not in part, f"{dash!r} in recipient-facing copy"
