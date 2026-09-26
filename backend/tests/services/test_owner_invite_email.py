"""The Owner invite is its own email, and says true things (ADR-455).

The employee template says "Your manager has created an AsheFlow account for
you". For an Owner that is false twice: there is no manager yet (this is the
first account in the tenant), and a manager could not create an Owner anyway —
only a platform super-admin can.

These tests read the rendered message that would be handed to SES, so they
fail if the copy regresses OR if a caller is re-pointed at the generic
template.
"""
from unittest.mock import MagicMock, patch

from app.routers import companies as C
from app.services.email import send_owner_invite_email


def _send_and_capture(**kwargs) -> dict:
    """Run the sender against a mocked SES client and return the message."""
    with patch("app.services.email.boto3.client") as mk:
        client = MagicMock()
        mk.return_value = client
        send_owner_invite_email(**kwargs)
        return client.send_email.call_args.kwargs


def _rendered(**over) -> tuple[str, str, str]:
    kw = {"to_email": "owner@example.com", "owner_name": "Nicoy Hunt",
          "company_name": "Test Company", "token": "tok123"}
    kw.update(over)
    sent = _send_and_capture(**kw)
    return (
        sent["Message"]["Subject"]["Data"],
        sent["Message"]["Body"]["Text"]["Data"],
        sent["Message"]["Body"]["Html"]["Data"],
    )


def test_never_claims_a_manager_created_the_account():
    """The whole reason this template exists."""
    subject, text, html_body = _rendered()
    for part in (subject, text, html_body):
        low = part.lower()
        assert "your manager" not in low
        assert "manager has created" not in low


def test_no_dashes_in_recipient_facing_copy():
    """House style: no em or en dashes in an email the customer reads.

    Two short sentences beat one dash-joined clause for someone skimming on a
    phone, and the character renders inconsistently across mail clients.
    """
    subject, text, html_body = _rendered()
    for part in (subject, text, html_body):
        for dash in ("\u2014", "\u2013", "&mdash;", "&ndash;"):
            assert dash not in part, f"{dash!r} in recipient-facing copy"


def test_names_the_company_and_the_role():
    """The BODY must name the company and the role.

    Not the subject: that is a welcome ("Welcome to AsheFlow, Nicoy"), and a
    subject line naming the tenant is not what identifies this email. The body
    is where the recipient learns which company is theirs.
    """
    _, text, html_body = _rendered()
    for part in (text, html_body):
        assert "Test Company" in part
        assert "yours to run" in part


def test_subject_welcomes_by_name():
    subject, _, _ = _rendered(owner_name="Nicoy Hunt")
    assert subject == "Welcome to AsheFlow, Nicoy"


def test_greets_by_first_name_not_full_name():
    """Assert the PROPERTY, not the sentence, so a copy rewrite does not fail here."""
    _, text, html_body = _rendered(owner_name="Nicoy Hunt")
    assert "Hi Nicoy," in text
    assert "Nicoy" in html_body
    assert "Nicoy Hunt" not in html_body, "the greeting should use the first name alone"


def test_company_name_is_html_escaped():
    """A company name is operator-supplied text reaching an HTML sink (D10)."""
    _, _, html_body = _rendered(company_name='Acme <script>alert(1)</script>')
    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body


def test_html_carries_the_register_link_and_no_stray_placeholders():
    import re
    _, text, html_body = _rendered(token="abc987")
    assert "/register?token=abc987" in text
    assert "/register?token=abc987" in html_body
    # An unsubstituted {settings.x} would render literally to the recipient.
    assert not re.search(r"\{[a-z_][a-z_.]*\}", html_body)


def test_brand_colours_not_the_employee_gradient():
    """Navy field, violet accent — the palette's primary and brand.

    The employee template is a full-bleed violet-to-purple gradient, which uses
    the accent as the entire identity. Pinned because a copy-paste from that
    template is exactly how this would regress.
    """
    _, _, html_body = _rendered()
    assert "#1B2A6B" in html_body          # primary / navy
    assert "#8517D3" in html_body          # brand / violet accent
    assert "linear-gradient" not in html_body


def test_owner_routes_use_the_owner_template():
    """Both Owner call sites call send_owner_invite_email, not the generic one.

    Reading the router source: the risk this guards is a future edit
    re-pointing one of these at send_invite_email, which would silently start
    telling Owners about their manager again.
    """
    import inspect
    src = inspect.getsource(C)
    assert "send_owner_invite_email(" in src
    assert "send_invite_email(" not in src, (
        "companies.py should send only Owner invites; a generic send_invite_email "
        "call here would use the 'your manager' copy"
    )
